"""TST-011-007 (REQ-KAP-025, REQ-KAP-026): kb-home layout, lock with PID check, atomic active pointer, listing."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.release import store
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError, ReleaseState
from odooflux.knowledge.release.store import (
    KbLock,
    KbLockedError,
    build_pointer,
    ensure_layout,
    list_installed,
    read_active,
    set_release_state,
    write_active,
)

SRC = Path(__file__).resolve().parents[4] / "src"
META = {
    "label": "test-release",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
T1 = "2026-11-01T10:00:00Z"
T2 = "2026-11-02T10:00:00Z"
T3 = "2026-11-03T10:00:00Z"


def _install(home: Path, content: bytes) -> str:
    """Build a release tree with `content`, move it into kb-home/releases/<release_id>, return the id."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        (tree / "knowledge").mkdir(parents=True)
        (tree / "knowledge" / "RULE.json").write_bytes(content)
        manifest = write_release_manifest(tree, META)
        dest = home / "releases" / manifest["release_id"]
        tree.rename(dest)
    return manifest["release_id"]


def _pointer(release_id: str, digest: str = "ab" * 32) -> dict:
    return {"format": "odooflux.active/1", "release_id": release_id, "digest": digest,
            "activated_at": T1, "previous": []}


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class KbStoreTests(unittest.TestCase):
    def test_active_write_atomic_fault(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = ensure_layout(Path(tmp) / "kb")
            first = _pointer("kr-111111111111")
            with KbLock(home):
                write_active(home, first)
            before = (home / "active.json").read_bytes()

            # the write goes through utils.atomic.atomic_write_text
            second = _pointer("kr-222222222222", "cd" * 32)
            with KbLock(home):
                with mock.patch.object(store, "atomic_write_text",
                                       wraps=store.atomic_write_text) as spy:
                    write_active(home, second)
                spy.assert_called_once()
                self.assertTrue(str(spy.call_args.args[0]).endswith("active.json"))
            self.assertEqual(read_active(home)["release_id"], "kr-222222222222")

            # a fault at each step of the atomic write leaves the old pointer byte for byte
            for target in ("os.replace", "os.fsync"):
                with self.subTest(fault=target):
                    current = (home / "active.json").read_bytes()
                    with KbLock(home), mock.patch(f"odooflux.utils.atomic.{target}",
                                                  side_effect=OSError("injected")):
                        with self.assertRaises(OSError):
                            write_active(home, _pointer("kr-333333333333"))
                    self.assertEqual((home / "active.json").read_bytes(), current)
                    leftovers = [p.name for p in home.iterdir() if p.name.startswith(".active.json")]
                    self.assertEqual(leftovers, [])
            self.assertNotEqual(before, (home / "active.json").read_bytes())

    def test_lock_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = ensure_layout(Path(tmp) / "kb")
            with KbLock(home):
                self.assertTrue((home / ".lock").is_file())
                with self.assertRaises(KbLockedError):
                    KbLock(home).acquire()
            self.assertFalse((home / ".lock").exists())
            with KbLock(home):  # free again after release
                pass

            # a live holder in another process is refused
            holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                (home / ".lock").write_text(f"{holder.pid}\n", encoding="utf-8")
                with self.assertRaises(KbLockedError):
                    KbLock(home).acquire()
                self.assertTrue((home / ".lock").is_file())  # the live holder's lock is not removed
            finally:
                holder.kill()
                holder.wait()
            (home / ".lock").unlink()

            # a stale lock (dead pid) is taken over
            (home / ".lock").write_text(f"{_dead_pid()}\n", encoding="utf-8")
            with KbLock(home):
                self.assertEqual((home / ".lock").read_text(encoding="utf-8").strip(), str(os.getpid()))
            self.assertFalse((home / ".lock").exists())

            # an unreadable lock is treated as held (fail closed)
            (home / ".lock").write_text("", encoding="utf-8")
            with self.assertRaises(KbLockedError):
                KbLock(home).acquire()

    def test_list_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = ensure_layout(Path(tmp) / "kb")
            ids = {}
            for content in (b"c", b"a", b"b"):
                ids[content] = _install(home, content)
            for content, release_id in ids.items():
                set_release_state(home, release_id, ReleaseState.INSTALLED)
            removed = _install(home, b"gone")
            set_release_state(home, removed, ReleaseState.REMOVED)

            with KbLock(home):
                write_active(home, _pointer(ids[b"b"]))
            listed = list_installed(home)
            self.assertEqual([r.release_id for r in listed], sorted(ids.values()))
            active = [r for r in listed if r.active]
            self.assertEqual([r.release_id for r in active], [ids[b"b"]])
            self.assertEqual(active[0].state, ReleaseState.ACTIVE)
            self.assertEqual({r.state for r in listed if not r.active}, {ReleaseState.INSTALLED})
            self.assertNotIn(removed, [r.release_id for r in listed])

            # a directory whose release.json does not match its name fails closed
            bad = home / "releases" / "kr-000000000000"
            bad.mkdir()
            (bad / "release.json").write_text("{}", encoding="utf-8")
            set_release_state(home, bad.name, ReleaseState.INSTALLED)
            with self.assertRaises(KnowledgeReleaseError):
                list_installed(home)

    def test_missing_active_means_builtin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = ensure_layout(Path(tmp) / "kb")
            before = sorted(p.relative_to(home).as_posix() for p in home.rglob("*"))
            self.assertIsNone(read_active(home))
            self.assertEqual(list_installed(home), [])
            after = sorted(p.relative_to(home).as_posix() for p in home.rglob("*"))
            self.assertEqual(before, after)
            self.assertFalse((home / "active.json").exists())

    def test_layout_and_previous_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = ensure_layout(Path(tmp) / "kb")
            for name in ("releases", "snapshots", "staging"):
                self.assertTrue((home / name).is_dir(), name)
            self.assertEqual(ensure_layout(home), home)  # idempotent

            a, b, c = "kr-aaaaaaaaaaaa", "kr-bbbbbbbbbbbb", "kr-cccccccccccc"
            p1 = build_pointer(None, a, "11" * 32, T1)
            self.assertEqual(p1["previous"], [])
            p2 = build_pointer(p1, b, "22" * 32, T2)
            self.assertEqual(p2["previous"], [{"release_id": a, "digest": "11" * 32, "deactivated_at": T2}])
            p3 = build_pointer(p2, c, "33" * 32, T3)
            self.assertEqual([e["release_id"] for e in p3["previous"]], [b, a])
            self.assertEqual(p3["release_id"], c)


if __name__ == "__main__":
    unittest.main()
