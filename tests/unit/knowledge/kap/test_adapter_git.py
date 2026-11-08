"""TST-011-035 (REQ-KAP-007, REQ-KAP-009, REQ-KAP-001): git-local adapter (probe, snapshot; no substitution).

Runs against the synthetic repository built by T030 in a temporary folder. Offline; `git` plumbing only. Remote
URLs are checked for the allow-list and refused without any network access.
"""

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition.adapters import git_local
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.fixtures.kap.make_synth_repo import build_synth_repo

GIT = shutil.which("git")
SOURCE_ID = "odoo-community-17.0"
CREATED = "2026-11-08T10:00:00Z"
SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "snapshot.schema.json").read_text("utf-8"))
ALLOW = ["https://github.com/odoo/odoo/"]


def _spec(url, revision, kind="GIT_COMMUNITY", scope=None):
    return {
        "source_id": SOURCE_ID, "kind": kind, "official": False, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": "17.0", "revision": revision,
        "scope": scope or {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


@unittest.skipUnless(GIT, "git is not installed; the git-local adapter needs git")
class GitLocalAdapterTests(unittest.TestCase):
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
        self.store_root = Path(self._dir.name) / "store"
        self.store = BlobStore(self.store_root)
        self.local = "local:" + self.repo.path

    def _adapter(self, kind="GIT_COMMUNITY"):
        return GitLocalAdapter(kind, allow_list=ALLOW)

    def _objects_written(self) -> int:
        objects = self.store_root / "objects"
        return sum(1 for p in objects.rglob("*") if p.is_file()) if objects.exists() else 0

    def test_pinned_missing_fails(self):
        spec = _spec(self.local, "f" * 40)
        adapter = self._adapter()
        probe = adapter.probe(spec)
        self.assertFalse(probe["available"])
        self.assertEqual(probe["reason_code"], "REVISION_UNAVAILABLE")
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(spec, self.store)
        self.assertEqual(ctx.exception.code, "REVISION_UNAVAILABLE")
        self.assertEqual(self._objects_written(), 0)  # nothing stored for a failed pin

    def test_no_substitution(self):
        adapter = self._adapter()
        # a branch that exists in the repo, a prefix of a real SHA, or an unknown SHA is never substituted
        for revision in ("17.0", "16.0", "HEAD", self.repo.to_sha[:12], "f" * 40):
            with self.subTest(revision=revision), self.assertRaises(SourceError) as ctx:
                adapter.snapshot(_spec(self.local, revision), self.store)
            self.assertEqual(ctx.exception.code, "REVISION_UNAVAILABLE")
        self.assertEqual(self._objects_written(), 0)
        # the exact pinned revision of the other branch is still served
        ok = adapter.snapshot(_spec(self.local, self.repo.from_sha), self.store)
        self.assertEqual(ok["revision"], self.repo.from_sha)

    def test_snapshot_matches_tree(self):
        adapter = self._adapter()
        snap = adapter.snapshot(_spec(self.local, self.repo.to_sha), self.store)
        self.assertEqual(v.check(snap, SCHEMA), [])
        self.assertEqual(snap["revision"], self.repo.to_sha)
        self.assertEqual(snap["limits"]["excluded"], [])
        # the same commit extracted to a plain folder gives the same entries and digest
        extract = Path(self._dir.name) / "tree"
        extract.mkdir()
        archive = subprocess.run(["git", "-C", self.repo.path, "archive", "--format=tar", self.repo.to_sha],
                                 check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(extract, filter="data")
        plain = build_snapshot(extract, SOURCE_ID, self.repo.to_sha, BlobStore(Path(self._dir.name) / "s2"),
                               created_at=CREATED)
        snap_fixed = dict(snap, created_at=CREATED)
        self.assertEqual(snap_fixed["entries"], plain["entries"])
        self.assertEqual(snap_fixed["snapshot_digest"], plain["snapshot_digest"])
        self.assertEqual(snap_fixed["snapshot_id"], plain["snapshot_id"])
        # every blob is readable and verified through the blob store
        for entry in snap["entries"]:
            self.assertEqual(len(self.store.get(entry["sha256"])), entry["size"])

    def test_argument_lists_no_shell(self):
        real_run = subprocess.run
        calls = []

        def spy(argv, *args, **kwargs):
            calls.append((argv, kwargs))
            return real_run(argv, *args, **kwargs)

        adapter = self._adapter()
        with mock.patch.object(git_local.subprocess, "run", side_effect=spy):
            adapter.probe(_spec(self.local, self.repo.to_sha))
            adapter.snapshot(_spec(self.local, self.repo.to_sha), self.store)
        self.assertTrue(calls)
        for argv, kwargs in calls:
            with self.subTest(argv=argv):
                self.assertIsInstance(argv, list)
                self.assertEqual(argv[0], "git")
                self.assertFalse(kwargs.get("shell", False))
                self.assertIn("timeout", kwargs)
                self.assertEqual(kwargs["env"]["GIT_CONFIG_NOSYSTEM"], "1")
                self.assertNotIn("HOME", kwargs["env"])
                self.assertIn("core.fsmonitor=false", argv)

    def test_remote_url_never_fetched(self):
        adapter = self._adapter()
        allowed = _spec("https://github.com/odoo/odoo/", self.repo.to_sha)
        probe = adapter.probe(allowed)
        self.assertEqual((probe["available"], probe["reason_code"]), (False, "NETWORK_DISABLED"))
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(allowed, self.store)
        self.assertEqual(ctx.exception.code, "NETWORK_DISABLED")
        blocked = _spec("https://example.invalid/odoo.git", self.repo.to_sha)
        with self.assertRaises(SourceError) as ctx:
            adapter.snapshot(blocked, self.store)
        self.assertEqual(ctx.exception.code, "NOT_ALLOWLISTED")

    def test_non_hex_revision_refused(self):
        adapter = self._adapter()
        probe = adapter.probe(_spec(self.local, "17.0"))
        self.assertEqual(probe["reason_code"], "REVISION_UNAVAILABLE")

    def test_scope_include_reports_out_of_scope_files(self):
        scope = {"modules": "all", "include": ["*/migrations/*"], "exclude": [], "file_kinds": []}
        snap = self._adapter().snapshot(_spec(self.local, self.repo.to_sha, scope=scope), self.store)
        self.assertTrue(snap["entries"])
        self.assertTrue(all("/migrations/" in e["path"] for e in snap["entries"]))
        self.assertTrue(snap["limits"]["excluded"])
        self.assertTrue(all(x["reason"] == "NOT_IN_SCOPE" for x in snap["limits"]["excluded"]))


if __name__ == "__main__":
    unittest.main()
