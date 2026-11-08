"""TST-011-011 (REQ-KAP-024, REQ-KAP-022, REQ-KAP-028): deterministic package builder and redaction scan hook.

Contract: knowledge-package-format "Writer (export)". Exports are compared by sha256 of the `.ofkp` bytes.
"""

import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from odooflux.knowledge.package.archive import PackageError, read_package_archive
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.utils.redaction import MASK

CANARY = "CANARY-7f3a9c2e1b-do-not-export"
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
    write_release_manifest(root, META if meta is None else meta)
    return root


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPackageBuilder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.release = _make_release(self.tmp / "kb" / "releases" / "work")

    def tearDown(self):
        self._tmp.cleanup()

    def test_export_deterministic(self):
        first = export_package(self.release, self.tmp / "a.ofkp")
        second = export_package(self.release, self.tmp / "b.ofkp")
        self.assertEqual(_sha(self.tmp / "a.ofkp"), _sha(self.tmp / "b.ofkp"))
        self.assertEqual(first.release_digest, second.release_digest)
        # Touching mtimes must not change the bytes.
        for path in self.release.rglob("*"):
            if path.is_file():
                os.utime(path, (1_000_000_000, 1_000_000_000))
        third = export_package(self.release, self.tmp / "c.ofkp")
        self.assertEqual(_sha(self.tmp / "a.ofkp"), _sha(self.tmp / "c.ofkp"))
        self.assertEqual(third.sha256, first.sha256)

    def test_export_independent_of_umask_and_dir(self):
        export_package(self.release, self.tmp / "ref.ofkp")
        copy = self.tmp / "elsewhere" / "copy-of-release"
        shutil.copytree(self.release, copy)
        old = os.umask(0o077)
        try:
            export_package(copy, self.tmp / "umask077.ofkp")
        finally:
            os.umask(old)
        old = os.umask(0o002)
        try:
            export_package(self.release, self.tmp / "umask002.ofkp")
        finally:
            os.umask(old)
        ref = _sha(self.tmp / "ref.ofkp")
        self.assertEqual(ref, _sha(self.tmp / "umask077.ofkp"))
        self.assertEqual(ref, _sha(self.tmp / "umask002.ofkp"))

    def test_no_absolute_paths(self):
        out = export_package(self.release, self.tmp / "p.ofkp").path
        with zipfile.ZipFile(out) as zf:
            for name in zf.namelist():
                self.assertFalse(name.startswith("/"), name)
                self.assertNotIn("\\", name)
                self.assertFalse(len(name) > 1 and name[1] == ":", name)
            blob = b"".join(zf.read(name) for name in zf.namelist())
        self.assertNotIn(str(self.release.resolve()).encode("utf-8"), blob)
        # A release that embeds its own absolute directory is refused rather than exported.
        leaky_dir = (self.tmp / "leaky").resolve()
        leaky = _make_release(self.tmp / "leaky", files={
            **FILES, "provenance/where.json": f'{{"at": "{leaky_dir}"}}\n'.encode("utf-8")})
        with self.assertRaises(PackageError) as ctx:
            export_package(leaky, self.tmp / "leaky.ofkp")
        self.assertEqual(ctx.exception.code, "P09")
        self.assertFalse((self.tmp / "leaky.ofkp").exists())

    def test_secret_canary_fails_build(self):
        leaky = _make_release(self.tmp / "canary", files={
            **FILES, "knowledge/evidence/EV-002.json": f'{{"note": "{CANARY}"}}\n'.encode("utf-8")})
        with self.assertRaises(PackageError) as ctx:
            export_package(leaky, self.tmp / "canary.ofkp", canaries=[CANARY])
        self.assertEqual(ctx.exception.code, "P09")
        self.assertFalse((self.tmp / "canary.ofkp").exists())
        self.assertEqual(list(self.tmp.glob(".canary.ofkp*")), [])
        # Credential-shaped strings are refused even without a planted canary.
        shaped = _make_release(self.tmp / "shaped", files={
            **FILES, "knowledge/evidence/EV-003.json": b'{"note": "sk-ant-api03-abcdefghijklmnopqrstuv"}\n'})
        with self.assertRaises(PackageError):
            export_package(shaped, self.tmp / "shaped.ofkp")
        self.assertNotIn(MASK, CANARY)

    def test_snapshots_not_exported(self):
        home = self.tmp / "kb"
        (home / "snapshots").mkdir(exist_ok=True)
        (home / "snapshots" / "blob.bin").write_bytes(b"raw source text")
        out = export_package(self.release, self.tmp / "s.ofkp").path
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            blob = b"".join(zf.read(name) for name in names)
        self.assertFalse(any(n.startswith(("snapshots/", "staging/")) for n in names), names)
        self.assertNotIn(b"raw source text", blob)
        # A release tree that carries a snapshots/ directory is refused.
        bad = _make_release(self.tmp / "bad", files={**FILES, "snapshots/x.bin": b"raw"})
        with self.assertRaises(PackageError):
            export_package(bad, self.tmp / "bad.ofkp")

    def test_enterprise_derived_refused_by_default(self):
        meta = {**META, "sources": [{"source_id": "enterprise-local", "revision": "17.0", "snapshot_digest": "ab" * 32,
                                     "official": True, "status": "VERIFIED", "enterprise_derived": True}]}
        release = _make_release(self.tmp / "ent", meta=meta)
        with self.assertRaises(PackageError):
            export_package(release, self.tmp / "ent.ofkp")
        info = export_package(release, self.tmp / "ent2.ofkp", include_enterprise_derived=True)
        self.assertTrue(info.contains_enterprise_derived)

    def test_export_self_check_reads_back(self):
        info = export_package(self.release, self.tmp / "ok.ofkp")
        staged = read_package_archive(self.tmp / "ok.ofkp", self.tmp / "check")
        self.assertEqual(staged.manifest["release_digest"], info.release_digest)
        staged.discard()


if __name__ == "__main__":
    unittest.main()
