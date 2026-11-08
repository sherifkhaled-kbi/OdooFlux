"""Stage and per-module progress lines derived from the report model (REQ-REP-002, REQ-REP-006). Pure functions."""

from odooflux.reporting.options import sanitize_text

STAGES = ("Discover", "Plan", "Workspace", "Step N/M", "Validate L1-L5", "Promote", "Report")


def stage_line() -> str:
    return " > ".join(STAGES)


def _layers(module: dict) -> str:
    return " ".join(f"{k} {v['outcome']}" for k, v in sorted(module["layers"].items()))


def progress_lines(report: dict) -> list:
    """One line per module: index, name, status and every layer outcome (unrun layers are never PASS)."""
    total = len(report["modules"])
    return [f"[{i}/{total}] {sanitize_text(m['name'])}  {m['status']}  {_layers(m)}"
            for i, m in enumerate(report["modules"], 1)]
