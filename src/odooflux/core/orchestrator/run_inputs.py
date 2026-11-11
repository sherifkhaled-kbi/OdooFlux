"""Per-run rule inputs (FR-017, FR-019, ADR-018 D-A1): the planned ``target`` reaches opted-in rules.

Rule metadata rows whose detector declares a run key (``*.manifest.version-prefix``) are bound per run
through ``bind_rule(run_params)``. They are opt-in (``--enable-rule``) and DETECT_ONLY here: no fixer is
ever run from this path. A required run input that is missing yields an INFO gap, never a silent skip.
The rule rows and the bindable module table are injected by the composition root; nothing is imported
from the rule packages here.
"""

from odooflux.core.engine.documents import Document
from odooflux.core.orchestrator import knowledge_rules
from odooflux.rules.shared.legacy_adapter import _kind
from odooflux.rules.shared.loader import BindingError, bind_rule, declares_run_input


def run_params_for(target: str) -> dict:
    """Run parameters from the planned step's target version string; empty when unknown."""
    return {"target": target} if target else {}


class RunInputRule:
    """Registry-shaped adapter over a ``BoundRule``: detect-only, limited to the rule's file kinds."""

    contract_version = 1
    depends: tuple = ()

    def __init__(self, bound, meta: dict):
        self._bound = bound
        self.key = bound.rule_id
        self.step = meta.get("step") or "*"
        self._kinds = tuple(meta.get("file_kinds") or ())

    def detect(self, document) -> list:
        if self._kinds and _kind(document.path) not in self._kinds:
            return []
        return self._bound.detect(Document.from_text(document.path, document.text))


def bind_run_rules(rows, modules, run_params: dict, enabled) -> tuple:
    """(rules, gaps, unknown) for the enabled ids. ``unknown`` lists ids that name no run-input rule."""
    by_id = {r.get("id"): r for r in rows if declares_run_input(r, modules)}
    rules, gaps = [], []
    unknown = [rid for rid in enabled if rid not in by_id]
    for rid in enabled:
        meta = by_id.get(rid)
        if meta is None:
            continue
        meta = {**meta, "fixer_ref": None, "maturity": "DETECT_ONLY"}  # detect-only on this path
        try:
            bound = bind_rule(meta, modules, run_params)
        except BindingError as exc:
            gaps.append(f"INFO: rule {rid} skipped: {exc}")
            continue
        if bound.gap:
            gaps.append(bound.gap)
            continue
        rules.append(RunInputRule(bound, meta))
    return rules, gaps, unknown


class RunRuleBinder:
    """Injected by the composition root: ``rows_loader`` returns the rule metadata rows (loaded lazily, once).
    ``experimental`` (an ``ExperimentalFixers``) is offered to ``for_steps`` when a run asks for experimental fixes."""

    def __init__(self, rows_loader, modules, experimental=None):
        self._load, self._modules, self._rows = rows_loader, modules, None
        self._experimental = experimental

    def rows(self) -> list:
        if self._rows is None:
            self._rows = list(self._load())
        return self._rows

    def known(self) -> list:
        return sorted(r["id"] for r in self.rows() if declares_run_input(r, self._modules))

    def __call__(self, run_params: dict, enabled) -> tuple:
        return bind_run_rules(self.rows(), self._modules, run_params, enabled)

    def for_steps(self, run_params: dict, steps, experimental: bool = False) -> tuple:
        """(rules, gaps): the knowledge rules selected by the plan's step keys (WS-E). ``experimental`` (the run's
        ``--experimental-fixes``) adds the registry fixers to DETECT_ONLY rules; off, the result is unchanged."""
        fixers = self._experimental if experimental else None
        return knowledge_rules.bind_knowledge_rules(self.rows(), self._modules, run_params, steps, fixers)
