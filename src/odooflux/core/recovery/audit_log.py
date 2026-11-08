"""Append-only, hash-chained audit log (T018; REQ-SEC-005, FR-007; specs/010-hardening-release/contracts/audit-log.md).

One JSON line per consequential action: ``ts``, ``run_id``, ``seq`` (1, 2, ...), ``actor``, ``action``, ``target``
(relative where possible), ``outcome``, ``details`` and ``prev_hash``, the SHA-256 of the previous line as written
(64 zeros for the first). Editing, deleting or reordering an entry breaks the chain at the next entry; ``verify_chain``
names it. The last entry has no successor, so a change to the final line alone is not detectable by the chain; the
``run_finished`` entry closes a normal run.

Details never hold file contents, prompts or secrets: values are redacted (``utils.redaction``) before they are written
and the log refuses a location inside a scanned path (REQ-SEC-003). A failed audit write raises: an action that cannot
be recorded must not go on silently."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from odooflux.utils import redaction

GENESIS = "0" * 64
ACTOR = "tool"
OUTCOMES = ("ok", "failed", "refused")
ACTIONS = ("config_loaded", "plan_created", "workspace_created", "backup_created", "backup_verified", "file_written",
           "file_promoted", "edit_rejected", "rollback_started", "rollback_completed", "checkpoint_written",
           "ai_request", "runtime_launched", "runtime_teardown", "report_written", "run_finished",
           "module_blocked")  # module_blocked extends the contract list: a blocked module is a consequential outcome


class AuditError(Exception):
    pass


def _line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path, run_id: str, *, secrets=(), scanned_paths=()):
        self.path = Path(path)
        self.run_id = run_id
        self._secrets = list(secrets)
        resolved = self.path.resolve()
        for root in scanned_paths:
            root = Path(root).resolve()
            if resolved == root or root in resolved.parents:
                raise AuditError(f"audit log {resolved} is inside scanned path {root} (REQ-SEC-003)")
        self._seq, self._last_hash = 0, GENESIS
        self._resume()

    def add_secrets(self, secrets) -> None:
        self._secrets.extend(s for s in secrets if s)

    def _resume(self) -> None:
        """Continue an existing chain (rollback and resume reopen a run)."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if lines:
            try:
                self._seq = json.loads(lines[-1])["seq"]
            except (ValueError, KeyError, TypeError):
                raise AuditError(f"{self.path}: the last entry is unreadable; the chain cannot continue") from None
            self._last_hash = _line_hash(lines[-1])

    def append(self, action: str, target: str = "", outcome: str = "ok", details=None) -> dict:
        if action not in ACTIONS:
            raise AuditError(f"unknown audit action {action!r}")
        if outcome not in OUTCOMES:
            raise AuditError(f"unknown audit outcome {outcome!r}")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id, "seq": self._seq + 1, "actor": ACTOR, "action": action,
            "target": redaction.redact_text(str(target), self._secrets),
            "outcome": outcome,
            "details": redaction.scrub(details or {}, self._secrets),
            "prev_hash": self._last_hash,
        }
        line = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._seq += 1
        self._last_hash = _line_hash(line)
        return entry


def verify_chain(path) -> tuple:
    """``(True, "")`` for an intact chain, else ``(False, reason)`` naming the first broken entry (1-based)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return False, f"cannot read {path}: {type(exc).__name__}"
    previous = GENESIS
    for number, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except ValueError:
            return False, f"entry {number}: not valid JSON (truncated or edited)"
        if not isinstance(entry, dict) or entry.get("seq") != number:
            return False, f"entry {number}: sequence {entry.get('seq') if isinstance(entry, dict) else '?'} " \
                          f"does not follow the previous entry"
        if entry.get("prev_hash") != previous:
            return False, f"entry {number}: prev_hash does not match the previous entry"
        previous = _line_hash(line)
    return True, ""


def _relative(module_path, path) -> str:
    try:
        return f"{Path(module_path).name}/{Path(path).relative_to(module_path).as_posix()}"
    except (ValueError, TypeError):
        return Path(str(path)).name


def from_runlog(event: str, fields: dict):
    """Map a run-log event to ``(action, target, outcome, details)``, or None when it is not a consequential action.
    Only hashes, counts and rule ids are carried over; never file contents."""
    module = fields.get("module", "")
    if event == "backup_created":
        return "backup_created", module, "ok", {}
    if event == "backup_verified":
        return "backup_verified", module, "ok", {}
    if event == "backup_failed":
        return "backup_verified", module, "failed", {"reason": str(fields.get("reason", ""))[:200]}
    if event in ("file_written", "file_created"):
        target = _relative(fields.get("module_path", ""), fields.get("path", "")) if fields.get("module_path") else \
            f"{module}/{Path(str(fields.get('path', ''))).name}"
        return "file_promoted", target, "ok", {
            "created": event == "file_created", "renamed_from": fields.get("renamed_from"),
            "sha256_before": fields.get("sha256_before"), "sha256_after": fields.get("sha256_after"),
            "rules": list(fields.get("rules") or [])}
    if event == "edit_rejected":
        return "edit_rejected", f"{module}/{Path(str(fields.get('path', ''))).name}", "refused", {
            "rules": list(fields.get("rules") or []), "reason": str(fields.get("reason", ""))[:200]}
    if event == "module_blocked":
        return "module_blocked", module, "failed", {"reason": str(fields.get("reason", ""))[:300]}
    if event == "file_restored" and "count" in fields:  # a failed promotion put its files back
        return "rollback_completed", module, "ok", {"restored": fields["count"], "cause": "promotion_failed"}
    return None
