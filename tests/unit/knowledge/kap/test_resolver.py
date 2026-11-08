"""TST-011-015 (REQ-KAP-036, REQ-KAP-005, REQ-KAP-001): read-only, fail-closed knowledge resolution.

The built-in path must cause no writes: the kb-home is never created, locked or modified by `resolve_knowledge`.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release import resolver
from odooflux.knowledge.release.builtin import builtin_descriptor, builtin_digest, tree_fingerprint
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError, ReleaseState
from odooflux.knowledge.release.resolver import default_kb_home, resolve_knowledge
from odooflux.knowledge.release.store import KbLock, build_pointer, ensure_layout, set_release_state, write_active, \
    utc_now

META = {
    "label": "resolver-test",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [{"step": "16-17", "completeness": "COMPLETE", "ledger_digest": "ab" * 32}],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}


def _snapshot(root: Path) -> dict:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = path.lstat()
            out[str(path.relative_to(root))] = (st.st_mtime_ns, st.st_size)
    return out


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / "kb-home"
        resolver.clear_cache()

    def tearDown(self):
        resolver.clear_cache()
        self._tmp.cleanup()

    def _install(self, meta=META, state=ReleaseState.ACTIVE) -> str:
        """Build a release tree, install it under releases/<id>, make it active. Returns the release id."""
        ensure_layout(self.home)
        tree = self.base / "tree"
        (tree / "compatibility").mkdir(parents=True)
        (tree / "compatibility" / "16-17.rules.json").write_text('[{"id": "16-17.python.one"}]\n', encoding="utf-8")
        manifest = write_release_manifest(tree, meta)
        rid = manifest["release_id"]
        tree.rename(self.home / "releases" / rid)
        set_release_state(self.home, rid, state)
        with KbLock(self.home):
            write_active(self.home, build_pointer(None, rid, manifest["release_digest"], utc_now()))
        return rid

    def test_no_active_returns_builtin_without_writes(self):
        ensure_layout(self.home)
        before = _snapshot(self.home)
        handle = resolve_knowledge(self.home)
        self.assertTrue(handle.builtin)
        self.assertEqual("builtin", handle.release_id)
        self.assertEqual(KNOWLEDGE_ROOT, handle.root)
        self.assertEqual(builtin_digest(), handle.digest)
        self.assertEqual(before, _snapshot(self.home))

    def test_absent_home_is_not_created(self):
        missing = self.base / "never-made"
        handle = resolve_knowledge(missing)
        self.assertTrue(handle.builtin)
        self.assertFalse(missing.exists())

    def test_valid_active(self):
        rid = self._install()
        handle = resolve_knowledge(self.home)
        self.assertFalse(handle.builtin)
        self.assertEqual(rid, handle.release_id)
        self.assertEqual(self.home / "releases" / rid, handle.root)
        self.assertEqual("COMPLETE", handle.completeness)
        self.assertEqual({"16-17": "COMPLETE"}, handle.steps)
        self.assertEqual(len(handle.digest), 64)

    def test_corrupt_fails_closed(self):
        rid = self._install()
        (self.home / "releases" / rid / "compatibility" / "16-17.rules.json").write_text("[]\n", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)
        resolver.clear_cache()
        (self.home / "active.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)

    def test_missing_dir_fails_closed(self):
        rid = self._install()
        target = self.home / "releases" / rid
        for path in sorted(target.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        target.rmdir()
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)

    def test_removed_state_fails_closed(self):
        self._install(state=ReleaseState.REMOVED)
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)

    def test_require_complete(self):
        partial = dict(META, completeness="PARTIAL")
        self._install(meta=partial)
        self.assertEqual("PARTIAL", resolve_knowledge(self.home).completeness)
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home, require_complete=True)

    def test_require_complete_builtin_passes(self):
        self.assertTrue(resolve_knowledge(self.base / "none", require_complete=True).builtin)

    def test_kb_home_mtime_unchanged(self):
        self._install()
        before = _snapshot(self.home)
        for _ in range(3):
            resolve_knowledge(self.home)
        self.assertEqual(before, _snapshot(self.home))
        self.assertFalse((self.home / ".lock").exists())

    def test_digest_cached_per_process(self):
        self._install()
        with mock.patch.object(resolver, "require_intact", wraps=resolver.require_intact) as spy:
            resolve_knowledge(self.home)
            resolve_knowledge(self.home)
        self.assertEqual(1, spy.call_count)

    def _compat_file(self, rid):
        return self.home / "releases" / rid / "compatibility" / "16-17.rules.json"

    def test_cache_hit_when_unchanged(self):
        self._install()
        with mock.patch.object(resolver, "require_intact", wraps=resolver.require_intact) as spy:
            resolve_knowledge(self.home)
            resolve_knowledge(self.home)
        self.assertEqual(1, spy.call_count)

    def test_fingerprint_once_per_resolve(self):
        self._install()
        with mock.patch.object(resolver, "tree_fingerprint", wraps=tree_fingerprint) as spy:
            resolve_knowledge(self.home)
        self.assertEqual(1, spy.call_count)

    def test_modified_file_invalidates_cache(self):
        rid = self._install()
        target = self._compat_file(rid)
        with mock.patch.object(resolver, "require_intact", wraps=resolver.require_intact) as spy:
            resolve_knowledge(self.home)
            original = target.read_bytes()
            tampered = original.replace(b"one", b"two")
            self.assertEqual(len(original), len(tampered))
            st = target.stat()
            target.write_bytes(tampered)
            # same size, new mtime: only the mtime component of the fingerprint can detect this
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
            with self.assertRaises(KnowledgeReleaseError):
                resolve_knowledge(self.home)
        self.assertEqual(2, spy.call_count)

    def test_restored_mtime_is_residual_risk(self):
        """Documented residual risk, not a guarantee: a same-size edit whose mtime is restored to the cached value
        is NOT detected within the process, because the fingerprint is stat-only by design (no content hashing)."""
        rid = self._install()
        target = self._compat_file(rid)
        resolve_knowledge(self.home)
        st = target.stat()
        target.write_bytes(target.read_bytes().replace(b"one", b"two"))
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        with mock.patch.object(resolver, "require_intact", wraps=resolver.require_intact) as spy:
            resolve_knowledge(self.home)
        self.assertEqual(0, spy.call_count)

    def test_added_and_removed_file_invalidate(self):
        rid = self._install()
        root = self.home / "releases" / rid
        extra = root / "compatibility" / "extra.json"
        extra.write_text("[]\n", encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)
        extra.unlink()
        resolve_knowledge(self.home)
        target = self._compat_file(rid)
        saved = target.read_bytes()
        target.unlink()
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)
        target.write_bytes(saved)
        self.assertEqual(rid, resolve_knowledge(self.home).release_id)

    def test_tamper_raises_after_cache(self):
        rid = self._install()
        resolve_knowledge(self.home)
        self._compat_file(rid).write_text('[{"id": "evil.rule.with.longer.name"}]\n', encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            resolve_knowledge(self.home)

    def test_fingerprint_does_not_read_file_contents(self):
        tree = self.base / "fp-tree"
        (tree / "sub").mkdir(parents=True)
        (tree / "release.json").write_text("{}\n", encoding="utf-8")
        (tree / "sub" / "a.json").write_text("[]\n", encoding="utf-8")
        with mock.patch.object(Path, "read_bytes") as read_bytes, \
                mock.patch.object(Path, "read_text") as read_text, \
                mock.patch.object(Path, "open") as path_open, \
                mock.patch("builtins.open") as builtin_open:
            first = tree_fingerprint(tree)
            second = tree_fingerprint(tree)
        read_bytes.assert_not_called()
        read_text.assert_not_called()
        path_open.assert_not_called()
        builtin_open.assert_not_called()
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_home_from_env_and_xdg_default(self):
        rid = self._install()
        with mock.patch.dict(os.environ, {"ODOOFLUX_KB_HOME": str(self.home)}):
            self.assertEqual(rid, resolve_knowledge(None).release_id)
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.base / "xdg")}):
            self.assertEqual(self.base / "xdg" / "odooflux" / "kb", default_kb_home())

    def test_builtin_descriptor_is_static(self):
        desc = builtin_descriptor()
        self.assertEqual({"release_id": "builtin", "root": str(KNOWLEDGE_ROOT), "builtin": True, "digest": None,
                          "completeness": None}, desc)


if __name__ == "__main__":
    unittest.main()
