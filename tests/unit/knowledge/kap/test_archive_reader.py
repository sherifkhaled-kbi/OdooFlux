"""TST-011-010 (REQ-KAP-023): safe archive reader rejects malicious packages table-driven and cleans staging.

Archives come from `_archives.py`. Every rejection must raise PackageError with the contract code and leave the
staging root empty (contract knowledge-package-format, reader algorithm steps 1 to 3).
"""

import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from odooflux.knowledge.package.archive import PackageError, read_package_archive
from odooflux.knowledge.package.limits import MAX_ENTRY_BYTES

from . import _archives as arc


class _ArchiveCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.staging_root = self.root / "staging"
        self._n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _archive(self, entries) -> Path:
        self._n += 1
        return arc.write_zip(self.root / f"case{self._n}.ofkp", entries)

    def assertRejected(self, archive, code):
        with self.assertRaises(PackageError) as ctx:
            read_package_archive(archive, self.staging_root)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        leftovers = list(self.staging_root.iterdir()) if self.staging_root.exists() else []
        self.assertEqual(leftovers, [], "failed read must remove its staging directory")


class ArchiveReaderTests(_ArchiveCase):
    def test_valid_package_accepted(self):
        archive = self._archive(arc.valid_entries())
        staged = read_package_archive(archive, self.staging_root)
        try:
            self.assertEqual(
                sorted(e.path for e in staged.entries),
                sorted(name for name, _ in arc.valid_entries()),
            )
            for entry in staged.entries:
                data = (staged.staging_dir / entry.path).read_bytes()
                self.assertEqual(len(data), entry.size)
                self.assertEqual(arc.sha256_hex(data), entry.sha256)
            self.assertTrue((staged.staging_dir / "package.json").is_file())
            self.assertEqual(stat.S_IMODE(staged.staging_dir.stat().st_mode), 0o700)
        finally:
            staged.discard()
        self.assertFalse(staged.staging_dir.exists())

    def test_reject_traversal(self):
        base = arc.valid_entries()
        for name in ("knowledge/../../escape.json", "../escape.json"):
            with self.subTest(name=name):
                self.assertRejected(self._archive(base + [(name, b"x")]), "P01")

    def test_reject_absolute(self):
        base = arc.valid_entries()
        for name in ("/knowledge/evidence/evil.json", "/etc/passwd"):
            with self.subTest(name=name):
                self.assertRejected(self._archive(base + [(name, b"x")]), "P01")

    def test_reject_backslash(self):
        base = arc.valid_entries()
        for name in ("knowledge\\evil.json", "..\\escape.json"):
            with self.subTest(name=name):
                self.assertRejected(self._archive(base + [(name, b"x")]), "P01")

    def test_reject_duplicate_entry(self):
        base = arc.valid_entries()
        dup = base + [("knowledge/evidence/EV-001.json", b"{}")]
        self.assertRejected(self._archive(dup), "P02")

    def test_reject_casefold_duplicate(self):
        base = arc.valid_entries()
        self.assertRejected(self._archive(base + [("knowledge/evidence/ev-001.json", b"{}")]), "P02")

    def test_reject_symlink(self):
        base = arc.valid_entries()
        link = ("knowledge/link.json", b"/etc/passwd", {"mode": stat.S_IFLNK | 0o777})
        self.assertRejected(self._archive(base + [link]), "P03")

    def test_reject_directory_entry(self):
        base = arc.valid_entries()
        self.assertRejected(self._archive(base + [("knowledge/evidence/", b"", {"mode": stat.S_IFDIR | 0o755})]),
                            "P03")

    def test_reject_zip_bomb_ratio(self):
        files = arc.base_files()
        files["knowledge/bomb.json"] = b"\0" * (2 * 1024 * 1024)  # deflates to about 2 KB: ratio far above 200
        self.assertRejected(self._archive(arc.valid_entries(files)), "P05")

    def test_reject_oversize_header_lie(self):
        # header claims more than the per-entry cap (ratio cap also trips, both are P05)
        archive = self._archive(arc.valid_entries())
        arc.patch_central_file_size(archive, "knowledge/evidence/EV-001.json", MAX_ENTRY_BYTES + 1)
        self.assertRejected(archive, "P05")
        # header understates the real size: the manifest total no longer matches the headers
        archive = self._archive(arc.valid_entries())
        arc.patch_central_file_size(archive, "knowledge/evidence/EV-001.json", 1)
        self.assertRejected(archive, "P04")

    def test_reject_extra_entry(self):
        base = arc.valid_entries()
        self.assertRejected(self._archive(base + [("knowledge/evidence/extra.json", b"{}")]), "P04")

    def test_reject_missing_entry(self):
        entries = [e for e in arc.valid_entries() if e[0] != "provenance/sources.json"]
        self.assertRejected(self._archive(entries), "P04")
        entries = [e for e in arc.valid_entries() if e[0] != "package.json"]
        self.assertRejected(self._archive(entries), "P04")

    def test_reject_unsupported_container_features(self):
        base = arc.valid_entries()
        encrypted = [(n, d, {"flags": 0x1}) if n == "release.json" else (n, d) for n, d in base]
        self.assertRejected(self._archive(encrypted), "P08")
        bzip = [(n, d, {"method": zipfile.ZIP_BZIP2}) if n == "release.json" else (n, d) for n, d in base]
        self.assertRejected(self._archive(bzip), "P08")

    def test_failure_cleans_staging(self):
        # corrupt the payload of the last entry so streaming fails after earlier entries were written
        stored = [(n, d, {"method": zipfile.ZIP_STORED}) for n, d in arc.valid_entries()]
        archive = self._archive(stored)
        arc.flip_stored_byte(archive, "release.json")
        self.assertRejected(archive, "ZIP_CORRUPT")
        # and a pre-flight rejection never creates the staging root contents
        self.assertRejected(self._archive(arc.valid_entries() + [("../x", b"")]), "P01")


if __name__ == "__main__":
    unittest.main()
