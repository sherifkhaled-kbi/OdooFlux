"""State directory and run directories (ADR-013, R-03)."""

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from odooflux.core.recovery.audit_log import AuditLog
from odooflux.core.recovery.runlog import RunLog
from odooflux.utils.atomic import atomic_write_bytes

STATE_SCHEMA = "odooflux.runstate/1"
HEAVY_FIELDS = ("report", "edits")


def default_state_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "odooflux"


def check_state_dir(state_dir: Path, scanned: list) -> Optional[str]:
    """An error message when the state directory is inside a scanned path (FR-003)."""
    resolved = Path(state_dir).resolve()
    for root in scanned:
        root = Path(root).resolve()
        if resolved == root or root in resolved.parents:
            return f"state directory {resolved} is inside scanned path {root}"
    return None


class RunDir:
    """runs/<run-id>/ with state.json, work/, backup/, and log/run_log.jsonl (contracts/recovery.md)."""

    def __init__(self, root: Path, run_id: str, reversible: bool, external: bool = True):
        self.root = Path(root)
        self.run_id = run_id
        self.reversible = reversible
        self.state_path = self.root / "state.json"
        self.work_dir = self.root / "work"
        self.backup_dir = self.root / "backup"
        self.log_dir = self.root / "log"
        self.modules_dir = self.root / "modules"
        # Fix runs keep module results in modules/ (state.json stays small). Analyze and dry-run
        # runs keep them inline: they create only state.json and log/ (TST-003-030).
        self.external = bool(external)
        # log/audit.jsonl (not <run>/audit.jsonl): analysis runs may create only state.json and log/ (TST-003-030)
        self.audit = AuditLog(self.log_dir / "audit.jsonl", run_id)
        self.log = RunLog(self.log_dir / "run_log.jsonl", run_id, reversible, audit=self.audit)

    @classmethod
    def create(cls, state_dir: Path, reversible: bool, *, with_backup: bool) -> "RunDir":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{stamp}-{secrets.token_hex(3)}"
        run = cls(Path(state_dir) / "runs" / run_id, run_id, reversible, external=with_backup)
        if with_backup:
            run.backup_dir.mkdir()
        return run

    @classmethod
    def open(cls, state_dir: Path, run_id: str) -> "RunDir":
        root = Path(state_dir) / "runs" / run_id
        if not root.is_dir():
            raise FileNotFoundError(f"no run {run_id!r} in {state_dir}")
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        return cls(root, run_id, bool(state.get("options", {}).get("reversible", True)),
                   external=state.get("mode") == "fix")

    def save_module(self, entry: dict) -> None:
        """Write a module's heavy results (report, edits) once, when the module finishes.

        Keeping them out of state.json keeps each checkpoint small (state.json is rewritten after
        every module; its size would otherwise grow with the run)."""
        if not self.external or entry.get("report") is None:
            return
        heavy = {k: entry.get(k) for k in HEAVY_FIELDS}
        self.modules_dir.mkdir(exist_ok=True)
        target = self.modules_dir / f"{entry['name']}.json"
        atomic_write_bytes(target, json.dumps(heavy, sort_keys=True, separators=(",", ":")).encode("utf-8"))

    def write_state(self, state: dict) -> None:
        light = []
        for entry in state["modules"]:
            if not self.external:
                light.append(dict(entry))
                continue
            item = {k: v for k, v in entry.items() if k not in HEAVY_FIELDS}
            item["has_result"] = entry.get("report") is not None
            light.append(item)
        data = json.dumps({**state, "modules": light}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        atomic_write_bytes(self.state_path, data)
        if self.external:  # fix runs checkpoint for resume; analysis runs only record their start and end
            self.audit.append("checkpoint_written", "state.json", details={
                "status": state.get("status"), "modules_done": sum(
                    1 for m in state["modules"] if m.get("status") in ("PROMOTED", "DONE", "BLOCKED", "FAILED"))})

    def read_state(self) -> dict:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for entry in state["modules"]:
            if entry.pop("has_result", False):
                entry.update(json.loads((self.modules_dir / f"{entry['name']}.json").read_text(encoding="utf-8")))
        return state
