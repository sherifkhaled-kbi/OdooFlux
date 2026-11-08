"""Directory adapter (REQ-KAP-010; source-adapter contract, DIRECTORY row and rules 2, 6, 7, 8).

Reads a local directory given as a `local:<path>` url and snapshots it with `snapshot.build_snapshot`. No network,
no writes to the source tree. The `scope.include` / `scope.exclude` rules have the same meaning as in the git-local
adapter, so the same tree gives the same entries and `snapshot_digest` through either adapter.
"""

import fnmatch
import os
import re

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.release.canonical import digest_obj

__all__ = ["DirectoryAdapter", "apply_includes", "REVISION_PATTERN"]

REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
_LOCAL = "local:"


def _probe(available: bool, reason_code: str, detail: str) -> dict:
    return {"available": available, "reason_code": reason_code, "detail": detail}


def apply_includes(snap: dict, includes: list) -> dict:
    """Move entries that match no include pattern to `limits.excluded` as NOT_IN_SCOPE, then re-digest.

    An empty include list keeps everything. Blobs are content-addressed, so nothing is removed from the store.
    """
    if not includes:
        return snap
    kept, moved = [], []
    for entry in snap["entries"]:
        if any(fnmatch.fnmatchcase(entry["path"], p) for p in includes):
            kept.append(entry)
        else:
            moved.append({"path": entry["path"], "reason": "NOT_IN_SCOPE"})
    if not moved:
        return snap
    excluded = sorted(snap["limits"]["excluded"] + moved, key=lambda e: e["path"])
    digest = digest_obj({"source_id": snap["source_id"], "revision": snap["revision"], "entries": kept})
    return {**snap, "entries": kept, "snapshot_digest": digest, "snapshot_id": "ss-" + digest[:12],
            "limits": {**snap["limits"], "excluded": excluded}}


class DirectoryAdapter:
    kind = "DIRECTORY"

    def probe(self, spec: dict) -> dict:
        """Read-only check. Never raises for a source problem."""
        url, revision = spec["url"], spec["revision"]
        if not url.startswith(_LOCAL):
            return _probe(False, "NETWORK_DISABLED", "directory sources must be local: paths")
        if not REVISION_PATTERN.match(revision or ""):
            return _probe(False, "REVISION_UNAVAILABLE", "revision must be a 40-hex SHA or sha256:<64-hex> label")
        if not os.path.isdir(url[len(_LOCAL):]):
            return _probe(False, "IO_ERROR", "directory source path is not a directory")
        return _probe(True, "OK", "directory present")

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        """Store every in-scope file of the directory and return a SourceSnapshot dict. Raises SourceError when the
        source is unavailable; nothing is stored in that case."""
        source_id, revision = spec["source_id"], spec["revision"]
        probe = self.probe(spec)
        if not probe["available"]:
            raise SourceError(probe["reason_code"], source_id, probe["detail"])
        scope = spec.get("scope") or {}
        snap = build_snapshot(spec["url"][len(_LOCAL):], source_id, revision, store,
                              scope_exclude=list(scope.get("exclude") or []), created_at=created_at)
        return apply_includes(snap, list(scope.get("include") or []))
