"""TST-011-086 boundaries (REQ-KAP-046, REQ-KAP-028): secrets are masked BEFORE integrity hashing and packaging, and
never weaken digest verification. One focused case per boundary: release manifest (order), provenance, kb-home audit,
package export and the kap release/package/source CLIs (failure paths). Offline; no network, git or Docker.

Planted values: a registered canary, a provider-style key and a URL with embedded credentials. Each boundary must
hold none of them in any file it writes, in any decompressed package member, or in any stdout/stderr text.
"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from odooflux.cli.knowledge import main as knowledge_main
from odooflux.cli.kap_common import EXIT_PACKAGE_REJECTED, EXIT_USAGE, EXIT_VALIDATION
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release.audit import AUDIT_NAME, RELEASE_ACTIONS, KbAudit, verify_audit
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.release.manifest import (META_FIELDS, MANIFEST_NAME, verify_release_tree,
                                                 write_release_manifest)
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.provenance import (PROVENANCE_RELPATH, SNAPSHOT_DIRNAME, sources_meta,
                                                   verify_provenance, write_provenance)
from odooflux.utils.redaction import scan_for_canaries, scan_for_shapes

CANARY = "CANARY-KAP-SECRET-7f3a9c2e1b"
SK = "sk-ant-api03-ABCDEFGHIJKLMNOP0123456789"
CRED_URL = "https://user:s3cretT0ken@github.com/odoo/odoo"
MARKERS = (CANARY, SK, "s3cretT0ken")
ORIGIN = "https://github.com/odoo/odoo"
REV = "a" * 40
DIR_REV = "sha256:" + "b" * 64
META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-08T10:00:00Z", "host_free": True},
}
FILES = {
    "knowledge/evidence/EV-001.json": b'{"id": "EV-001", "status": "VERIFIED"}\n',
    "knowledge/compatibility/versions.json": b'{"versions": []}\n',
    "coverage/coverage-manifest.json": b'{"items": []}\n',
    "provenance/sources.json": b'{"sources": []}\n',
}


def _leaks(blob) -> list:
    """Planted markers found in `blob` (bytes or text), by their UTF-8 form."""
    data = blob.encode("utf-8") if isinstance(blob, str) else blob
    return [marker for marker in MARKERS if marker.encode("utf-8") in data]


def _make_release(root: Path, files: dict = None, meta: dict = None, secrets=(CANARY,)) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in (FILES if files is None else files).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    write_release_manifest(root, META if meta is None else meta, secrets=list(secrets))
    return root


def _members(path: Path) -> list:
    """Decompressed bytes of every zip member (the scan must see inside the deflate stream)."""
    with zipfile.ZipFile(path) as zf:
        return [zf.read(name) for name in zf.namelist()]


def _run(argv: list, home: Path):
    """(exit code, stdout + stderr text) of one knowledge CLI invocation."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = knowledge_main([*argv, "--kb-home", str(home)])
    return code, out.getvalue() + err.getvalue()


class ManifestOrderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_release_json_holds_no_secret_and_digest_binds_scrubbed_body(self):
        meta = {**META, "label": f"label {CANARY} {SK}",
                "sources": [{"source_id": "odoo-community-17.0", "origin_url": CRED_URL}]}
        root = _make_release(self.tmp / "rel", meta=meta)
        raw = (root / MANIFEST_NAME).read_bytes()
        self.assertEqual(_leaks(raw), [])
        manifest = json.loads(raw)
        body = {k: v for k, v in manifest.items() if k not in ("release_id", "release_digest")}
        self.assertEqual(digest_obj(body), manifest["release_digest"])
        raw_body = {"format": manifest["format"], "files": manifest["files"],
                    **{k: meta[k] for k in META_FIELDS}}
        self.assertNotEqual(digest_obj(raw_body), manifest["release_digest"],
                            "the digest must cover the scrubbed metadata, not the raw one")
        self.assertEqual(verify_release_tree(root), [])

    def test_secret_injected_after_hashing_is_detected(self):
        root = _make_release(self.tmp / "rel")
        target = root / "knowledge/evidence/EV-001.json"
        target.write_bytes(f'{{"id": "EV-001", "key": "{SK}"}}\n'.encode("utf-8"))
        problems = verify_release_tree(root)
        self.assertTrue(any(p.startswith("changed file") and "EV-001.json" in p for p in problems), problems)

    def test_manifest_edited_to_restore_a_secret_breaks_the_digest(self):
        root = _make_release(self.tmp / "rel")
        path = root / MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["label"] = f"label {CANARY}"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        problems = verify_release_tree(root)
        self.assertIn("release_digest does not match the manifest contents", problems)


class ProvenanceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "store")
        tree = self.base / "odoo"
        (tree / "addons" / "demo").mkdir(parents=True)
        (tree / "addons" / "demo" / "models.py").write_text("x = 1\n", encoding="utf-8")
        self.snap = build_snapshot(tree, "odoo-community-17.0", REV, self.store, created_at="2026-11-08T10:00:00Z")
        self.snap["origin_url"] = ORIGIN
        self.rec = {"source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "official": True,
                    "url": "local:" + str(self.base / "clone-17"), "expected_origin": ORIGIN, "revision": REV,
                    "status": "VERIFIED", "checksum": self.snap["snapshot_digest"]}

    def _release(self) -> Path:
        tree = self.base / "release"
        (tree / "coverage").mkdir(parents=True)
        (tree / "coverage" / "coverage-manifest.json").write_text('{"items": []}\n', encoding="utf-8")
        return tree

    def _refused(self, snap, rec, needle: str):
        tree = self._release()
        with self.assertRaises(KnowledgeReleaseError) as caught:
            write_provenance(tree, [snap], [rec])
        message = str(caught.exception)
        self.assertIn(needle, message)
        self.assertEqual(_leaks(message), [], message)
        self.assertFalse((tree / PROVENANCE_RELPATH).exists())
        self.assertFalse((tree / SNAPSHOT_DIRNAME).exists())

    def test_non_official_url_with_credentials_is_refused_with_code(self):
        tree = self.base / "pack"
        (tree / "x").mkdir(parents=True)
        (tree / "x" / "f.py").write_text("y = 2\n", encoding="utf-8")
        snap = build_snapshot(tree, "dir-pack-01", DIR_REV, self.store, created_at="2026-11-08T10:00:00Z")
        rec = {"source_id": "dir-pack-01", "kind": "DIRECTORY", "official": False, "url": CRED_URL,
               "revision": DIR_REV, "status": "VERIFIED", "checksum": snap["snapshot_digest"]}
        self._refused(snap, rec, "URL_CREDENTIALS")

    def test_expected_origin_with_credentials_is_refused_with_code(self):
        self._refused(self.snap, {**self.rec, "expected_origin": CRED_URL}, "URL_CREDENTIALS")

    def test_snapshot_origin_with_credentials_is_refused_with_code(self):
        self._refused({**self.snap, "origin_url": CRED_URL}, self.rec, "URL_CREDENTIALS")

    def test_credential_shape_inside_snapshot_is_refused_without_echo(self):
        snap = json.loads(json.dumps(self.snap))
        snap["limits"]["excluded"] = [{"path": "x.py", "reason": f"fetched with {SK}"}]
        self._refused(snap, self.rec, "credential-shaped")

    def test_shipped_snapshots_and_sources_hold_no_credentials(self):
        tree = self._release()
        entries = write_provenance(tree, [self.snap], [self.rec])
        write_release_manifest(tree, {**META, "sources": sources_meta(entries)})
        verify_provenance(tree)
        for path in tree.rglob("*"):
            if path.is_file():
                self.assertEqual(_leaks(path.read_bytes()), [], path)
        self.assertEqual(scan_for_shapes([tree]), [])
        self.assertEqual(scan_for_canaries([tree], [CANARY]), [])


class AuditBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "kb-home"

    def test_every_release_action_masks_secrets_in_target_and_details(self):
        audit = KbAudit(self.home, "run-086", secrets=[CANARY])
        details = {"url": CRED_URL, "api_key": SK, "note": f"{CANARY} {SK} {CRED_URL}",
                   "nested": [{"reason": f"clone of {CRED_URL} failed"}]}
        for action in RELEASE_ACTIONS:
            audit.record(action, target=f"target-{CANARY}", outcome="ok", details=details)
        text = (self.home / AUDIT_NAME).read_text(encoding="utf-8")
        self.assertEqual(_leaks(text), [])
        self.assertEqual(len(text.splitlines()), len(RELEASE_ACTIONS))
        ok, reason = verify_audit(self.home)
        self.assertTrue(ok, reason)


class PackageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _tree_with(self, name: str, rel: str, text: str) -> Path:
        return _make_release(self.tmp / name, files={**FILES, rel: text.encode("utf-8")}, secrets=())

    def _assert_refused(self, release: Path, out: Path, **kwargs):
        with self.assertRaises(PackageError) as caught:
            export_package(release, out, **kwargs)
        self.assertEqual(caught.exception.code, "P09")
        self.assertEqual(_leaks(str(caught.exception)), [], str(caught.exception))
        self.assertEqual(_leaks(caught.exception.detail), [])
        self.assertFalse(out.exists())
        self.assertEqual(list(self.tmp.glob(".*.tmp")), [])

    def test_canary_inside_shipped_snapshot_manifest_refused(self):
        rel = f"{SNAPSHOT_DIRNAME}/ss-0123456789ab.json"
        release = self._tree_with("snap-canary", rel, f'{{"note": "{CANARY}"}}\n')
        self._assert_refused(release, self.tmp / "a.ofkp", canaries=[CANARY])

    def test_credential_shape_inside_shipped_snapshot_manifest_refused(self):
        rel = f"{SNAPSHOT_DIRNAME}/ss-0123456789ab.json"
        release = self._tree_with("snap-shape", rel, f'{{"note": "{SK}"}}\n')
        self._assert_refused(release, self.tmp / "b.ofkp")

    def test_canary_inside_provenance_sources_refused(self):
        release = self._tree_with("prov-canary", PROVENANCE_RELPATH, f'{{"sources": [{{"url": "{CANARY}"}}]}}\n')
        self._assert_refused(release, self.tmp / "c.ofkp", canaries=[CANARY])

    def test_credential_url_inside_provenance_sources_refused(self):
        release = self._tree_with("prov-url", PROVENANCE_RELPATH, f'{{"sources": [{{"url": "{CRED_URL}"}}]}}\n')
        self._assert_refused(release, self.tmp / "d.ofkp")

    def test_clean_release_exports_with_no_secret_in_any_member(self):
        release = _make_release(self.tmp / "clean")
        out = self.tmp / "clean.ofkp"
        export_package(release, out, canaries=[CANARY])
        for member in _members(out):
            self.assertEqual(_leaks(member), [])
        self.assertEqual(scan_for_shapes([out]), [])
        self.assertEqual(scan_for_canaries([out], [CANARY]), [])


class CliFailureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "kb-home"
        self.registry = self.tmp / "sources.json"

    def _install(self, files: dict) -> str:
        """Install a release tree under kb-home/releases/<release_id> and return its id."""
        release = _make_release(self.tmp / "scratch", files=files, secrets=())
        release_id = json.loads((release / MANIFEST_NAME).read_text(encoding="utf-8"))["release_id"]
        target = self.home / "releases" / release_id
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(release), str(target))
        return release_id

    def _assert_clean(self, code: int, text: str, expected_code: int):
        self.assertEqual(code, expected_code, text)
        self.assertEqual(_leaks(text), [], text)

    def test_release_commands_do_not_echo_secret_release_ids(self):
        for argv in (["release", "show", CANARY], ["release", "activate", SK], ["release", "remove", CANARY],
                     ["release", "diff", CANARY, CRED_URL]):
            code, text = _run(argv, self.home)
            self._assert_clean(code, text, EXIT_VALIDATION)

    def test_export_refused_for_credential_shape_and_message_is_clean(self):
        release_id = self._install({**FILES, "knowledge/evidence/EV-002.json": f'{{"n": "{SK}"}}\n'.encode("utf-8")})
        out = self.tmp / "out.ofkp"
        code, text = _run(["package", "export", release_id, "-o", str(out)], self.home)
        self._assert_clean(code, text, EXIT_PACKAGE_REJECTED)
        self.assertFalse(out.exists())

    def test_package_expect_digest_secret_is_not_echoed(self):
        release = _make_release(self.tmp / "pkg-src")
        pkg = self.tmp / "pkg.ofkp"
        export_package(release, pkg)
        for argv in (["package", "validate", str(pkg), "--expect-digest", SK],
                     ["package", "import", str(pkg), "--expect-digest", CANARY]):
            code, text = _run(argv, self.home)
            self._assert_clean(code, text, EXIT_PACKAGE_REJECTED)

    def test_source_spec_with_credentials_refused_without_echo(self):
        spec = self.tmp / "spec.json"
        base = {"source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "official": True, "url": CRED_URL,
                "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": "17.0", "revision": REV,
                "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
                "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None,
                "required": True}
        for variant in (base, {**base, "url": ORIGIN, "expected_origin": CRED_URL}):
            spec.write_text(json.dumps(variant), encoding="utf-8")
            code, text = _run(["source", "add", "--file", str(spec), "--registry", str(self.registry)], self.home)
            self._assert_clean(code, text, EXIT_VALIDATION)
            self.assertIn("URL_CREDENTIALS", text)
        self.assertFalse(self.registry.exists())

    def test_source_commands_do_not_echo_secret_ids_or_hashes(self):
        reg = ["--registry", str(self.registry)]
        for argv in (["source", "show", CANARY], ["source", "remove", SK], ["source", "acquire", CANARY],
                     ["source", "fetch", SK, "--allow-network", "--sha256", CANARY]):
            code, text = _run([*argv, *reg], self.home)
            self.assertIn(code, (EXIT_VALIDATION, EXIT_USAGE), text)
            self.assertEqual(_leaks(text), [], text)


if __name__ == "__main__":
    unittest.main()
