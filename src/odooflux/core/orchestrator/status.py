"""Module result status decision (contracts/status-decision.md). Pure function: first matching row wins.

Implemented in core because core packages may not import ``odooflux.validation``; ``odooflux.validation.status``
re-exports it.

Row 1 BLOCKED, 2 FAILED, 3 NEEDS_REVIEW, 4 VERIFIED_SUCCESS, 5 INSTALL_VERIFIED, 6 STATIC_VALIDATED,
7 NEEDS_REVIEW fallback. Layers L1-L3 are always required. Row 7 is unreachable for valid inputs: any
layer in L1-L3 that is not PASS is either FAIL (row 2) or UNAVAILABLE/SKIPPED (row 1).
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional

from odooflux.core.contracts.records import ValidationResult

OUTCOMES = ("PASS", "FAIL", "UNAVAILABLE", "SKIPPED")
PLAN_STATES = ("ok", "refused", "unverified_allowed")
TOOL_STATES = ("ok", "backup_failed", "workspace_failed", "promotion_failed", "tool_error")
COVERAGE = (None, "full", "partial")
ALWAYS_REQUIRED = (1, 2, 3)
NOT_RUN = "not_run"


@dataclass(frozen=True)
class StatusInputs:
    layers: dict = field(default_factory=dict)          # {1..5: outcome}; missing layers are SKIPPED
    l5_coverage: Optional[str] = None                    # full | partial | None (L5 only)
    plan_state: str = "ok"
    tool_state: str = "ok"
    required_layers: tuple = ()                          # added to L1-L3
    open_critical: int = 0
    open_warning: int = 0
    open_review: int = 0
    rejected_edits: int = 0                              # informational only
    sub_validator_unavailable: int = 0                   # L1/L2 sub-validator for a present file kind


@dataclass(frozen=True)
class StatusDecision:
    status: str
    row: int
    reasons: tuple
    inputs_digest: str


def _normalise(inputs: StatusInputs) -> dict:
    if inputs.plan_state not in PLAN_STATES:
        raise ValueError(f"unknown plan_state {inputs.plan_state!r}")
    if inputs.tool_state not in TOOL_STATES:
        raise ValueError(f"unknown tool_state {inputs.tool_state!r}")
    if inputs.l5_coverage not in COVERAGE:
        raise ValueError(f"unknown l5_coverage {inputs.l5_coverage!r}")
    for name, value in (("open_critical", inputs.open_critical), ("open_warning", inputs.open_warning),
                        ("open_review", inputs.open_review), ("sub_validator_unavailable", inputs.sub_validator_unavailable)):
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    layers = {}
    for n in range(1, 6):
        outcome = inputs.layers.get(n, "SKIPPED")
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome for L{n}: {outcome!r}")
        layers[n] = outcome
    unknown = set(inputs.layers) - set(range(1, 6))
    if unknown:
        raise ValueError(f"unknown layers {sorted(unknown)}")
    return layers


def _digest(inputs: StatusInputs) -> str:
    payload = {"layers": {str(k): v for k, v in sorted(inputs.layers.items())}, "l5_coverage": inputs.l5_coverage,
               "plan_state": inputs.plan_state, "tool_state": inputs.tool_state,
               "required_layers": sorted(inputs.required_layers), "open_critical": inputs.open_critical,
               "open_warning": inputs.open_warning, "open_review": inputs.open_review,
               "rejected_edits": inputs.rejected_edits,
               "sub_validator_unavailable": inputs.sub_validator_unavailable}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def decide(inputs: StatusInputs) -> StatusDecision:
    """Return the status for *inputs*. Raises ValueError for values outside the contract vocabulary."""
    L = _normalise(inputs)
    digest = _digest(inputs)
    required = sorted(set(ALWAYS_REQUIRED) | set(inputs.required_layers))

    # Row 1
    reasons = []
    if inputs.plan_state == "refused":
        reasons.append("plan_refused")
    if inputs.tool_state != "ok":
        reasons.append(f"tool_state:{inputs.tool_state}")
    reasons += [f"required_layer_{L[n].lower()}:L{n}" for n in required if L[n] in ("UNAVAILABLE", "SKIPPED")]
    if reasons:
        return StatusDecision("BLOCKED", 1, tuple(reasons), digest)

    # Row 2
    reasons = [f"layer_failed:L{n}" for n in range(1, 6) if L[n] == "FAIL"]
    if inputs.open_critical > 0:
        reasons.append("open_critical_findings")
    if reasons:
        return StatusDecision("FAILED", 2, tuple(reasons), digest)

    # Row 3
    reasons = []
    if inputs.open_review > 0:
        reasons.append("open_review_findings")
    if inputs.open_warning > 0:
        reasons.append("open_warning_findings")
    if inputs.plan_state == "unverified_allowed":
        reasons.append("unverified_plan")
    if inputs.sub_validator_unavailable > 0:
        reasons.append("sub_validator_unavailable")
    if reasons:
        return StatusDecision("NEEDS_REVIEW", 3, tuple(reasons), digest)

    # Rows 4-6
    if all(L[n] == "PASS" for n in (1, 2, 3, 4)) and L[5] == "PASS" and inputs.l5_coverage == "full":
        return StatusDecision("VERIFIED_SUCCESS", 4, (), digest)
    if all(L[n] == "PASS" for n in (1, 2, 3, 4)):
        return StatusDecision("INSTALL_VERIFIED", 5, (), digest)
    if all(L[n] == "PASS" for n in (1, 2, 3)):
        return StatusDecision("STATIC_VALIDATED", 6, (), digest)

    # Row 7: unreachable for valid inputs (see module docstring).
    return StatusDecision("NEEDS_REVIEW", 7, ("unmatched_combination",), digest)


def unavailable(layer: int, reason: str) -> ValidationResult:
    """A layer that could not run. The reason is required (FR-002)."""
    return ValidationResult(layer=layer, outcome="UNAVAILABLE", reason=reason)


def skipped(layer: int, reason: str) -> ValidationResult:
    """A layer that was not attempted on purpose. The reason is required (FR-002)."""
    return ValidationResult(layer=layer, outcome="SKIPPED", reason=reason)


def serialise_layers(results: dict) -> dict:
    """Layer outcomes for reports: keys L1..L5. A layer without a result is UNAVAILABLE, never PASS."""
    out = {}
    for n in range(1, 6):
        result = results.get(n)
        if result is None:
            out[f"L{n}"] = {"outcome": "UNAVAILABLE", "reason": NOT_RUN, "coverage": None}
        else:
            out[f"L{n}"] = {"outcome": result.outcome, "reason": result.reason, "coverage": result.coverage}
    return out


def decide_status(layers: dict, *, open_critical: int = 0, open_review: int = 0,
                  open_warning: int = 0, unverified: bool = False, blocked_reason=None,
                  tool_ok: bool = True, required=(), l5_coverage=None):
    """Return (status, reasons). *layers* maps layer number (1–5) to PASS/FAIL/UNAVAILABLE/SKIPPED.

    Adapter kept for existing callers: L1–L3 are always required (contract). ``blocked_reason`` is a
    tool-state failure text. Rows 4–6 carry no trigger reasons; use ``decide`` for the matched row."""
    tool_state = "tool_error" if (not tool_ok or blocked_reason) else "ok"
    decision = decide(StatusInputs(
        layers=dict(layers),
        l5_coverage=l5_coverage,
        plan_state="unverified_allowed" if unverified else "ok",
        tool_state=tool_state,
        required_layers=tuple(required),
        open_critical=open_critical,
        open_warning=open_warning,
        open_review=open_review,
    ))
    reasons = list(decision.reasons)
    if blocked_reason and decision.status == "BLOCKED":
        reasons.insert(0, blocked_reason)
    return decision.status, reasons
