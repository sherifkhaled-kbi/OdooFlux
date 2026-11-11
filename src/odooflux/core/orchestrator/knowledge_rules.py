"""Knowledge-base rules in the migrate pipeline (WS-E, FR-017, ADR-018).

For a plan (its steps, e.g. ``17-18``, ``18-19``), the metadata rows whose step is in the plan or ``*`` are bound
once per run (``bind_rule`` with the run parameters) and become engine rules. Detection runs on every module file
of the rule's kind. Only ``FIX_ENABLED`` rules have a fixer, and their edits go through ``apply_edits`` and the
existing validate and re-scan path; ``DETECT_ONLY`` rules never edit (SC-005). ``DRAFT``/``RETIRED`` rows and rules
that declare a run key (opt-in via ``--enable-rule``) are not selected here. Rule rows and the bindable module
table are injected by the composition root; nothing is imported from the rule packages.

Experimental fixes (AD-1): with ``--experimental-fixes`` a selected DETECT_ONLY row that has an entry in the
experimental registry gets that entry's fixer. Such a rule is marked ``experimental``, its row keeps DETECT_ONLY, and
its edits go through the same ``apply_edits`` path. The registry is a code table, not the KB; the composition root
injects it as an ``ExperimentalFixers`` value, so this module never imports the rule packages.
"""

import dataclasses
import functools

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.discovery.manifest import MANIFEST_NAMES
from odooflux.rules.shared.legacy_overlap import LEGACY_CATEGORIES, RETIRED_CATEGORIES, covered
from odooflux.rules.shared.loader import BindingError, bind_rule, declares_run_input

RUNNABLE = ("DETECT_ONLY", "FIX_ENABLED")
_KIND_BY_EXT = {"py": "python", "xml": "xml", "csv": "csv", "js": "javascript", "ts": "javascript",
                "mjs": "javascript"}


@functools.lru_cache(maxsize=8192)
def file_kind(path: str) -> str:
    """The rule ``file_kinds`` value for a path: manifest, python, xml, csv, javascript, or ''."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in MANIFEST_NAMES:
        return "manifest"
    dot = name.rfind(".")
    return _KIND_BY_EXT.get(name[dot + 1:], "") if dot > 0 else ""


def _major(version: str) -> int:
    return int(str(version).split(".", 1)[0])


def step_keys(plan_step_ids) -> list:
    """Rule step keys (``N-M``) for plan step ids (``N.0->M.0``)."""
    keys = []
    for step_id in plan_step_ids:
        source, _, target = str(step_id).partition("->")
        keys.append(f"{_major(source)}-{_major(target)}")
    return keys


def step_keys_for_range(from_version: int, to_version: int) -> list:
    return [f"{v}-{v + 1}" for v in range(from_version, to_version)]


def select_rows(rows, modules, steps) -> list:
    """Rows to run for ``steps``: step-specific rows in the window plus ``*`` rows; runnable maturities with a
    detector; rules that need a run input are left to the opt-in path."""
    window = set(steps) | {"*"}
    return [r for r in rows
            if r.get("step") in window and r.get("maturity") in RUNNABLE and r.get("detector_ref")
            and not declares_run_input(r, modules)]


_SHARED: list = [None, None, None]  # [path, text, Document]: all rules of a run read one file in turn


def _shared_document(document) -> Document:
    """One engine Document per file for every rule, instead of one per rule and file (hot path)."""
    text = document.text
    if _SHARED[0] != document.path or _SHARED[1] is not text:
        _SHARED[:] = [document.path, text, Document.from_text(document.path, text)]
    return _SHARED[2]


class KnowledgeRule:
    """Registry-shaped adapter over a ``BoundRule``; carries maturity, review flag and evidence for the report."""

    contract_version = 1
    depends: tuple = ()

    def __init__(self, bound, meta: dict, experimental=None):
        self._bound = bound
        self._experimental = experimental  # the registry entry when this rule runs an experimental fixer
        self._views = bound.fixer_params.get("views")  # the run's module context (VR-1), None when absent
        self.key = bound.rule_id
        self.step = meta.get("step") or "*"
        self.maturity = bound.maturity
        self.review_required = bound.review_required
        self.evidence = tuple(meta.get("evidence") or ())
        self.fixes = bound.fixer is not None
        self.experimental = experimental is not None
        self.fix_class = "experimental" if self.experimental else ("certified" if self.fixes else "")
        self._kinds = tuple(meta.get("file_kinds") or ())

    def explain(self, document):
        """The experimental plan (conversions and refusals) for ``document``; None for other rules. Pure."""
        if self._experimental is None:
            return None
        return self._experimental.explain(document, views=self._views)

    def applies_to(self, path: str) -> bool:
        return not self._kinds or file_kind(path) in self._kinds

    def detect(self, document) -> list:
        if not self.applies_to(document.path):
            return []
        found = self._bound.detect(_shared_document(document))
        return [dataclasses.replace(f, evidence=self.evidence) for f in found]

    def fix(self, document: Document) -> list:
        return self._bound.fix(document) if self.fixes and self.applies_to(document.path) else []


@dataclasses.dataclass(frozen=True)
class ExperimentalFixers:
    """The experimental registry as injected by the composition root: ``entries`` maps a rule id to an entry (its
    ``fixer_ref``, ``params`` and ``explain``); ``modules`` resolves those fixer references, as the bindable table does
    for ordinary rows."""

    entries: object
    modules: object
    views: object = None  # zero-argument factory of the run's module context (VR-1), None for no module context


def experimental_entry(meta: dict, experimental: ExperimentalFixers | None):
    """The registry entry offered to row ``meta``: only a DETECT_ONLY row whose id has an entry naming the row's own
    step. A fixer is never offered to another version's row. None when there is no such entry."""
    if experimental is None or meta.get("maturity") != "DETECT_ONLY":
        return None
    entry = experimental.entries.get(meta.get("id"))
    return entry if entry is not None and entry.step == meta.get("step") else None


def effective_maturity(meta: dict, modules, experimental: ExperimentalFixers | None = None) -> str:
    """The maturity a row executes with, computed at read time (AD-02: FIX_ENABLED means executable availability).

    A DETECT_ONLY row reads as FIX_ENABLED when its offered registry entry binds (no gap, a fixer attached). Every
    other row reads its stored maturity; DRAFT and RETIRED never change. The stored row is never modified."""
    stored = meta.get("maturity")
    entry = experimental_entry(meta, experimental)
    if entry is None:
        return stored
    try:
        bound = bind_rule(meta, {**modules, **experimental.modules}, None, experimental=entry)
    except BindingError:
        return stored
    return "FIX_ENABLED" if bound.fixer is not None and not bound.gap else stored


def bind_knowledge_rules(rows, modules, run_params: dict, steps,
                          experimental: ExperimentalFixers | None = None) -> tuple:
    """(rules, gaps). A row that does not bind is an INFO gap, never an exception or a silent skip.

    ``experimental`` (``None`` keeps the default behaviour exactly) offers registry fixers. One is used only for a
    selected DETECT_ONLY row with a matching entry; its fixer resolves through ``experimental.modules``."""
    rules, gaps = [], []
    views = experimental.views() if experimental is not None and experimental.views is not None else None
    for meta in select_rows(rows, modules, steps):
        entry = experimental_entry(meta, experimental)
        bind_modules = {**modules, **experimental.modules} if entry is not None else modules
        try:
            bound = bind_rule(meta, bind_modules, run_params, experimental=entry)
        except BindingError as exc:
            gaps.append(f"INFO: rule {meta.get('id')} skipped: {exc}")
            continue
        if bound.gap:
            gaps.append(bound.gap)
            continue
        if entry is not None and views is not None:  # the fixer's module context, bound for this run only
            bound = dataclasses.replace(bound, fixer_params={**bound.fixer_params, "views": views})
        rules.append(KnowledgeRule(bound, meta, entry))
    return rules, gaps


def rules_for_file(rules, path: str) -> list:
    return [r for r in rules if r.applies_to(path)]


def _experimental_record(rule, path: str, document):
    """The conversions and refusals an experimental rule reports for this document (None when it has neither)."""
    plan = rule.explain(document)
    if plan is None or not (plan.converted or plan.refused):
        return None
    return {"rule_id": rule.key, "path": path,
            "converted": [{"line": c.line, "element": c.element, "before": c.before, "after": c.after,
                           "note": c.note} for c in plan.converted],
            "refused": [{"line": r.line, "element": r.element, "reason": r.reason} for r in plan.refused]}


def fixing_transform(rules, steps, log=None):
    """``callable(path, text) -> text`` applying the FIX_ENABLED rules step by step, or None when none apply.
    Edits go through ``apply_edits`` (overlap resolution, stale-span checks); the caller validates the result.
    ``log`` (a list) receives one record per file and experimental rule that converted or refused something."""
    fixers = [r for r in rules if r.fixes]
    if not fixers:
        return None
    order = {key: i for i, key in enumerate(steps)}

    def transform(path: str, text: str) -> str:
        mine = [r for r in fixers if r.applies_to(path)]
        for step in sorted({r.step for r in mine}, key=lambda s: order.get(s, -1)):
            batch = [r for r in mine if r.step == step]
            document = Document.from_text(path, text)
            edits = [e for r in batch for e in r.fix(document)]
            if log is not None:
                log.extend(record for record in (_experimental_record(r, path, document)
                                                 for r in batch if r.experimental) if record)
            if edits:
                text = apply_edits(document, edits, precedence=[r.key for r in batch]).text
        return text

    return transform


def handled_lines(file_log, path: str) -> frozenset:
    """(file, line, rule id) of each construct an experimental rule converted or refused in ``path`` (AD-1)."""
    return frozenset((path, line, record["rule_id"]) for record in file_log
                     for line in [c["line"] for c in record["converted"]] + [r["line"] for r in record["refused"]])


def deduplicate(issues, knowledge_ids, handled=frozenset()) -> list:
    """Drop knowledge-rule issues on a file line already reported by an overlapping legacy category.

    ``handled`` holds (file, line, rule id) for constructs an experimental rule acted on or refused (AD-1). Its
    knowledge finding is kept, and the overlapping legacy row on that line is dropped, so the construct is reported
    once. A knowledge finding the experimental rule never saw (for example a states= that the legacy layer already
    converted) follows the ordinary rule above."""
    legacy: dict = {}
    for issue in issues:
        if issue.category not in knowledge_ids:
            legacy.setdefault(issue.file, {}).setdefault(issue.category, set()).add(issue.line)
    seen = {(i.file, i.line, i.category) for i in issues}

    def retired_duplicate(i) -> bool:  # a retired legacy row never doubles a sibling or knowledge rule (WSE-001)
        if i.category not in RETIRED_CATEGORIES:
            return False
        return any((i.file, i.line, other) in seen for rid, cats in LEGACY_CATEGORIES.items() if i.category in cats
                   for other in (*cats, rid) if other != i.category)

    def superseded(i) -> bool:  # a legacy row whose construct an experimental rule handled on the same line
        return i.category not in knowledge_ids and any(
            (i.file, i.line, rid) in handled for rid, cats in LEGACY_CATEGORIES.items() if i.category in cats)

    return [i for i in issues
            if not retired_duplicate(i)
            and not superseded(i)
            and not (i.category in knowledge_ids and (i.file, i.line, i.category) not in handled
                     and covered(i.category, i.line, legacy.get(i.file, {})))]
