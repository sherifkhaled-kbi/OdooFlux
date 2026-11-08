"""Shared helpers: load golden models, build reports from scenarios."""

import json
from pathlib import Path

from ._setup import SRC  # noqa: F401
from . import fixtures

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "golden_fixtures" / "reports"


def golden_names():
    return sorted(p.stem for p in GOLDEN_DIR.glob("*.json"))


def golden(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def all_goldens() -> dict:
    return {n: golden(n) for n in golden_names()}


def build(name: str) -> dict:
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.model.model import build_report
    state, kwargs = fixtures.scenarios()[name]
    return build_report(state, reports_from_state(state), run_log_path="/state/runs/run-golden/log/run.jsonl",
                        **kwargs)
