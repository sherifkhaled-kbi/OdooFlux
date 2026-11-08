"""Snapshot-pack adapter (REQ-KAP-010; source-adapter contract, SNAPSHOT_PACK row and rules 6, 7, 8).

Reads a local `.ofkp` archive given as a `local:<path>` url. The archive is validated and streamed into a staging
directory only by `package.archive.read_package_archive` (safe reader, T010). Any rejection becomes
`SourceError(SNAPSHOT_CORRUPT)` and the staging directory is removed. The pack's own metadata (`package.json`,
`integrity/SHA256SUMS`) is listed in `limits.excluded` with reason `PACK_METADATA`, not dropped silently.

Manifest sha256 comparison belongs to package validation (P06, T012); this adapter hashes the bytes it stores.
"""

import os
import shutil
import tempfile
from pathlib import Path

from odooflux.knowledge.acquisition.adapters.directory import REVISION_PATTERN, apply_includes
from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.package.archive import PackageError, read_package_archive

__all__ = ["SnapshotPackAdapter", "PACK_METADATA_RULES"]

_LOCAL = "local:"
PACK_METADATA_RULES = (
    {"pattern": "package.json", "reason": "PACK_METADATA"},
    {"pattern": "integrity/SHA256SUMS", "reason": "PACK_METADATA"},
)


def _probe(available: bool, reason_code: str, detail: str) -> dict:
    return {"available": available, "reason_code": reason_code, "detail": detail}


class SnapshotPackAdapter:
    kind = "SNAPSHOT_PACK"

    def __init__(self, staging_root=None):
        """`staging_root` is a directory for the safe reader; None uses a fresh temporary directory per call."""
        self._staging_root = None if staging_root is None else Path(staging_root)

    def probe(self, spec: dict) -> dict:
        """Read-only check. Never raises for a source problem."""
        url, revision = spec["url"], spec["revision"]
        if not url.startswith(_LOCAL):
            return _probe(False, "NETWORK_DISABLED", "snapshot packs must be local: paths")
        if not REVISION_PATTERN.match(revision or ""):
            return _probe(False, "REVISION_UNAVAILABLE", "revision must be a 40-hex SHA or sha256:<64-hex> label")
        if not os.path.isfile(url[len(_LOCAL):]):
            return _probe(False, "IO_ERROR", "snapshot pack is not a file")
        return _probe(True, "OK", "snapshot pack present")

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        source_id, revision = spec["source_id"], spec["revision"]
        probe = self.probe(spec)
        if not probe["available"]:
            raise SourceError(probe["reason_code"], source_id, probe["detail"])
        archive = spec["url"][len(_LOCAL):]
        scope = spec.get("scope") or {}
        own_staging = self._staging_root is None
        staging_root = Path(tempfile.mkdtemp(prefix="kap-pack-")) if own_staging else self._staging_root
        try:
            try:
                staged = read_package_archive(archive, staging_root)
            except PackageError as exc:
                raise SourceError("SNAPSHOT_CORRUPT", source_id, f"snapshot pack rejected by safe reader: {exc.code}"
                                  ) from exc
            try:
                rules = list(PACK_METADATA_RULES) + list(scope.get("exclude") or [])
                snap = build_snapshot(staged.staging_dir, source_id, revision, store, scope_exclude=rules,
                                      created_at=created_at)
            finally:
                staged.discard()
        finally:
            if own_staging:
                shutil.rmtree(staging_root, ignore_errors=True)
        return apply_includes(snap, list(scope.get("include") or []))
