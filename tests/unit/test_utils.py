"""TST-003-006 (REQ-SAF-007): ported helpers, including atomic-write fault injection."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.utils.atomic import atomic_write_text
from odooflux.utils.hashing import finding_id, sha256_bytes
from odooflux.utils.paths import is_within
from odooflux.utils.redact import redact

from ._setup import SRC  # noqa: F401


class UtilsTests(unittest.TestCase):
    def test_atomic_write_keeps_original_on_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.py"
            target.write_text("old\n", encoding="utf-8")
            with mock.patch("os.replace", side_effect=OSError("crash")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.py"])

    def test_sha256_and_finding_id(self):
        self.assertEqual(sha256_bytes(b"abc")[:8], "ba7816bf")
        self.assertEqual(finding_id("a", 1), finding_id("a", 1))
        self.assertNotEqual(finding_id("a", 1), finding_id("a", 2))

    def test_is_within_rejects_escapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            self.assertTrue(is_within(root / "x", root))
            self.assertFalse(is_within(Path(tmp) / "other", root))
            link = root / "link"
            os.symlink(Path(tmp), link)
            self.assertFalse(is_within(link, root))

    def test_redact_hides_keys(self):
        self.assertNotIn("sk-ant-abcdefgh12345", redact("key sk-ant-abcdefgh12345"))
        self.assertIn("REDACTED", redact("api_key=secret123"))


if __name__ == "__main__":
    unittest.main()
