"""Knowledge-base rules in the migrate pipeline (WS-E, FR-017, ADR-018).

For a plan (its steps, e.g. ``17-18``, ``18-19``), the metadata rows whose step is in the plan or ``*`` are bound
once per run (``bind_rule`` with the run parameters) and become engine rules. Detection runs on every module file
of the rule's kind. Only ``FIX_ENABLED`` rules have a fixer, and their edits go through ``apply_edits`` and the
existing validate and re-scan path; ``DETECT_ONLY`` rules never edit (SC-005). ``DRAFT``/``RETIRED`` rows and rules
that declare a run key (opt-in via ``--enable-rule``) are not selected here. Rule rows and the bindable module
table are injected by the composition root; nothing is imported from the rule packages.
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

    def __init__(self, bound, meta: dict):
        self._bound = bound
        self.key = bound.rule_id
        self.step = meta.get("step") or "*"
        self.maturity = bound.maturity
        self.review_required = bound.review_required
        self.evidence = tuple(meta.get("evidence") or ())
        self.fixes = bound.fixer is not None
        self._kinds = tuple(meta.get("file_kinds") or ())

    def applies_to(self, path: str) -> bool:
        return not self._kinds or file_kind(path) in self._kinds

    def detect(self, document) -> list:
        if not self.applies_to(document.path):
            return []
        found = self._bound.detect(_shared_document(document))
        return [dataclasses.replace(f, evidence=self.evidence) for f in found]

    def fix(self, document: Document) -> list:
        return self._bound.fix(document) if self.fixes and self.applies_to(document.path) else []


def bind_knowledge_rules(rows, modules, run_params: dict, steps) -> tuple:
    """(rules, gaps). A row that does not bind is an INFO gap, never an exception or a silent skip."""
    rules, gaps = [], []
    for meta in select_rows(rows, modules, steps):
        try:
            bound = bind_rule(meta, modules, run_params)
        except BindingError as exc:
            gaps.append(f"INFO: rule {meta.get('id')} skipped: {exc}")
            continue
        if bound.gap:
            gaps.append(bound.gap)
            continue
        rules.append(KnowledgeRule(bound, meta))
    return rules, gaps


def rules_for_file(rules, path: str) -> list:
    return [r for r in rules if r.applies_to(path)]


def fixing_transform(rules, steps):
    """``callable(path, text) -> text`` applying the FIX_ENABLED rules step by step, or None when none apply.
    Edits go through ``apply_edits`` (overlap resolution, stale-span checks); the caller validates the result."""
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
            if edits:
                text = apply_edits(document, edits, precedence=[r.key for r in batch]).text
        return text

    return transform


def deduplicate(issues, knowledge_ids) -> list:
    """Drop knowledge-rule issues on a file line already reported by an overlapping legacy category."""
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

    return [i for i in issues
            if not retired_duplicate(i)
            and not (i.category in knowledge_ids and covered(i.category, i.line, legacy.get(i.file, {})))]
