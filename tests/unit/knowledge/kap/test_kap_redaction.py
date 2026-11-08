"""TST-011-086 (REQ-KAP-046, REQ-KAP-028): canary secrets never reach KB logs, the kb-home audit log, release
manifests, provenance or exported packages.

Uses the planted-canary approach of `utils/redaction.py` (`scan_for_canaries`), the existing package builder
(`export_package`, P09 redaction scan) and the existing kb-home audit wrapper (`KbAudit`). Test file only.
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release.audit import AUDIT_NAME, KbAudit, verify_audit
from odooflux.knowledge.release.manifest import MANIFEST_NAME, write_release_manifest
from odooflux.knowledge.release.provenance import PROVENANCE_RELPATH
from odooflux.utils.redaction import MASK, scan_for_canaries, scan_for_shapes

CANARY = "CANARY-KAP-SECRET-7f3a9c2e1b"
META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
FILES = {
    "knowledge/evidence/EV-001.json": b'{"id": "EV-001", "status": "VERIFIED"}\n',
    "knowledge/compatibility/versions.json": b'{"versions": []}\n',
    "coverage/coverage-manifest.json": b'{"items": []}\n',
    "provenance/sources.json": b'{"sources": []}\n',
}


def _make_release(root: Path, files: dict = None, meta: dict = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in (FILES if files is None else files).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    write_release_manifest(root, META if meta is None else meta, secrets=[CANARY])  # the registered canary is masked
    return root


def _package_members(path: Path) -> list:
    """Decompressed bytes of every member: the canary check must see inside the zip, not the deflated bytes."""
    with zipfile.ZipFile(path) as zf:
        return [zf.read(name) for name in zf.namelist()]


class KapRedactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "kb-home"

    def tearDown(self):
        self._tmp.cleanup()

    def test_canary_not_in_logs(self):
        audit = KbAudit(self.home, "run-086", secrets=[CANARY])
        audit.record("package_rejected", f"pkg-{CANARY}.ofkp", "refused",
                     {"reason": f"token={CANARY}", "api_key": CANARY, "header": f"Authorization: Bearer {CANARY}"})
        audit.record("source_failed", "git-local", "failed", {"detail": f"clone of https://u:{CANARY}@host failed"})
        audit.record("ai_proposal", "rule-x", "ok", {"prompt_excerpt": f"secret {CANARY} inside"})
        self.assertEqual(scan_for_canaries([self.home], [CANARY]), [])
        text = (self.home / AUDIT_NAME).read_text(encoding="utf-8")
        self.assertIn(MASK, text)
        ok, reason = verify_audit(self.home)
        self.assertTrue(ok, reason)

    def test_canary_not_in_kb_home_tree_after_refused_export(self):
        release = _make_release(self.tmp / "kb" / "releases" / "work", files={
            **FILES, "knowledge/evidence/EV-002.json": f'{{"note": "{CANARY}"}}\n'.encode("utf-8")})
        out = self.tmp / "out" / "leak.ofkp"
        KbAudit(self.home, "run-086", secrets=[CANARY]).record("package_rejected", "leak.ofkp", "refused", {})
        with self.assertRaises(PackageError) as caught:
            export_package(release, out, canaries=[CANARY])
        self.assertNotIn(CANARY, str(caught.exception))
        self.assertFalse(out.exists())
        self.assertEqual(scan_for_canaries([self.home, self.tmp / "out"], [CANARY]), [])

    def test_canary_not_in_package(self):
        clean = _make_release(self.tmp / "kb" / "releases" / "clean")
        out = self.tmp / "clean.ofkp"
        info = export_package(clean, out, canaries=[CANARY])
        self.assertTrue(out.exists())
        self.assertEqual(scan_for_canaries([out], [CANARY]), [])
        for member in _package_members(out):
            self.assertNotIn(CANARY.encode("utf-8"), member)
        self.assertEqual(scan_for_shapes([out]), [])
        self.assertTrue(info.release_id.startswith("kr-"))

    def test_canary_in_package_source_refused(self):
        release = _make_release(self.tmp / "kb" / "releases" / "leaky", files={
            **FILES, "knowledge/evidence/EV-002.json": f'{{"note": "{CANARY}"}}\n'.encode("utf-8")})
        out = self.tmp / "leaky.ofkp"
        with self.assertRaises(PackageError):
            export_package(release, out, canaries=[CANARY])
        self.assertFalse(out.exists())
        self.assertEqual(list(self.tmp.glob(".leaky.ofkp*")), [])

    def test_canary_in_provenance_refused(self):
        files = {**FILES, PROVENANCE_RELPATH: f'{{"sources": [{{"url": "{CANARY}"}}]}}\n'.encode("utf-8")}
        release = _make_release(self.tmp / "kb" / "releases" / "prov", files=files)
        out = self.tmp / "prov.ofkp"
        with self.assertRaises(PackageError):
            export_package(release, out, canaries=[CANARY])
        self.assertFalse(out.exists())

    def test_canary_not_in_release_manifest(self):
        meta = {**META, "label": f"label-{CANARY}"}
        root = _make_release(self.tmp / "kb" / "releases" / "manifest", meta=meta)
        self.assertEqual(scan_for_canaries([root / MANIFEST_NAME], [CANARY]), [])
        self.assertEqual(json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))["label"].count(CANARY), 0)


if __name__ == "__main__":
    unittest.main()
