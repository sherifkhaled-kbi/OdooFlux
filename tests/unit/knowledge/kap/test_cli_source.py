"""TST-011-040 (REQ-KAP-006, REQ-KAP-001, REQ-KAP-009): `knowledge source` CLI group.

Contract: cli-surface (source verbs, exit codes 0/1/2/4/5), source-adapter (pinned revision never substituted,
Enterprise without entitlement is SKIPPED_UNAUTHORIZED, OCA/OpenUpgrade labelled non-official, fetch explicit only).
The registry is a file (`--registry`), snapshots live in kb-home (`--kb-home`). Git inputs come from the synthetic
repository built by T030. The socket layer is patched for the whole module, so the default run is offline.
"""

import io
import json
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from odooflux.cli import kap_source
from odooflux.cli.kap_common import EXIT_INTEGRITY, EXIT_OK, EXIT_SOURCE_UNAVAILABLE, EXIT_USAGE, EXIT_VALIDATION
from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.release.audit import verify_audit
from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT = shutil.which("git")
MISSING_SHA = "f" * 40
EMPTY_SUM = "sha256:" + "a" * 64


def _spec(source_id, kind, url, revision, *, official=False, licence="PUBLIC_OPEN", required=True):
    return {
        "source_id": source_id, "kind": kind, "official": official, "url": url,
        "licence_access": licence, "licence_id": "LGPL-3", "branch": "17.0", "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": required,
    }


@unittest.skipUnless(GIT, "git is not installed; the source CLI acquires git sources through git plumbing")
class TestSourceCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._synth_tmp = tempfile.TemporaryDirectory()
        cls.repo = build_synth_repo(Path(cls._synth_tmp.name) / "synth")

    @classmethod
    def tearDownClass(cls):
        cls._synth_tmp.cleanup()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "kb"
        self.registry = self.tmp / "sources.json"
        net = mock.patch.object(socket, "socket", side_effect=AssertionError("network is disabled in tests"))
        net.start()
        self.addCleanup(net.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = knowledge_main(["source", *argv, "--registry", str(self.registry), "--kb-home", str(self.home)])
        return code, out.getvalue(), err.getvalue()

    def add(self, spec) -> int:
        path = self.tmp / f"{spec['source_id']}.json"
        path.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
        code, _, _ = self.run_cli("add", "--file", str(path))
        return code

    def status_of(self, source_id) -> dict:
        code, out, _ = self.run_cli("show", source_id, "--json")
        self.assertEqual(code, EXIT_OK)
        return json.loads(out)

    def git_spec(self, source_id="synth-community-17", revision=None):
        return _spec(source_id, "GIT_COMMUNITY", "local:" + self.repo.path, revision or self.repo.to_sha)

    def test_acquire_offline(self):
        self.assertEqual(self.add(self.git_spec()), EXIT_OK)
        code, out, err = self.run_cli("acquire")
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(self.status_of("synth-community-17")["status"], "RETRIEVED")
        self.assertTrue(list((self.home / "snapshots").glob("ss-*.json")))
        code, _, err = self.run_cli("verify")
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(self.status_of("synth-community-17")["status"], "VERIFIED")
        self.assertTrue(verify_audit(self.home)[0])

    def test_registry_persists_across_invocations(self):
        self.assertEqual(self.add(self.git_spec()), EXIT_OK)
        self.assertTrue(self.registry.is_file())
        code, out, _ = self.run_cli("list", "--json")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual([s["source_id"] for s in json.loads(out)["sources"]], ["synth-community-17"])
        self.assertEqual(self.add(self.git_spec()), EXIT_VALIDATION)  # duplicate id is refused

    def test_missing_revision_exit4(self):
        self.assertEqual(self.add(self.git_spec("synth-missing-17", revision=MISSING_SHA)), EXIT_OK)
        self.assertEqual(self.add(self.git_spec("synth-pinned-17")), EXIT_OK)
        code, out, err = self.run_cli("acquire")
        self.assertEqual(code, EXIT_SOURCE_UNAVAILABLE, err)
        missing = self.status_of("synth-missing-17")
        self.assertEqual(missing["status"], "FAILED")
        self.assertTrue(missing["failure_reason"].startswith("REVISION_UNAVAILABLE"))
        self.assertIsNone(missing["checksum"])
        # The pinned source with a present revision is still acquired; nothing was substituted for the missing pin.
        self.assertEqual(self.status_of("synth-pinned-17")["status"], "RETRIEVED")
        self.assertEqual(self.status_of("synth-pinned-17")["revision"], self.repo.to_sha)

    def test_fetch_needs_allow_network_exit2(self):
        self.assertEqual(self.add(_spec("odoo-community-17", "GIT_COMMUNITY",
                                        "https://github.com/odoo/odoo/archive/x.tar.gz", self.repo.to_sha)),
                         EXIT_OK)
        code, _, err = self.run_cli("fetch", "odoo-community-17")
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("allow-network", err)
        self.assertEqual(self.status_of("odoo-community-17")["status"], "DECLARED")

    def test_fetch_never_reaches_off_allowlist_url(self):
        # The allow-list is enforced at `add`, so an off-list source is never registered and fetch cannot use it.
        self.assertEqual(self.add(_spec("other-source-17", "DOCS", "https://example.invalid/docs.tar.gz",
                                        self.repo.to_sha)), EXIT_VALIDATION)
        with mock.patch.object(kap_source, "fetch") as fetch_mock:
            code, _, _ = self.run_cli("fetch", "other-source-17", "--allow-network")
        self.assertEqual(code, EXIT_VALIDATION)
        fetch_mock.assert_not_called()

    def test_fetch_success_applies_retrieved_transition(self):
        url = "https://github.com/odoo/odoo/archive/x.tar.gz"
        self.assertEqual(self.add(_spec("odoo-community-17", "GIT_COMMUNITY", url, self.repo.to_sha)), EXIT_OK)
        fake = {"url": url, "sha256": "a" * 64, "size": 3, "retrieved_at": "2026-11-08T10:00:00Z"}
        with mock.patch.object(kap_source, "fetch", return_value=fake) as fetch_mock:
            code, _, err = self.run_cli("fetch", "odoo-community-17", "--allow-network")
        self.assertEqual(code, EXIT_OK, err)
        self.assertTrue(fetch_mock.call_args.kwargs["allow_network"])
        record = self.status_of("odoo-community-17")
        self.assertEqual(record["status"], "RETRIEVED")
        self.assertEqual(record["checksum"], "a" * 64)
        self.assertEqual(record["retrieved_at"], "2026-11-08T10:00:00Z")

    def test_enterprise_skipped_not_failure(self):
        ent = self.tmp / "enterprise-drop"
        ent.mkdir()
        (ent / "README.txt").write_text("supplied by the user\n", encoding="utf-8")
        self.assertEqual(self.add(_spec("enterprise-local-17", "ENTERPRISE_LOCAL", "local:" + str(ent),
                                        EMPTY_SUM, licence="ENTERPRISE_AUTHORIZED")), EXIT_OK)
        code, _, err = self.run_cli("acquire")
        self.assertEqual(code, EXIT_OK, err)
        self.assertEqual(self.status_of("enterprise-local-17")["status"], "SKIPPED_UNAUTHORIZED")
        # SKIPPED_UNAUTHORIZED is terminal, so an entitled run needs its own registered source.
        self.assertEqual(self.add(_spec("enterprise-entitled-17", "ENTERPRISE_LOCAL", "local:" + str(ent),
                                        EMPTY_SUM, licence="ENTERPRISE_AUTHORIZED")), EXIT_OK)
        code, _, _ = self.run_cli("acquire", "enterprise-entitled-17", "--i-am-entitled")
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.status_of("enterprise-entitled-17")["status"], "RETRIEVED")
        self.assertEqual(self.status_of("enterprise-local-17")["status"], "SKIPPED_UNAUTHORIZED")

    def test_oca_labelled_nonofficial(self):
        self.assertEqual(self.add(_spec("oca-web-17", "OCA", "local:" + self.repo.path, self.repo.to_sha,
                                        official=True)), EXIT_OK)
        code, out, err = self.run_cli("acquire", "oca-web-17")
        self.assertEqual(code, EXIT_OK, err)
        record = self.status_of("oca-web-17")
        self.assertFalse(record["official"])
        self.assertEqual(record["status"], "RETRIEVED")
        code, out, _ = self.run_cli("list")
        self.assertIn("SUPPLEMENTARY_NON_OFFICIAL", out)

    def test_remove_and_show(self):
        self.assertEqual(self.add(self.git_spec()), EXIT_OK)
        self.assertEqual(self.run_cli("remove", "synth-community-17")[0], EXIT_OK)
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, EXIT_OK)
        self.assertIn("no sources", out)
        self.assertEqual(self.run_cli("show", "synth-community-17")[0], EXIT_VALIDATION)

    def test_add_refuses_remote_url_off_allowlist(self):
        self.assertEqual(self.add(_spec("bad-remote-17", "DOCS", "https://example.invalid/x", self.repo.to_sha)),
                         EXIT_VALIDATION)

    def test_official_identity_failure_reported_with_exact_code(self):
        # the synthetic clone has no origin remote, so an official claim cannot be verified: FAILED, exit non-zero
        spec = self.git_spec("odoo-community-17")
        spec["official"] = True
        spec["expected_origin"] = "https://github.com/odoo/odoo"
        self.assertEqual(self.add(spec), EXIT_OK)
        code, out, err = self.run_cli("acquire", "odoo-community-17")
        self.assertEqual(code, EXIT_SOURCE_UNAVAILABLE)
        self.assertIn("OFFICIAL_IDENTITY_UNVERIFIED", out)
        record = self.status_of("odoo-community-17")
        self.assertEqual(record["status"], "FAILED")
        self.assertTrue(record["failure_reason"].startswith("OFFICIAL_IDENTITY_UNVERIFIED: "), record)
        self.assertNotIn("origin_url", record)

    def test_verify_detects_tampered_blob_exit5(self):
        self.assertEqual(self.add(self.git_spec()), EXIT_OK)
        self.assertEqual(self.run_cli("acquire")[0], EXIT_OK)
        blobs = sorted(p for p in (self.home / "snapshots").rglob("*") if p.is_file() and "objects" in p.parts)
        self.assertTrue(blobs)
        blobs[0].write_bytes(b"tampered\n")
        code, _, _ = self.run_cli("verify")
        self.assertEqual(code, EXIT_INTEGRITY)
        self.assertEqual(self.status_of("synth-community-17")["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
