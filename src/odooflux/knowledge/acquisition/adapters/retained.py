"""Retained-snapshot adapter (feature 012 Wave 3b, plan addendum C1; source-adapter contract rules 6, 7, 8).

A carried source is not re-fetched and not re-read from a repository. Its verified snapshot manifest, written by an
earlier run of the pipeline into `<snapshots_dir>/<source_id>.json`, is returned again, but only when every check
below passes. Any failure raises `SourceError`, so the pipeline records the source as FAILED and fails closed:

- the manifest file exists and parses, and its `source_id` is the spec's;
- `snapshot_digest` recomputes from `source_id`, `revision` and `entries` (the formula snapshot.py uses);
- the recomputed digest equals `expected_digests[source_id]` (the digest the installed release recorded); an absent
  expectation is a refusal, never a pass;
- the manifest revision equals the spec's pinned revision;
- every referenced blob exists in `store` and re-hashes to its recorded sha256 and size.

No network and no repository access: the adapter reads only the snapshots directory and the blob store. The
`created_at` argument is accepted for interface compatibility and ignored, because the stored manifest is returned
byte-for-byte equal in content. Retained blobs live in the update staging directory, never in a release or package.
"""

import hashlib
import json
import re
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.release.canonical import digest_obj

__all__ = ["RetainedSnapshotAdapter"]

_HEX64 = re.compile(r"[0-9a-f]{64}")  # used with fullmatch: `$` would accept a trailing newline
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")  # a source id is used as a file name, so no separators


class RetainedSnapshotAdapter:
    """Returns a retained, re-verified snapshot manifest. Registered per source (`BuildPlan.adapter_by_source`)."""

    kind = "RETAINED"  # adapter label only; the source keeps its own kind in the registry

    def __init__(self, snapshots_dir, expected_digests: dict):
        for source_id, digest in dict(expected_digests).items():
            if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
                raise ValueError(f"expected digest for {source_id!r} must be 64 lowercase hex characters")
        self.snapshots_dir = Path(snapshots_dir)
        self.expected_digests = dict(expected_digests)

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        """The retained SourceSnapshot dict for `spec`. Raises SourceError (CHECKSUM_MISMATCH, REVISION_UNAVAILABLE or
        IO_ERROR) and returns nothing when any check fails."""
        source_id, revision = spec["source_id"], spec["revision"]
        if not isinstance(source_id, str) or not _SAFE_ID.fullmatch(source_id):
            raise SourceError("IO_ERROR", source_id, "source id cannot name a retained snapshot file")
        path = self.snapshots_dir / f"{source_id}.json"
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise SourceError("IO_ERROR", source_id,
                              f"retained snapshot is missing or unreadable ({type(exc).__name__})") from None
        if not isinstance(snap, dict) or not isinstance(snap.get("entries"), list):
            raise SourceError("IO_ERROR", source_id, "retained snapshot has no entries list")
        if snap.get("source_id") != source_id:
            raise SourceError("IO_ERROR", source_id, "retained snapshot belongs to another source")
        entries = snap["entries"]

        recomputed = digest_obj({"source_id": source_id, "revision": snap.get("revision"), "entries": entries})
        if snap.get("snapshot_digest") != recomputed:
            raise SourceError("CHECKSUM_MISMATCH", source_id, "retained snapshot digest does not recompute")
        expected = self.expected_digests.get(source_id)
        if expected is None:
            raise SourceError("CHECKSUM_MISMATCH", source_id, "no expected digest is recorded for this source")
        if recomputed != expected:
            raise SourceError("CHECKSUM_MISMATCH", source_id, "retained snapshot differs from the recorded digest")
        if snap.get("revision") != revision:
            raise SourceError("REVISION_UNAVAILABLE", source_id, "retained snapshot revision differs from the pin")

        for entry in entries:
            digest = entry.get("sha256") if isinstance(entry, dict) else None
            try:
                blob_path = store.path_for(digest)
            except ValueError:
                raise SourceError("IO_ERROR", source_id, "retained snapshot holds a malformed blob digest") from None
            if not blob_path.is_file():
                raise SourceError("IO_ERROR", source_id, "a retained blob is missing from the store")
            try:
                data = blob_path.read_bytes()
            except OSError:
                raise SourceError("IO_ERROR", source_id, "a retained blob cannot be read") from None
            if hashlib.sha256(data).hexdigest() != digest or len(data) != entry.get("size"):
                raise SourceError("CHECKSUM_MISMATCH", source_id, "a retained blob no longer matches its digest")
        return snap
