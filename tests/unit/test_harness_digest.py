"""TST-002-001 (REQ-TST-001): tree_digest is order-independent and detects a one-byte change."""

import shutil
import tempfile
import unittest
from pathlib import Path

from tests._support.digest import digest_hex, tree_digest


def _write(root: Path, files: dict, order) -> None:
    for name in order:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(files[name])


class TreeDigestTests(unittest.TestCase):
    FILES = {"a.txt": b"alpha", "sub/b.txt": b"beta", "sub/deep/c.txt": b"gamma"}

    def test_order_independent(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            _write(Path(one), self.FILES, sorted(self.FILES))
            _write(Path(two), self.FILES, sorted(self.FILES, reverse=True))
            self.assertEqual(tree_digest(one), tree_digest(two))
            self.assertEqual(digest_hex(one), digest_hex(two))

    def test_one_byte_change_detected(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            _write(Path(one), self.FILES, sorted(self.FILES))
            shutil.copytree(one, Path(two) / "copy")
            (Path(two) / "copy" / "sub" / "b.txt").write_bytes(b"betb")
            self.assertNotEqual(tree_digest(one), tree_digest(Path(two) / "copy"))
            self.assertNotEqual(digest_hex(one), digest_hex(Path(two) / "copy"))

    def test_added_file_detected(self):
        with tempfile.TemporaryDirectory() as one:
            _write(Path(one), self.FILES, sorted(self.FILES))
            before = digest_hex(one)
            (Path(one) / "new.txt").write_bytes(b"")
            self.assertNotEqual(before, digest_hex(one))


if __name__ == "__main__":
    unittest.main()
