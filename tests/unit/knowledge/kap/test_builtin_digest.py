"""TST-011-016 (REQ-KAP-005, REQ-KAP-036): built-in release identity digest and its side-effect freedom.

`builtin_digest` must be deterministic, change when a loaded file changes, ignore `__pycache__` and `*.pyc`, be cached per
process, and `resolve_knowledge` with no active release must stay free of writes while reporting that digest.
"""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release import builtin
from odooflux.knowledge.release.builtin import builtin_digest, clear_digest_cache
from odooflux.knowledge.release.resolver import resolve_knowledge

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _snapshot(root: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            out[str(path.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


def _touch_newer(path: Path, seconds: int = 5) -> None:
    """Give `path` a deterministic, different mtime so stat-based fingerprints change."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + seconds * 1_000_000_000))


class BuiltinDigestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        (self.tree / "compatibility").mkdir(parents=True)
        (self.tree / "compatibility" / "16-17.rules.json").write_text('[{"id": "16-17.a"}]\n', encoding="utf-8")
        (self.tree / "README.txt").write_text("knowledge\n", encoding="utf-8")
        clear_digest_cache()

    def tearDown(self):
        clear_digest_cache()
        self._tmp.cleanup()

    def test_builtin_digest_deterministic(self):
        first = builtin_digest(self.tree)
        self.assertRegex(first, HEX64)
        self.assertEqual(first, builtin_digest(self.tree))
        # same bytes at another path, with different mtimes, give the same digest
        copy = self.base / "elsewhere" / "copy"
        shutil.copytree(self.tree, copy)
        for path in copy.rglob("*"):
            if path.is_file():
                _touch_newer(path, seconds=1000)
        clear_digest_cache()
        self.assertEqual(first, builtin_digest(copy))
        self.assertRegex(builtin_digest(), HEX64)
        self.assertEqual(builtin_digest(), builtin_digest())

    def test_builtin_digest_changes_when_a_file_changes(self):
        before = builtin_digest(self.tree)
        target = self.tree / "compatibility" / "16-17.rules.json"
        target.write_text('[{"id": "16-17.b"}]\n', encoding="utf-8")
        _touch_newer(target)
        after_edit = builtin_digest(self.tree)
        self.assertNotEqual(before, after_edit)
        added = self.tree / "compatibility" / "extra.json"
        added.write_text("[]\n", encoding="utf-8")
        self.assertNotEqual(after_edit, builtin_digest(self.tree))

    def test_pycache_ignored(self):
        plain = builtin_digest(self.tree)
        (self.tree / "__pycache__").mkdir()
        (self.tree / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\x00bytecode")
        (self.tree / "__pycache__" / "notes.txt").write_text("ignored too\n", encoding="utf-8")
        (self.tree / "compatibility" / "__pycache__").mkdir()
        (self.tree / "compatibility" / "__pycache__" / "x.pyc").write_bytes(b"\x01")
        (self.tree / "stray.pyc").write_bytes(b"\x02")
        clear_digest_cache()
        self.assertEqual(plain, builtin_digest(self.tree))
        (self.tree / "data.json").write_text("{}\n", encoding="utf-8")
        clear_digest_cache()
        self.assertNotEqual(plain, builtin_digest(self.tree))

    def test_builtin_digest_cached_per_process(self):
        with mock.patch.object(builtin, "_scan", wraps=builtin._scan) as spy:
            first = builtin_digest(self.tree)
            self.assertEqual(first, builtin_digest(self.tree))
            self.assertEqual(1, spy.call_count)
            _touch_newer(self.tree / "README.txt")
            builtin_digest(self.tree)
            self.assertEqual(2, spy.call_count)

    def test_resolve_builtin_has_digest(self):
        missing = self.base / "no-kb-home"
        handle = resolve_knowledge(missing)
        self.assertTrue(handle.builtin)
        self.assertEqual("builtin", handle.release_id)
        self.assertEqual(KNOWLEDGE_ROOT, handle.root)
        self.assertEqual(builtin_digest(), handle.digest)
        self.assertRegex(handle.digest, HEX64)

    def test_resolve_builtin_still_has_no_side_effects(self):
        kb_home = self.base / "kb-home"
        fake_home = self.base / "home"
        fake_home.mkdir()
        before = _snapshot(self.base)
        with mock.patch.dict(os.environ, {"HOME": str(fake_home), "XDG_DATA_HOME": ""}):
            os.environ.pop("ODOOFLUX_KB_HOME", None)
            resolve_knowledge(None)
            resolve_knowledge(kb_home)
            resolve_knowledge(kb_home)
        self.assertEqual(before, _snapshot(self.base))
        self.assertFalse(kb_home.exists())
        self.assertFalse((fake_home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
