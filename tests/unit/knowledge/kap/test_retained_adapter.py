"""Retained-snapshot adapter (feature 012 Wave 3b, addendum C1). Offline: a temporary directory and a blob store only.

Every refusal must raise SourceError with its closed code and must not return a snapshot. The adapter never reads a
repository, so no git is run here.
"""

import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.adapters.retained import RetainedSnapshotAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.release.canonical import canonical_bytes

SID = "odoo-enterprise-17.0"
REV = "e" * 40
CREATED = "2026-11-08T10:00:00Z"
SPEC = {"source_id": SID, "revision": REV}


class RetainedSnapshotAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        tree = self.base / "tree"
        (tree / "addons" / "sale_ent").mkdir(parents=True)
        (tree / "addons" / "sale_ent" / "__manifest__.py").write_text("{'name': 'x'}\n", encoding="utf-8")
        (tree / "addons" / "sale_ent" / "models.py").write_text("x = 1\n", encoding="utf-8")
        self.store = BlobStore(self.base / "store")
        self.snap = build_snapshot(tree, SID, REV, self.store, created_at=CREATED)
        self.snapshots = self.base / "snapshots"
        self.snapshots.mkdir()
        self._write(self.snap)
        self.digest = self.snap["snapshot_digest"]

    def _write(self, snap, name=SID):
        (self.snapshots / f"{name}.json").write_bytes(canonical_bytes(snap) + b"\n")

    def _adapter(self, digest=None):
        return RetainedSnapshotAdapter(self.snapshots, {SID: self.digest if digest is None else digest})

    def _refused(self, code, adapter=None, spec=SPEC):
        with self.assertRaises(SourceError) as ctx:
            (adapter or self._adapter()).snapshot(spec, self.store, created_at=CREATED)
        self.assertEqual(ctx.exception.code, code, ctx.exception.message)
        return ctx.exception

    def test_ok_returns_the_retained_snapshot(self):
        result = self._adapter().snapshot(SPEC, self.store, created_at=CREATED)
        self.assertEqual(result, self.snap)
        self.assertEqual(result["snapshot_digest"], self.digest)
        self.assertEqual(RetainedSnapshotAdapter.kind, "RETAINED")

    def test_digest_differs_from_recorded_is_checksum_mismatch(self):
        self._refused("CHECKSUM_MISMATCH", adapter=self._adapter(digest="0" * 64))

    def test_expected_digest_absent_fails_closed(self):
        adapter = RetainedSnapshotAdapter(self.snapshots, {"some-other-source": self.digest})
        self._refused("CHECKSUM_MISMATCH", adapter=adapter)

    def test_missing_blob_is_io_error(self):
        digest = self.snap["entries"][0]["sha256"]
        self.store.path_for(digest).unlink()
        self._refused("IO_ERROR")

    def test_tampered_blob_is_checksum_mismatch(self):
        digest = self.snap["entries"][0]["sha256"]
        self.store.path_for(digest).write_bytes(b"altered after retention\n")
        self._refused("CHECKSUM_MISMATCH")

    def test_revision_mismatch_is_revision_unavailable(self):
        self._refused("REVISION_UNAVAILABLE", spec={"source_id": SID, "revision": "f" * 40})

    def test_missing_manifest_file_is_io_error(self):
        (self.snapshots / f"{SID}.json").unlink()
        self._refused("IO_ERROR")

    def test_unparseable_manifest_is_io_error(self):
        (self.snapshots / f"{SID}.json").write_text("{not json", encoding="utf-8")
        self._refused("IO_ERROR")

    def test_recorded_snapshot_digest_altered_is_checksum_mismatch(self):
        altered = dict(self.snap, snapshot_digest="1" * 64)
        self._write(altered)
        self._refused("CHECKSUM_MISMATCH")

    def test_entries_altered_under_an_unchanged_digest_is_checksum_mismatch(self):
        entries = [dict(entry) for entry in self.snap["entries"]]
        entries[0]["path"] = "addons/sale_ent/renamed.py"
        self._write(dict(self.snap, entries=entries))
        self._refused("CHECKSUM_MISMATCH")

    def test_manifest_of_another_source_is_io_error(self):
        self._write(dict(self.snap, source_id="odoo-enterprise-16.0"))
        self._refused("IO_ERROR")

    def test_source_id_cannot_escape_the_snapshots_directory(self):
        self._refused("IO_ERROR", spec={"source_id": "../escape", "revision": REV})

    def test_malformed_expected_digest_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            RetainedSnapshotAdapter(self.snapshots, {SID: "ABC"})


if __name__ == "__main__":
    unittest.main()
