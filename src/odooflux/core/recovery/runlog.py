"""Append-only run log, JSON Lines, fsync per entry (FR-006, R-06)."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RUNLOG_SCHEMA = "odooflux.runlog/1"
ACCEPTED_SCHEMAS = ("odooflux.runlog/0", "odooflux.runlog/1")


class RunLog:
    def __init__(self, path, run_id: str, reversible: bool, audit=None):
        self.audit = audit  # AuditLog: consequential events are mirrored there (REQ-SEC-005)
        self.path = Path(path)
        self.run_id = run_id
        self.reversible = reversible
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: str, **fields) -> None:
        record = {
            "schema": RUNLOG_SCHEMA,
            "run_id": self.run_id,
            "event": event,
            "reversible": self.reversible,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **fields,
        }
        line = json.dumps(record, sort_keys=True) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        if self.audit is not None:
            from odooflux.core.recovery.audit_log import from_runlog
            mapped = from_runlog(event, fields)
            if mapped is not None:
                self.audit.append(*mapped)


def read_runlog(path):
    """Return (entries, warnings). A truncated final line is ignored with a warning."""
    entries, warnings = [], []
    path = Path(path)
    if not path.exists():
        return entries, warnings
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if number == len(lines):
                warnings.append(f"line {number}: truncated entry ignored")
                continue
            raise ValueError(f"corrupt run log entry at line {number}") from None
        if record.get("schema") not in ACCEPTED_SCHEMAS:
            raise ValueError(f"unsupported run log schema {record.get('schema')!r}")
        entries.append(record)
    return entries, warnings
