"""Enterprise-local adapter (REQ-KAP-007; source-adapter contract rule 4).

Reads a directory the user supplies (`local:<path>`). Without the explicit entitlement flag (`entitled=False`, set
by the `--i-am-entitled` CLI option) the source is skipped: probe and snapshot report `AUTH_REQUIRED`, which the
caller records as `SKIPPED_UNAUTHORIZED`. The adapter never reads credentials, never stores or logs them, and never
opens a network connection. Community-only builds continue; `community_limit_entry` gives the exclusion record to
list in the community snapshot's `limits`. The licence and access constraints are recorded in `provenance`.
"""

import re
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.snapshot import build_snapshot

__all__ = ["EnterpriseLocalAdapter", "community_limit_entry"]

_LOCAL = "local:"
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")


def community_limit_entry(spec: dict) -> dict:
    """The `limits.excluded` record for a skipped Enterprise source."""
    return {
        "path": f"source:{spec['source_id']}",
        "reason": "SKIPPED_UNAUTHORIZED AUTH_REQUIRED: ENTERPRISE_LOCAL requires an explicit entitlement flag",
    }


class EnterpriseLocalAdapter:
    kind = "ENTERPRISE_LOCAL"

    def __init__(self, entitled: bool = False):
        self._entitled = bool(entitled)

    def probe(self, spec: dict) -> dict:
        """Read-only check. Never raises for a source problem."""
        if not self._entitled:
            return _probe(False, "AUTH_REQUIRED", "no entitlement flag given; source skipped")
        if not spec["url"].startswith(_LOCAL):
            return _probe(False, "NETWORK_DISABLED", "enterprise sources are read only from a local path")
        if not _REVISION.match(spec["revision"] or ""):
            return _probe(False, "REVISION_UNAVAILABLE", "revision must be a 40-hex SHA or sha256:<digest>")
        if not Path(spec["url"][len(_LOCAL):]).is_dir():
            return _probe(False, "IO_ERROR", "supplied enterprise path is not a directory")
        return _probe(True, "OK", "supplied enterprise directory present")

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        probe = self.probe(spec)
        if not probe["available"]:
            raise SourceError(probe["reason_code"], spec["source_id"], probe["detail"])
        scope = spec.get("scope") or {}
        return build_snapshot(spec["url"][len(_LOCAL):], spec["source_id"], spec["revision"], store,
                              scope_exclude=scope.get("exclude") or [], created_at=created_at)

    def provenance(self, spec: dict) -> dict:
        """Licence and access constraints, and whether the entitlement flag was given. No paths, no secrets."""
        return {
            "source_id": spec["source_id"],
            "kind": self.kind,
            "entitled": self._entitled,
            "licence_access": spec["licence_access"],
            "licence_id": spec["licence_id"],
            "access": "user-supplied local directory; no credentials; no network",
        }


def _probe(available: bool, reason_code: str, detail: str) -> dict:
    return {"available": available, "reason_code": reason_code, "detail": detail}
