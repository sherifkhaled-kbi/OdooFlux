"""Rule loading with evidence enforcement and maturity capping (FR-003, FR-004). Used by the
rule registry; legacy-* rules are waived from the evidence requirement until P5 (P2_CUTOVER).

Binding (REQ-PY-003, REQ-EVD-001): ``bind_rule`` turns one metadata row into a ``BoundRule`` whose
detector and fixer are generic functions named by ``detector_ref``/``fixer_ref``. References resolve only
through the module table passed in by the caller (``odooflux.rules.bindable``; no dynamic import), so an
unknown reference cannot run code."""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field

from odooflux.knowledge.checks import rule_maturity
from odooflux.knowledge.loader import KnowledgeBase
from odooflux.core.contracts.records import SEVERITIES
from odooflux.rules.shared.emit import RuleContext


def resolve_rules(kb: KnowledgeBase):
    """Return (rules, warnings). Each rule dict gets an effective maturity; errors raise ValueError."""
    rules, warnings = [], []
    for rule in kb.rules:
        rid = rule["id"]
        if not rule.get("evidence") and not (rule.get("step") == "*" and rule.get("not_applicable_reason")):
            raise ValueError(f"rule {rid}: missing evidence")
        for ref in rule.get("evidence", []):
            if ref not in kb.evidence:
                raise ValueError(f"rule {rid}: unknown evidence {ref}")
        effective, capped = rule_maturity(rule, kb.evidence)
        if capped:
            warnings.append(f"rule {rid}: maturity capped to {effective} (evidence not verified)")
        rules.append({**rule, "effective_maturity": effective})
    return rules, warnings


MATURITIES = ("DRAFT", "DETECT_ONLY", "FIX_ENABLED", "RETIRED")
_DETECT_REQUIRED = ("DETECT_ONLY", "FIX_ENABLED")
_REQUIRED_TESTS = {"FIX_ENABLED": ("positive", "negative", "idempotence"),
                   "DETECT_ONLY": ("positive", "negative")}


class BindingError(ValueError):
    """A rule metadata row whose bindings or test references break the maturity rules."""


@dataclass(frozen=True)
class BoundRule:
    rule_id: str
    maturity: str
    review_required: bool
    context: RuleContext
    detector: object = None
    fixer: object = None
    detector_params: dict = field(default_factory=dict)
    fixer_params: dict = field(default_factory=dict)
    gap: str = ""  # INFO gap: why the rule is skipped for this run (a required run input is missing)

    def detect(self, document):
        if self.detector is None:
            return []
        return self.detector(document, self.context, **self.detector_params)

    def fix(self, document):
        if self.fixer is None:
            return []
        return self.fixer(document, self.context, **self.fixer_params)


def _lookup(ref: str, modules: Mapping):
    """The function named by ``module:function`` in ``modules``, or None. Only public functions defined in
    that module qualify."""
    module_name, _, func_name = ref.partition(":")
    module = modules.get(module_name)
    func = getattr(module, func_name, None) if module is not None and not func_name.startswith("_") else None
    if not inspect.isfunction(func) or func.__module__ != module.__name__:
        return None
    return func


def _keyword_params(func) -> tuple:
    """(accepted keyword names, required keyword names) after the document and context arguments."""
    parameters = list(inspect.signature(func).parameters.values())[2:]
    accepted = {p.name for p in parameters if p.kind == p.KEYWORD_ONLY}
    required = {p.name for p in parameters if p.kind == p.KEYWORD_ONLY and p.default is p.empty}
    return accepted, required


def _bind_ref(field_name: str, ref, modules: Mapping, problems: list):
    if not isinstance(ref, str) or ":" not in ref:
        problems.append(f"{field_name} {ref!r} must look like module:function")
        return None
    func = _lookup(ref, modules)
    if func is None:
        problems.append(f"{field_name} {ref!r} does not resolve to a generic rule function")
    return func


RUN_KEYS = ("target",)  # run-supplied inputs the planner may pass (FR-017, ADR-018 D-A1)


def declares_run_input(meta: dict, modules: Mapping) -> bool:
    """True when the detector or fixer named by ``meta`` declares a run key (``target``) as a keyword."""
    for ref in (meta.get("detector_ref"), meta.get("fixer_ref")):
        func = _lookup(ref, modules) if isinstance(ref, str) and ":" in ref else None
        if func is not None and _keyword_params(func)[0] & set(RUN_KEYS):
            return True
    return False


def _split_params(params: dict, funcs: list, problems: list, names: list, run_params=None, needs_run=None) -> list:
    """Give each function the params it accepts. Required arguments must be present (static or run);
    a key that no bound function accepts is an error (it would be silently ignored otherwise). Run
    params are passed only where declared; a static/run clash is an error; a required run key that is
    absent is recorded in ``needs_run`` instead of failing."""
    run_params = run_params or {}
    clash = sorted(set(params) & set(run_params))
    if clash:
        problems.append(f"params {', '.join(clash)} given both statically and by the run")
    accepted_all = set()
    result = []
    for func, name in zip(funcs, names):
        if func is None:
            result.append({})
            continue
        accepted, required = _keyword_params(func)
        accepted_all |= accepted
        absent = required - set(params) - set(run_params)
        run_missing = sorted(absent & set(RUN_KEYS))
        if needs_run is not None:
            needs_run.update(run_missing)
        missing = sorted(absent - set(RUN_KEYS))
        if missing:
            problems.append(f"params missing for {name} '{func.__module__}:{func.__name__}': {', '.join(missing)}")
        merged = {key: value for key, value in params.items() if key in accepted}
        merged.update({key: value for key, value in run_params.items() if key in accepted and key not in params})
        result.append(merged)
    unknown = sorted(set(params) - accepted_all)
    if unknown:
        problems.append(f"params not accepted by any bound function: {', '.join(unknown)}")
    return result


def bind_rule(meta: dict, modules: Mapping, run_params: dict | None = None) -> BoundRule:
    """Bind one rule metadata row (data-model.md RuleMetadata) against ``modules``, a mapping from module
    name to module object (``odooflux.rules.bindable.BINDABLE_MODULES``). Raises ``BindingError`` listing
    every problem, prefixed with the rule id. ``run_params`` (e.g. the planned target) is passed only to
    functions that declare the keyword; ``None`` keeps the static-only behaviour. A rule whose function
    requires a run key the run lacks binds with no detector and a ``gap`` message (skipped, never raised)."""
    rid = meta.get("id") or ""
    problems = []
    if not rid:
        problems.append("id is required")
    maturity = meta.get("maturity")
    if maturity not in MATURITIES:
        problems.append(f"maturity {maturity!r} is not one of {', '.join(MATURITIES)}")
    severity = meta.get("severity")
    if severity not in SEVERITIES:
        problems.append(f"severity {severity!r} is not one of {', '.join(SEVERITIES)}")
    if not isinstance(meta.get("step"), str) or not meta.get("step"):
        problems.append("step is required")
    review = meta.get("review_required", False)
    if not isinstance(review, bool):
        problems.append("review_required must be true or false")
    params = meta.get("params") or {}
    params_ok = isinstance(params, dict)
    if not params_ok:
        problems.append("params must be a mapping")
    detector_ref, fixer_ref = meta.get("detector_ref"), meta.get("fixer_ref")

    if maturity == "RETIRED":
        if detector_ref is not None or fixer_ref is not None:
            problems.append("RETIRED rule must not bind a detector_ref or fixer_ref")
    elif maturity in _DETECT_REQUIRED and not detector_ref:
        problems.append(f"detector_ref is required for maturity {maturity}")
    if review and fixer_ref is not None:
        problems.append("review_required rule must not have a fixer_ref")
    if fixer_ref is not None and maturity != "FIX_ENABLED":
        problems.append("fixer_ref requires FIX_ENABLED maturity")
    if maturity == "FIX_ENABLED" and fixer_ref is None:
        problems.append("FIX_ENABLED rule has no fixer_ref")

    tests = meta.get("tests") or {}
    for kind in _REQUIRED_TESTS.get(maturity, ()):
        if not tests.get(kind):
            problems.append(f"missing {kind} test")

    detector = _bind_ref("detector_ref", detector_ref, modules, problems) if detector_ref is not None else None
    fixer = _bind_ref("fixer_ref", fixer_ref, modules, problems) if fixer_ref is not None else None
    needs_run = set()
    detector_params, fixer_params = (
        _split_params(params, [detector, fixer], problems, ["detector_ref", "fixer_ref"], run_params, needs_run)
        if params_ok else ({}, {}))

    if problems:
        raise BindingError(f"rule {rid or '<no id>'}: " + "; ".join(problems))
    context = RuleContext(rule_id=rid, severity=severity, step=meta["step"],
                          message=meta.get("message", ""), suggestion=meta.get("suggestion", ""))
    if needs_run:
        gap = (f"INFO: rule {rid} skipped: run input not supplied: {', '.join(sorted(needs_run))}"
               " (unbound-needs-run-context)")
        return BoundRule(rule_id=rid, maturity=maturity, review_required=review, context=context, gap=gap)
    return BoundRule(rule_id=rid, maturity=maturity, review_required=review, context=context,
                     detector=detector, fixer=fixer, detector_params=detector_params,
                     fixer_params=fixer_params)
