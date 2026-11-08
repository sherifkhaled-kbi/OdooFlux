"""TST-011-012 (REQ-KAP-047, REQ-KAP-022): package compatibility and validation, P04 P06 P07 P09 P11 orchestration.

Contract: knowledge-package-format "Reader rules" and "Reader algorithm" step 3. Packages are built with the T011
builder and tampered with by rewriting the ZIP, so every rejection is produced by the real reader path.
"""

import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.validate import validate_package
from odooflux.knowledge.release.manifest import write_release_manifest

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
FILE_ATTR = (stat.S_IFREG | 0o644) << 16
VERSIONS = b'{"versions": [], "transitions": []}\n'


def _release(root: Path, extra: dict = None) -> Path:
    files = {"knowledge/compatibility/versions.json": VERSIONS,
             "coverage/coverage-manifest.json": b'{"items": []}\n',
             "provenance/sources.json": b'{"sources": []}\n', **(extra or {})}
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    write_release_manifest(root, META)
    return root


def _rewrite(src: Path, dst: Path, *, replace: dict = None, package: dict = None) -> Path:
    """Copy every member of `src` to `dst`; `replace` maps names to bytes-transformers, `package` maps package.json
    edits (dict updates applied to the parsed JSON)."""
    with zipfile.ZipFile(src) as zin:
        members = [(info.filename, zin.read(info.filename)) for info in zin.infolist()]
    out = []
    for name, data in members:
        if replace and name in replace:
            data = replace[name](data)
        if name == "package.json" and package is not None:
            data = json.dumps({**json.loads(data), **package}, sort_keys=True).encode("utf-8")
        out.append((name, data))
    with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in out:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FILE_ATTR
            zf.writestr(info, data)
    return dst


class TestPackageValidate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.staging = self.tmp / "kb" / "staging"
        self.pkg = export_package(_release(self.tmp / "release"), self.tmp / "good.ofkp").path

    def tearDown(self):
        self._tmp.cleanup()

    def _expect(self, archive, code, **kwargs):
        with self.assertRaises(PackageError) as ctx:
            validate_package(archive, self.staging, **kwargs)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        self.assertEqual(list(self.staging.glob("*")) if self.staging.exists() else [], [])

    def test_valid_package_validates(self):
        result = validate_package(self.pkg, self.staging)
        self.assertEqual(result.release_id[:3], "kr-")
        self.assertTrue((result.staging_dir / "knowledge" / "compatibility" / "versions.json").is_file())
        self.assertEqual(result.knowledge_root, result.staging_dir / "knowledge")
        import shutil
        shutil.rmtree(result.staging_dir)

    def test_reject_bad_sha(self):
        bad = _rewrite(self.pkg, self.tmp / "bad-sha.ofkp", replace={
            "coverage/coverage-manifest.json": lambda data: data[:-1] + b" "})  # same size, different bytes
        self._expect(bad, "P06")

    def test_reject_incompatible_framework(self):
        bad = _rewrite(self.pkg, self.tmp / "framework.ofkp",
                       package={"compat": {"min_framework": "99.0.0", "max_framework": None, "schemas": {}}})
        self._expect(bad, "P07")
        too_old = _rewrite(self.pkg, self.tmp / "old.ofkp",
                           package={"compat": {"min_framework": "0.0.1", "max_framework": "0.0.2", "schemas": {}}})
        self._expect(too_old, "P07")

    def test_reject_unknown_schema(self):
        bad = _rewrite(self.pkg, self.tmp / "schema.ofkp",
                       package={"compat": {"min_framework": "0.2.0", "max_framework": None,
                                           "schemas": {"not_a_family": "1"}}})
        self._expect(bad, "P07")
        newer = _rewrite(self.pkg, self.tmp / "schema2.ofkp",
                         package={"compat": {"min_framework": "0.2.0", "max_framework": None,
                                             "schemas": {"evidence": "9"}}})
        self._expect(newer, "P07")

    def test_reject_newer_format(self):
        bad = _rewrite(self.pkg, self.tmp / "format.ofkp", package={"format": "odooflux.package/2"})
        self._expect(bad, "P07")

    def test_expect_digest_mismatch(self):
        self._expect(self.pkg, "P06", expect_digest="0" * 64)
        result = validate_package(self.pkg, self.staging, expect_digest=json.loads(
            zipfile.ZipFile(self.pkg).read("package.json"))["release_digest"])
        import shutil
        shutil.rmtree(result.staging_dir)

    def test_manifest_schema_enforced(self):
        extra = _rewrite(self.pkg, self.tmp / "extra-field.ofkp", package={"unexpected": True})
        self._expect(extra, "P07")

    def test_entry_set_must_match_release_files(self):
        bad = _rewrite(self.pkg, self.tmp / "extra.ofkp")
        with zipfile.ZipFile(bad, "a") as zf:
            info = zipfile.ZipInfo("provenance/extra.json", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = FILE_ATTR
            zf.writestr(info, b"{}\n")
        self._expect(bad, "P04")

    def test_knowledge_errors_reject_p11(self):
        broken = export_package(_release(self.tmp / "broken", {
            "knowledge/evidence/EV-9.json": b'{"id": "EV-9"'}), self.tmp / "broken.ofkp").path
        self._expect(broken, "P11")


if __name__ == "__main__":
    unittest.main()
