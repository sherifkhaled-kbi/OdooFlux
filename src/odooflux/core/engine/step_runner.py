"""Step runner: rules run in ``depends`` order, a step's output is the next step's input,
and the L1 validator runs before any output is accepted (FR-009, FR-015)."""

from dataclasses import dataclass, field

from odooflux.core.contracts.records import Document, Finding
from odooflux.core.engine.verdict import judge_output
from odooflux.dependencies.graph import topo_order


@dataclass
class Step:
    step_id: str
    rules: list
    transform: object = None  # callable(path, text) -> text, or None for detect-only


@dataclass
class StepOutcome:
    step_id: str
    findings: list = field(default_factory=list)
    output: str = ""
    rejected: bool = False
    rejection: str = ""
    errors: list = field(default_factory=list)
    verdict: object = None  # FileVerdict of the transform's output (None when there is no transform)


_ORDER_CACHE: dict = {}  # (keys, dependency edges) -> ordered keys; the same rule set is ordered once per file


def order_rules(rules: list) -> list:
    by_key = {r.key: r for r in rules}
    deps = {r.key: [d for d in getattr(r, "depends", ()) if d in by_key] for r in rules}
    signature = tuple((key, tuple(edges)) for key, edges in deps.items())
    order = _ORDER_CACHE.get(signature)
    if order is None:
        topo, cycles, _blocked = topo_order(deps)
        if cycles:
            raise ValueError(f"rule dependency cycle: {cycles}")
        order = tuple(topo)
        if len(_ORDER_CACHE) >= 64:
            _ORDER_CACHE.clear()
        _ORDER_CACHE[signature] = order
    return [by_key[k] for k in order]


def detect(rules: list, path: str, text: str, errors: list) -> list:
    """Run every rule; an exception becomes a RULE_ERROR finding and the run continues."""
    findings = []
    for rule in order_rules(rules):
        try:
            findings.extend(rule.detect(Document(path=path, text=text)))
        except Exception as exc:  # plugin code: never let it stop the run
            errors.append(f"{rule.key}: {exc}")
            findings.append(Finding(rule_id="RULE_ERROR", path=path, line=0, severity="WARNING",
                                    message=f"rule {rule.key} raised {type(exc).__name__}: {exc}"))
    return findings


def run_step(step: Step, path: str, text: str, validators: list) -> StepOutcome:
    outcome = StepOutcome(step_id=step.step_id)
    outcome.findings = detect(step.rules, path, text, outcome.errors)
    if step.transform is None:
        outcome.output = text
        return outcome
    candidate = step.transform(path, text)
    outcome.verdict = judge_output(validators, path, candidate)
    if not outcome.verdict.keep:
        outcome.rejected = True
        outcome.rejection = f"{outcome.verdict.status}: {outcome.verdict.reason}"
        outcome.output = text
        return outcome
    outcome.output = candidate
    return outcome


def run_steps(steps: list, path: str, text: str, validators: list) -> list:
    """Chain steps: each step's accepted output is the next step's input."""
    outcomes, current = [], text
    for step in steps:
        outcome = run_step(step, path, current, validators)
        outcomes.append(outcome)
        if outcome.rejected:
            break
        current = outcome.output
    return outcomes


def validate_output(validators: list, path: str, text: str):
    """The refusal for *text* (``STATUS: reason``) when its verdict does not keep it, or None to accept it."""
    verdict = judge_output(validators, path, text)
    return None if verdict.keep else f"{verdict.status}: {verdict.reason}"
