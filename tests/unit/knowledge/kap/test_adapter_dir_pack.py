"""TST-011-036 (REQ-KAP-010): directory and snapshot-pack adapters.

The directory adapter must produce the same snapshot as the git-local adapter for the same tree. The pack adapter
must read its archive only through the safe reader (T010). Offline; uses the synthetic repository from T030.
"""

import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition.adapters import snapshot_pack
from odooflux.knowledge.acquisition.adapters.directory import DirectoryAdapter
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.adapters.snapshot_pack import SnapshotPackAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.release.canonical import digest_obj
from tests.fixtures.kap.make_synth_repo import build_synth_repo

from . import _archives as arc

SOURCE_ID = "odoo-community-17.0"
CREATED = "2026-11-08T10:00:00Z"
ALLOW = ["https://github.com/odoo/odoo/"]


def _spec(kind, url, revision):
    return {
        "source_id": SOURCE_ID, "kind": kind, "official": False, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": "17.0", "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


class DirectoryAndPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.repo = build_synth_repo(cls.base / "synth")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def _export_tree(self, sha: str, dest: Path) -> Path:
        """Materialise the committed tree of *sha* (no .git) with `git archive`, argument list only."""
        blob = subprocess.run(["git", "-C", self.repo.path, "archive", "--format=tar", sha],
                              capture_output=True, check=True, timeout=120).stdout
        dest.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
            tf.extractall(dest, filter="data")
        return dest

    def test_directory_snapshot_equals_git_snapshot(self):
        tree = self._export_tree(self.repo.to_sha, self.root / "tree")
        dir_spec = _spec("DIRECTORY", "local:" + str(tree), self.repo.to_sha)
        git_spec = _spec("GIT_COMMUNITY", "local:" + self.repo.path, self.repo.to_sha)

        dir_snap = DirectoryAdapter().snapshot(dir_spec, BlobStore(self.root / "store-dir"), created_at=CREATED)
        git_snap = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW).snapshot(
            git_spec, BlobStore(self.root / "store-git"), created_at=CREATED)

        self.assertGreater(len(dir_snap["entries"]), 0)
        self.assertEqual(dir_snap["entries"], git_snap["entries"])
        self.assertEqual(dir_snap["snapshot_digest"], git_snap["snapshot_digest"])
        self.assertEqual(dir_snap["limits"], git_snap["limits"])
        self.assertEqual(dir_snap["snapshot_id"], git_snap["snapshot_id"])

    def test_directory_probe_is_read_only_and_refuses_remote(self):
        tree = self._export_tree(self.repo.to_sha, self.root / "tree2")
        before = sorted(p.name for p in self.root.iterdir())
        ok = DirectoryAdapter().probe(_spec("DIRECTORY", "local:" + str(tree), self.repo.to_sha))
        self.assertTrue(ok["available"])
        missing = DirectoryAdapter().probe(_spec("DIRECTORY", "local:" + str(self.root / "nope"), self.repo.to_sha))
        self.assertFalse(missing["available"])
        self.assertEqual(missing["reason_code"], "IO_ERROR")
        remote = DirectoryAdapter().probe(_spec("DIRECTORY", "https://example.invalid/x", self.repo.to_sha))
        self.assertFalse(remote["available"])
        self.assertEqual(remote["reason_code"], "NETWORK_DISABLED")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_pack_uses_safe_reader(self):
        files = arc.base_files()
        archive = arc.write_zip(self.root / "good.ofkp", arc.valid_entries(files))
        label = "sha256:" + arc.sha256_hex(archive.read_bytes())
        spec = _spec("SNAPSHOT_PACK", "local:" + str(archive), label)
        store = BlobStore(self.root / "store-pack")
        staging = self.root / "staging"
        adapter = SnapshotPackAdapter(staging_root=staging)

        real = snapshot_pack.read_package_archive
        with mock.patch.object(snapshot_pack, "read_package_archive", side_effect=real) as spy:
            snap = adapter.snapshot(spec, store, created_at=CREATED)
        spy.assert_called_once()

        self.assertEqual([e["path"] for e in snap["entries"]], sorted(files))
        for entry in snap["entries"]:
            self.assertEqual(store.get(entry["sha256"]), files[entry["path"]])
        excluded = {e["path"]: e["reason"] for e in snap["limits"]["excluded"]}
        self.assertEqual(excluded, {"package.json": "PACK_METADATA", "integrity/SHA256SUMS": "PACK_METADATA"})
        self.assertEqual(snap["snapshot_digest"], digest_obj(
            {"source_id": SOURCE_ID, "revision": label, "entries": snap["entries"]}))
        self.assertEqual(list(staging.iterdir()) if staging.exists() else [], [], "staging is cleaned up")

    def test_pack_rejected_by_safe_reader_leaves_no_staging(self):
        files = arc.base_files()
        entries = arc.valid_entries(files) + [("../escape.txt", b"x\n")]
        archive = arc.write_zip(self.root / "bad.ofkp", entries)
        label = "sha256:" + arc.sha256_hex(archive.read_bytes())
        staging = self.root / "staging-bad"
        adapter = SnapshotPackAdapter(staging_root=staging)
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(_spec("SNAPSHOT_PACK", "local:" + str(archive), label), BlobStore(self.root / "s2"))
        self.assertEqual(ctx.exception.code, "SNAPSHOT_CORRUPT")
        self.assertEqual(list(staging.iterdir()) if staging.exists() else [], [])


if __name__ == "__main__":
    unittest.main()
