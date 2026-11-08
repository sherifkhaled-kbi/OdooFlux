"""Transition coverage of a migration against the active knowledge release (REQ-KAP-037, REQ-KAP-041;
contracts/migration-integration.md "Transition coverage"). Core module: stdlib and core imports only.

For every planned step `NN-NN` the handle's release status decides the effect:

- COMPLETE: no finding.
- PARTIAL: warning `KAP_TRANSITION_PARTIAL`; the step still counts as covered (warning only).
- absent, FAILED or any other value: warning `KAP_TRANSITION_NOT_COVERED`; the run is not verified. The caller feeds
  this to the existing status inputs as an unverified-scope limit (no new status value). Missing knowledge is never
  success.

The built-in handle is never checked: no warnings, verified (byte-compatible with a run without releases).
"""

from dataclasses import dataclass

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
NOT_COVERED = "NOT_COVERED"
PARTIAL_CODE = "KAP_TRANSITION_PARTIAL"
NOT_COVERED_CODE = "KAP_TRANSITION_NOT_COVERED"


@dataclass(frozen=True)
class CoverageResult:
    steps: tuple      # ((step, COMPLETE | PARTIAL | NOT_COVERED), ...) in plan order
    warnings: tuple   # strings in the report `warnings` shape
    verified: bool    # False when at least one step is not covered


def release_step_key(step_id: str) -> str:
    """Release step key `N-M` for a plan step id `N.0->M.0` (the same mapping as the rule step keys)."""
    source, _, target = str(step_id).partition("->")
    if not target:
        return str(step_id)
    return f"{source.split('.', 1)[0]}-{target.split('.', 1)[0]}"


def check_transition_coverage(handle, steps) -> CoverageResult:
    """Coverage of the planned plan-step ids *steps* (`N.0->M.0`) against *handle* (a `KnowledgeHandle`)."""
    if handle.builtin:
        return CoverageResult(steps=tuple((release_step_key(s), COMPLETE) for s in steps), warnings=(),
                              verified=True)
    rows, warnings, verified = [], [], True
    for step in map(release_step_key, steps):
        status = handle.steps.get(step)
        if status == COMPLETE:
            rows.append((step, COMPLETE))
        elif status == PARTIAL:
            rows.append((step, PARTIAL))
            warnings.append(f"{PARTIAL_CODE}: step {step} is only partially covered by knowledge release "
                            f"{handle.release_id}; see the release steps_covered limits")
        else:
            verified = False
            rows.append((step, NOT_COVERED))
            warnings.append(f"{NOT_COVERED_CODE}: knowledge not available for step {step} in knowledge release "
                            f"{handle.release_id}; this step cannot be reported verified")
    return CoverageResult(steps=tuple(rows), warnings=tuple(warnings), verified=verified)
