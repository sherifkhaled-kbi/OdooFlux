"""Authoring checks A001..A006 (contract manual-rule-cli, feature 011, REQ-KAP-020).

Pure: KnowledgeBase -> findings, like knowledge/checks.py. Only rules whose maturity is not RETIRED count as active.
Non-built-in trees run these checks by default. The built-in tree runs them only when `strict_builtin` is set, so
built-in validation output stays byte-identical (REQ-KAP-005).
"""

import json
from collections import defaultdict

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, Finding, KnowledgeBase

RULES_FILE = "compatibility/*.rules.json"
FIX_ENABLED = "FIX_ENABLED"
SELECTOR = "selector"
OUTPUT = "output"

# Role of every param key used by the shipped rules (derived from the detector and fixer signatures).
# A SELECTOR key says what a rule matches; an OUTPUT key says what a fixer writes or what the finding reports.
# A rule's selector is its params minus the OUTPUT keys. A key not listed here is treated as a SELECTOR.
PARAM_ROLES = {
    "attribute": SELECTOR, "callee": SELECTOR, "decorator": SELECTOR, "field": SELECTOR,
    "from_type": SELECTOR, "key": SELECTOR, "keyword": SELECTOR, "mapping": SELECTOR, "method": SELECTOR,
    "methods": SELECTOR, "model_ids": SELECTOR, "module": SELECTOR, "old": SELECTOR, "qualified": SELECTOR,
    "tag": SELECTOR, "value": SELECTOR, "xml_ids": SELECTOR,
    "new": OUTPUT, "new_keyword": OUTPUT, "new_name": OUTPUT, "new_value": OUTPUT, "to_type": OUTPUT,
}


def is_builtin_tree(kb: KnowledgeBase) -> bool:
    return kb.root.resolve() == KNOWLEDGE_ROOT.resolve()


def _rows(kb: KnowledgeBase) -> list:
    return [r for r in kb.rules if isinstance(r, dict) and isinstance(r.get("id"), str)]


def _active(rows: list) -> list:
    return [r for r in rows if r.get("maturity") != "RETIRED"]


def _params_key(params) -> str:
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"))


def selector_params(params) -> dict:
    """The params that select what a rule matches: every key whose role is not OUTPUT (unknown keys included)."""
    return {k: v for k, v in (params or {}).items() if PARAM_ROLES.get(k) != OUTPUT}


def _file_kinds(rule: dict):
    kinds = rule.get("file_kinds")
    return set(kinds) if kinds else None  # None means every file kind


def _overlap(a: dict, b: dict) -> bool:
    ka, kb_ = _file_kinds(a), _file_kinds(b)
    return ka is None or kb_ is None or bool(ka & kb_)


def _error(code: str, pointer: str, message: str, severity: str = "ERROR") -> Finding:
    return Finding(code, RULES_FILE, pointer, message, severity)


def _a001(rows: list) -> list:
    seen = set()
    out = []
    for row in rows:
        if row["id"] in seen:
            out.append(_error("A001", row["id"], f"duplicate rule id {row['id']}"))
        seen.add(row["id"])
    return out


def _a002_pairs(active: list) -> set:
    """Index pairs (earlier, later) of active rules with the same step, detector and canonical params."""
    pairs = set()
    groups = defaultdict(list)
    for index, row in enumerate(active):
        if row.get("detector_ref"):
            groups[(row.get("step"), row["detector_ref"], _params_key(row.get("params")))].append(index)
    for members in groups.values():
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                pairs.add((first, second))
    return pairs


def _a002(active: list, pairs: set) -> list:
    out = []
    for first, second in sorted(pairs, key=lambda p: (p[1], p[0])):
        a, b = active[first], active[second]
        out.append(_error("A002", b["id"], f"{b['id']} repeats {a['id']} (same step, detector and params)"))
    return out


def _a005(active: list, a002_pairs: set) -> list:
    """Overlapping rules with the same step, detector and selector (pairs with identical params are A002).

    ERROR only when both rules are FIX_ENABLED (possible double edit); otherwise WARNING (duplicate reporting).
    """
    # Rules that can collide share step, detector and selector: group them once (one key per rule, not per pair) and
    # visit only the pairs inside a group. Findings come out in the order of the all-pairs scan: by later rule, then
    # by earlier rule.
    groups = defaultdict(list)
    for index, row in enumerate(active):
        if row.get("detector_ref"):
            groups[(row.get("step"), row["detector_ref"], _params_key(selector_params(row.get("params"))))].append(index)
    pairs = []
    for members in groups.values():
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                if (first, second) in a002_pairs or not _overlap(active[first], active[second]):
                    continue
                pairs.append((second, first))
    out = []
    for second, first in sorted(pairs):
        a, b = active[first], active[second]
        both_fix = a.get("maturity") == FIX_ENABLED and b.get("maturity") == FIX_ENABLED
        severity = "ERROR" if both_fix else "WARNING"
        out.append(_error("A005", b["id"],
                          f"{b['id']} and {a['id']} match the same selector and may edit the same files "
                          f"(same step and detector)", severity))
    return out


def _a003(rows: list, ids: set) -> list:
    out = []
    for row in rows:
        for field in ("conflicts_with", "depends_on"):
            for ref in row.get(field, []) or []:
                if ref not in ids:
                    out.append(_error("A003", row["id"], f"{row['id']}: {field} names unknown rule {ref}"))
    return out


def _a004(rows: list, ids: set) -> list:
    graph = {r["id"]: [d for d in (r.get("depends_on") or []) if d in ids] for r in rows}
    state = {}  # node -> 1 (on stack) or 2 (done)
    stack = []
    cycles = []

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif nxt not in state:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for node in graph:
        if node not in state:
            visit(node)
    out = []
    reported = set()
    for cycle in cycles:
        key = frozenset(cycle)
        if key in reported:
            continue
        reported.add(key)
        out.append(_error("A004", cycle[0], f"depends_on cycle: {' -> '.join(cycle)}"))
    return out


def _a006(rows: list, evidence: dict) -> list:
    out = []
    for row in rows:
        for ref in row.get("evidence", []) or []:
            if ref not in evidence:
                out.append(_error("A006", row["id"], f"{row['id']} references unknown evidence {ref}"))
    return out


def check_authoring(kb: KnowledgeBase) -> list:
    """All A-codes for the tree, ungated."""
    rows = _rows(kb)
    ids = {r["id"] for r in rows}
    active = _active(rows)
    a002 = _a002_pairs(active)
    out = _a001(rows) + _a002(active, a002) + _a005(active, a002)
    out += _a003(rows, ids) + _a004(rows, ids) + _a006(rows, kb.evidence)
    return out


def authoring_findings(kb: KnowledgeBase, *, strict_builtin: bool = False) -> list:
    """Gated entry point used by knowledge/checks.py: skipped for the built-in tree unless `strict_builtin`."""
    if is_builtin_tree(kb) and not strict_builtin:
        return []
    return check_authoring(kb)
