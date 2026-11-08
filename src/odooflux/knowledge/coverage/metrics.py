"""Eight coverage metrics (REQ-KAP-032; coverage-and-gates contract; data-model M1..M8).

Each metric has its own explicit numerator and denominator and is reported separately. A zero denominator gives
NOT_APPLICABLE with no per-mille value (never 100 percent). There is no blended score. Percentages are display only:
`per_mille` is an integer (integer division), and `format_line` always prints the fraction first.

Inputs (plain dicts, see `compute_metrics`). File accounting documents are `FileAccounting.document()` outputs.
"""

from odooflux.knowledge.extract.accounting import STATES

__all__ = ["compute_metrics", "format_line", "METRIC_IDS", "MEASURED", "NOT_APPLICABLE", "DEFINITIONS"]

MEASURED = "MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
METRIC_IDS = tuple(f"M{i}" for i in range(1, 9))
EVIDENCE_DISPOSITIONS = ("RULE_CREATED", "EXISTING_RULE_LINKED", "DETECTION_ONLY")
BUILTIN_ORIGINS = (None, "BUILTIN")
FIX_ENABLED = "FIX_ENABLED"

DEFINITIONS = {
    "M1": ("source_retrieval", "required sources VERIFIED / required sources declared"),
    "M2": ("file_scan", "changed files ANALYZED / all changed files of the pairs (sum of file states)"),
    "M3": ("change_classification", "changes with class not UNKNOWN / all changes"),
    "M4": ("change_disposition", "changes with disposition not UNRESOLVED / all changes"),
    "M5": ("evidence", "changes needing evidence with a valid EvidenceRecord / changes needing evidence"),
    "M6": ("rule_validation", "release rules new or changed, passing validation / release rules new or changed"),
    "M7": ("fix_verification", "FIX_ENABLED rules passing G-SAFE / FIX_ENABLED rules (built-in rows excluded)"),
    "M8": ("version_transition", "declared transitions with verified sources, complete accounting and a ledger / "
                                 "declared transitions"),
}


def _metric(metric_id: str, numerator: int, denominator: int, breakdown=None) -> dict:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError(f"{metric_id}: invalid counts {numerator}/{denominator}")
    name, definition = DEFINITIONS[metric_id]
    if denominator == 0:
        status, per_mille = NOT_APPLICABLE, None
    else:
        status, per_mille = MEASURED, numerator * 1000 // denominator
    return {"id": metric_id, "name": name, "numerator": numerator, "denominator": denominator, "status": status,
            "denominator_definition": definition, "per_mille": per_mille, "breakdown": dict(breakdown or {})}


def _state_counts(accounting: list) -> dict:
    counts = {state: 0 for state in STATES}
    for doc in accounting:
        for item in doc.get("files", []):
            counts[item["state"]] += 1
    return counts


def compute_metrics(inputs: dict) -> list:
    """Return the eight metric records M1..M8, in order. Keys read from `inputs` (missing keys count as empty):

    sources: [{source_id, required, status}]
    accounting: [FileAccounting document]
    changes: [{change_id, class, disposition, disposition_data: {evidence_ids}}]
    valid_evidence_ids: [evidence id]
    release_rules: [{id, in_release_delta, validation_passed, origin, maturity, safety_passed}]
    declared_transitions: [{step, sources_verified, accounting_complete, ledger_present}]
    """
    sources = inputs.get("sources", [])
    required = [s for s in sources if s.get("required")]
    m1 = _metric("M1", sum(1 for s in required if s.get("status") == "VERIFIED"), len(required))

    counts = _state_counts(inputs.get("accounting", []))
    m2 = _metric("M2", counts["ANALYZED"], sum(counts.values()), {
        "excluded": counts["EXCLUDED"], "unsupported": counts["UNSUPPORTED"], "failed": counts["FAILED"],
        "pending": counts["PENDING"]})

    changes = inputs.get("changes", [])
    m3 = _metric("M3", sum(1 for c in changes if c.get("class") != "UNKNOWN"), len(changes))
    m4 = _metric("M4", sum(1 for c in changes if c.get("disposition") != "UNRESOLVED"), len(changes))

    valid = set(inputs.get("valid_evidence_ids", []))
    needing = [c for c in changes if c.get("disposition") in EVIDENCE_DISPOSITIONS]
    covered = [c for c in needing
               if any(eid in valid for eid in c.get("disposition_data", {}).get("evidence_ids", []))]
    m5 = _metric("M5", len(covered), len(needing))

    rules = inputs.get("release_rules", [])
    delta = [r for r in rules if r.get("in_release_delta")]
    m6 = _metric("M6", sum(1 for r in delta if r.get("validation_passed")), len(delta))

    fix = [r for r in rules if r.get("maturity") == FIX_ENABLED and r.get("origin") not in BUILTIN_ORIGINS]
    grandfathered = [r for r in rules if r.get("maturity") == FIX_ENABLED and r.get("origin") in BUILTIN_ORIGINS]
    m7 = _metric("M7", sum(1 for r in fix if r.get("safety_passed")), len(fix),
                 {"builtin_grandfathered": len(grandfathered)})

    transitions = inputs.get("declared_transitions", [])
    complete = [t for t in transitions
                if t.get("sources_verified") and t.get("accounting_complete") and t.get("ledger_present")]
    m8 = _metric("M8", len(complete), len(transitions))

    return [m1, m2, m3, m4, m5, m6, m7, m8]


def format_line(item: dict) -> str:
    """One display line. The fraction comes first; the percentage is display only."""
    name = item["name"]
    if item["status"] == NOT_APPLICABLE:
        return f"{item['id']} {name}  NOT_APPLICABLE  (denominator 0: {item['denominator_definition']})"
    per_mille = item["per_mille"]
    percent = f"{per_mille // 10}.{per_mille % 10}%"
    line = f"{item['id']} {name}  {item['numerator']}/{item['denominator']}  ({percent})  " \
           f"[{item['denominator_definition']}]"
    if item["breakdown"]:
        line += "  " + " ".join(f"{key}={value}" for key, value in item["breakdown"].items())
    return line
