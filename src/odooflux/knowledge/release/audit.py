"""kb-home audit log: `audit.jsonl` at the kb-home root, release-lifecycle actions only (REQ-KAP-045, REQ-KAP-046;
contracts/release-lifecycle.md "Audit actions").

A thin wrapper over `core.recovery.audit_log.AuditLog`, which owns the hash chain, redaction and fsync. The wrapper
only narrows the action set to the release-lifecycle names and fixes the file location. Creating the log is lazy: the
kb-home directory is created on the first record, never on construction.
"""

from pathlib import Path

from odooflux.core.recovery.audit_log import AuditLog, verify_chain

AUDIT_NAME = "audit.jsonl"
RELEASE_ACTIONS = ("source_acquired", "source_failed", "build_started", "build_completed", "release_installed",
                   "release_activated", "release_deactivated", "release_rolled_back", "release_removed",
                   "package_exported", "package_rejected", "ai_proposal")


class KbAudit:
    def __init__(self, home, run_id: str, *, secrets=()):
        self.home = Path(home)
        self._log = AuditLog(self.home / AUDIT_NAME, run_id, secrets=secrets)

    def record(self, action: str, target: str = "", outcome: str = "ok", details=None) -> dict:
        if action not in RELEASE_ACTIONS:
            raise ValueError(f"{action!r} is not a release-lifecycle audit action")
        return self._log.append(action, target=target, outcome=outcome, details=details)


def verify_audit(home) -> tuple:
    """``(True, "")`` for an intact kb-home audit chain, else ``(False, reason)``. A missing log is an empty chain."""
    path = Path(home) / AUDIT_NAME
    if not path.exists():
        return True, ""
    return verify_chain(path)
