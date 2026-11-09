"""Feature 012 / T04: `odooflux knowledge check` (cli/kap_update.py) through the real parser path.

Exit codes: 0 completed, 1 local state invalid, 2 usage, 4 CHECK_UNAVAILABLE. The kb-home is hashed before and after every
run: `check` never writes. Remotes are a fake `ls_remote` injected through `remote_git.ls_remote_heads`; subprocess and
sockets are patched to fail. Tokens are dummy values and must never appear in any output.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_check_cli.py' -t .
"""

import hashlib
import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.resolver import clear_cache
from odooflux.knowledge.release.store import set_release_state
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update.catalog import load_catalog
from odooflux.cli import kap_release

CATALOG = load_catalog()
COMMUNITY_REPO = "https://github.com/odoo/odoo.git"
ENTERPRISE_REPO = "https://github.com/odoo/enterprise.git"
TOKEN = "tok-TEST-1234567890"  # dummy
ENV_KEYS = ("ODOOFLUX_OFFLINE", "ODOOFLUX_KB_HOME", "ODOOFLUX_ENTERPRISE_TOKEN", "ODOOFLUX_ENTERPRISE_TOKEN_FILE",
            "ODOOFLUX_GIT_SECRET", "XDG_DATA_HOME")
META = {
    "label": "community-check-fixture",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
REPORT_KEYS = {"schema", "statuses", "sources", "new_versions", "affected_transitions", "enterprise_freshness",
               "catalog_digest", "offline", "installed_release"}


def sha(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def heads_for(edition: str, changed=()) -> dict:
    return {e.branch: sha(f"{edition}-{e.branch}" + ("-moved" if e.branch in changed else ""))
            for e in CATALOG.entries if e.edition == edition}


def default_remote() -> dict:
    return {COMMUNITY_REPO: heads_for("community"), ENTERPRISE_REPO: heads_for("enterprise")}


class FakeRemote:
    def __init__(self, responses=None):
        self.responses = responses if responses is not None else default_remote()
        self.calls = []

    def __call__(self, repository, *, offline=False, transport_url=None, timeout=None, runner=None, credentials=None):
        self.calls.append((repository, credentials))
        outcome = self.responses[repository]
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)


def tree_snapshot(root: Path) -> dict:
    """Every path under `root` with its bytes (None for directories). Used to prove `check` writes nothing."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


class CheckCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "kb"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        net = mock.patch.object(socket, "socket", side_effect=AssertionError("no socket in check tests"))
        net.start()
        self.addCleanup(net.stop)
        clear_cache()
        self.addCleanup(clear_cache)

    def run_cli(self, argv, *, remote=None, extra_patches=()):
        """Run through `cli/knowledge.main` (the real parser). Returns (exit code, stdout, stderr, fake remote)."""
        fake = FakeRemote(remote)
        out, err = io.StringIO(), io.StringIO()
        patches = [mock.patch.object(rg, "ls_remote_heads", fake), *extra_patches]
        for patcher in patches:
            patcher.start()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = knowledge_main(argv)
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return code, out.getvalue(), err.getvalue(), fake

    def install_release(self, revisions: dict) -> str:
        """A real INSTALLED and ACTIVE release whose `release.json` pins `revisions` (source_id -> sha)."""
        tree = self.root / "tree"
        tree.mkdir(exist_ok=True)
        (tree / "payload.txt").write_text("knowledge payload\n", encoding="utf-8")
        sources = [{"source_id": sid, "revision": rev, "snapshot_digest": "ab" * 32, "official": True,
                    "status": "VERIFIED", "origin_url": "https://github.com/odoo/odoo", "snapshot_id": f"snap-{i}"}
                   for i, (sid, rev) in enumerate(sorted(revisions.items()))]
        manifest = write_release_manifest(tree, dict(META, sources=sources))
        release_id = manifest["release_id"]
        self.home.mkdir(exist_ok=True)
        shutil.copytree(tree, self.home / "releases" / release_id)
        set_release_state(self.home, release_id, ReleaseState.INSTALLED)
        kap_release.activate(self.home, release_id)
        shutil.rmtree(tree)
        return release_id

    def community_revisions(self) -> dict:
        return {CATALOG.source_id(e): heads_for("community")[e.branch] for e in CATALOG.entries
                if e.edition == "community"}

    def enterprise_revisions(self) -> dict:
        return {CATALOG.source_id(e): heads_for("enterprise")[e.branch] for e in CATALOG.entries
                if e.edition == "enterprise"}

    # --- wiring and usage ---------------------------------------------------------------------------------------

    def test_help_for_check_through_main(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = knowledge_main(["check", "--help"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        for flag in ("--json", "--offline", "--kb-home"):
            self.assertIn(flag, text)

    def test_unknown_flag_is_usage_error(self):
        code, _, _, fake = self.run_cli(["check", "--no-such-flag"])
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])

    # --- human and JSON output ----------------------------------------------------------------------------------

    def test_human_fresh_install_reports_fresh_install_and_exit_zero(self):
        code, out, _, fake = self.run_cli(["check", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertIn("installed release: none", out)
        self.assertIn("KNOWLEDGE_UPDATE_AVAILABLE", out)
        self.assertIn("fresh install", out)
        self.assertIn("enterprise freshness: NOT_INSTALLED", out)
        self.assertIn("SKIPPED_NO_CREDENTIALS", out)
        self.assertNotIn("Migration support", out)
        self.assertEqual(fake.calls, [(COMMUNITY_REPO, None)])

    def test_human_new_version_says_migration_support_not_established(self):
        remote = default_remote()
        remote[COMMUNITY_REPO] = dict(heads_for("community"), **{"20.0": sha("new")})
        code, out, _, _ = self.run_cli(["check", "--kb-home", str(self.home)], remote=remote)
        self.assertEqual(code, 0)
        self.assertIn("new upstream version: community 20.0", out)
        self.assertIn("Migration support: not established", out)
        self.assertIn("NEW_VERSION_DISCOVERED", out)
        self.assertIn("TRANSITION_NOT_YET_SUPPORTED", out)

    def test_json_run_has_exactly_the_report_fields(self):
        code, out, _, _ = self.run_cli(["check", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(set(payload), REPORT_KEYS)
        self.assertEqual(payload["schema"], "odooflux.knowledge-check/1")
        self.assertIsNone(payload["installed_release"])
        self.assertFalse(payload["offline"])
        self.assertEqual(payload["catalog_digest"], CATALOG.digest)

    def test_json_no_update_against_real_installed_release(self):
        release_id = self.install_release({**self.community_revisions()})
        code, out, _, fake = self.run_cli(["check", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["installed_release"], release_id)
        self.assertEqual(payload["statuses"], ["NO_UPDATE"])
        self.assertEqual(len(fake.calls), 1)

    def test_human_with_token_outdated_enterprise(self):
        self.install_release({**self.community_revisions(), **self.enterprise_revisions()})
        remote = default_remote()
        remote[ENTERPRISE_REPO] = heads_for("enterprise", changed=("17.0",))
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        code, out, _, fake = self.run_cli(["check", "--kb-home", str(self.home)], remote=remote)
        self.assertEqual(code, 0)
        self.assertIn("enterprise freshness: OUTDATED", out)
        self.assertIn("changed: 17.0", out)
        self.assertEqual([c[0] for c in fake.calls], [COMMUNITY_REPO, ENTERPRISE_REPO])
        self.assertNotIn(TOKEN, out)

    # --- exit codes -----------------------------------------------------------------------------------------------

    def test_offline_flag_exit_4_and_zero_calls(self):
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
            code, out, _, fake = self.run_cli(["check", "--kb-home", str(self.home), "--offline"])
        self.assertEqual(code, 4)
        self.assertEqual(fake.calls, [])
        self.assertIn("offline", out)
        self.assertIn("CHECK_UNAVAILABLE", out)

    def test_offline_environment_exit_4_and_zero_calls(self):
        os.environ["ODOOFLUX_OFFLINE"] = "yes"
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
            code, _, _, fake = self.run_cli(["check", "--kb-home", str(self.home)])
        self.assertEqual(code, 4)
        self.assertEqual(fake.calls, [])

    def test_invalid_local_state_exit_1_and_no_network(self):
        self.home.mkdir()
        (self.home / "active.json").write_text("{corrupt", encoding="utf-8")
        code, out, _, fake = self.run_cli(["check", "--kb-home", str(self.home)])
        self.assertEqual(code, 1)
        self.assertEqual(fake.calls, [])
        self.assertIn("LOCAL_STATE_INVALID", out)
        self.assertIn("installed release state is invalid", out)

    def test_invalid_local_state_json_reports_status(self):
        self.home.mkdir()
        (self.home / "active.json").write_text("{corrupt", encoding="utf-8")
        code, out, _, _ = self.run_cli(["check", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["statuses"], ["LOCAL_STATE_INVALID"])
        self.assertEqual(payload["sources"], [])

    def test_community_unavailable_exit_4(self):
        remote = default_remote()
        remote[COMMUNITY_REPO] = rg.RemoteGitError("UNAVAILABLE", None, "could not resolve host")
        code, out, _, _ = self.run_cli(["check", "--kb-home", str(self.home)], remote=remote)
        self.assertEqual(code, 4)
        self.assertIn("nothing could be read", out)

    def test_enterprise_failure_alone_exit_0(self):
        remote = default_remote()
        remote[ENTERPRISE_REPO] = rg.RemoteGitError("AUTH_FAILED", None, "rejected")
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        code, out, _, _ = self.run_cli(["check", "--kb-home", str(self.home), "--json"], remote=remote)
        self.assertEqual(code, 0)
        enterprise = {row["status"] for row in json.loads(out)["sources"] if row["edition"] == "enterprise"}
        self.assertEqual(enterprise, {"AUTH_FAILED"})

    def test_bad_credential_configuration_is_reported_without_echo(self):
        secret_path = self.root / "secret-token-location-XYZ"
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN_FILE"] = str(secret_path)  # missing file: config problem
        code, out, err, fake = self.run_cli(["check", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([c[0] for c in fake.calls], [COMMUNITY_REPO])
        self.assertIn("TOKEN_FILE_MISSING", out)
        self.assertNotIn("secret-token-location-XYZ", out + err)

    # --- secrecy and read-only guarantees -------------------------------------------------------------------------

    def test_token_never_appears_in_output(self):
        self.install_release({**self.community_revisions(), **self.enterprise_revisions()})
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        remote = default_remote()
        remote[ENTERPRISE_REPO] = rg.RemoteGitError("UNAVAILABLE", None, f"fatal: could not read {TOKEN} from host")
        for extra in ([], ["--json"]):
            with self.subTest(extra=extra):
                code, out, err, _ = self.run_cli(["check", "--kb-home", str(self.home), *extra], remote=remote)
                self.assertEqual(code, 0)
                self.assertNotIn(TOKEN, out)
                self.assertNotIn(TOKEN, err)
                self.assertIn("UNAVAILABLE", out)

    def test_auth_failure_message_with_token_is_masked(self):
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        remote = default_remote()
        remote[ENTERPRISE_REPO] = rg.RemoteGitError("AUTH_FAILED", None, f"bad credential {TOKEN}")
        code, out, err, _ = self.run_cli(["check", "--kb-home", str(self.home)], remote=remote)
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)

    def test_check_never_writes_to_kb_home(self):
        self.install_release({**self.community_revisions(), **self.enterprise_revisions()})
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        remote = default_remote()
        remote[COMMUNITY_REPO] = heads_for("community", changed=("18.0",))
        remote[ENTERPRISE_REPO] = heads_for("enterprise", changed=("17.0",))
        before = tree_snapshot(self.home)
        for extra in ([], ["--json"], ["--offline"]):
            with self.subTest(extra=extra):
                self.run_cli(["check", "--kb-home", str(self.home), *extra], remote=remote)
                self.assertEqual(tree_snapshot(self.home), before)

    def test_check_with_default_kb_home_from_environment_is_read_only(self):
        self.install_release(self.community_revisions())
        os.environ["ODOOFLUX_KB_HOME"] = str(self.home)
        before = tree_snapshot(self.home)
        code, _, _, _ = self.run_cli(["check", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(tree_snapshot(self.home), before)


if __name__ == "__main__":
    unittest.main()
