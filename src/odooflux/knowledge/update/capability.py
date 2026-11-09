"""Capability comparison between two knowledge releases (feature 012, plan addendum C3).

A rule's *capability* is what the release lets the engine do with that rule: its id, maturity, detector and fixer
references with their parameters, and the scope fields that decide where it applies. Rows are read through the same
loader used for releases (`loader.load_knowledge` on `<release>/knowledge`), so the view here matches what a loaded
release executes.

Executable field set (the row schema in `schemas/rule_metadata.schema.json`):
- `maturity` (DRAFT < DETECT_ONLY < FIX_ENABLED; RETIRED sits below DRAFT and is an explicit retirement)
- `detector_ref`, `detector_params`, `fixer_ref`, `fixer_params`. The schema has one shared `params` object that both
  references read, so both params fields carry the same value and a `params` edit reports both field names.
- scope: `step`, `file_kinds`, `depends_on`, `conflicts_with`, `validation`, `not_applicable_reason`
- execution gates: `risk`, `ai_eligible`

Not compared (descriptive only): `category`, `severity`, `evidence`, `tests`, `message`, `suggestion`, `legacy_ref`,
`origin`, `rev`, `review_required`, `retired_reason`. Lists keep their row order, so a reordering counts as a change.

`exec_digest` is the sha256 of the canonical JSON of the id plus the executable fields. Equal digests mean the rule is
unchanged. Rules are compared by identity (id) and executable fields, never by counts.

`compare` returns a `CapabilityDiff`:
- `lost`: ids missing from the new release, or whose maturity became RETIRED (an explicit retirement counts as lost).
  A rule that was already RETIRED and is absent is not a loss.
- `downgraded`: `{id, from, to}` where the maturity rank went down.
- `changed`: `{id, fields}` for executable fields that differ. A downgrade's maturity difference is reported under
  `downgraded` and not repeated in `fields`. An upgrade reports `maturity` in `fields`.
- `added`: ids only in the new release. `unchanged`: count of ids with equal digests.

`prev_dir` None (no previous release, or the built-in tree only) means every new rule is `added`.
"""

from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.canonical import CanonicalError, digest_obj

DRAFT = "DRAFT"
DETECT_ONLY = "DETECT_ONLY"
FIX_ENABLED = "FIX_ENABLED"
RETIRED = "RETIRED"
MATURITY_RANK = {RETIRED: -1, DRAFT: 0, DETECT_ONLY: 1, FIX_ENABLED: 2}
EXEC_FIELDS = ("maturity", "detector_ref", "detector_params", "fixer_ref", "fixer_params", "step", "file_kinds",
               "depends_on", "conflicts_with", "validation", "not_applicable_reason", "ai_eligible", "risk")

# Stable problem codes (CapabilityError.code).
RULE_ROW_INVALID = "capability.rule_row_invalid"
DUPLICATE_RULE_ID = "capability.duplicate_rule_id"
UNKNOWN_MATURITY = "capability.unknown_maturity"
RULES_UNREADABLE = "capability.rules_unreadable"


class CapabilityError(ValueError):
    """A release's rule rows cannot be read as capabilities (fail closed). `code` is one of the constants above."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Capability:
    id: str
    maturity: str
    detector_ref: object
    detector_params: dict
    fixer_ref: object
    fixer_params: dict
    step: object
    file_kinds: tuple
    depends_on: tuple
    conflicts_with: tuple
    validation: tuple
    not_applicable_reason: object
    ai_eligible: object
    risk: object
    exec_digest: str


@dataclass(frozen=True)
class CapabilityDiff:
    lost: tuple = ()
    downgraded: tuple = ()
    changed: tuple = ()
    added: tuple = ()
    unchanged: int = 0

    def to_dict(self) -> dict:
        return {"lost": list(self.lost), "downgraded": [dict(entry) for entry in self.downgraded],
                "changed": [{"id": e["id"], "fields": list(e["fields"])} for e in self.changed],
                "added": list(self.added), "unchanged": self.unchanged}


def _tuple(value, rid: str, key: str) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise CapabilityError(RULE_ROW_INVALID, f"{rid}: {key} must be a list")
    return tuple(value)


def _params(row: dict, rid: str) -> dict:
    params = row.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise CapabilityError(RULE_ROW_INVALID, f"{rid}: params must be an object")
    return dict(params)


def _capability(row: dict) -> Capability:
    rid = row["id"]
    maturity = row.get("maturity")
    if maturity not in MATURITY_RANK:
        raise CapabilityError(UNKNOWN_MATURITY, f"{rid}: maturity {maturity!r} is not a known maturity")
    params = _params(row, rid)
    fields = {
        "id": rid,
        "maturity": maturity,
        "detector_ref": row.get("detector_ref"),
        "detector_params": params,
        "fixer_ref": row.get("fixer_ref"),
        "fixer_params": dict(params),
        "step": row.get("step"),
        "file_kinds": _tuple(row.get("file_kinds"), rid, "file_kinds"),
        "depends_on": _tuple(row.get("depends_on"), rid, "depends_on"),
        "conflicts_with": _tuple(row.get("conflicts_with"), rid, "conflicts_with"),
        "validation": _tuple(row.get("validation"), rid, "validation"),
        "not_applicable_reason": row.get("not_applicable_reason"),
        "ai_eligible": row.get("ai_eligible"),
        "risk": row.get("risk"),
    }
    try:
        digest = digest_obj({key: fields[key] for key in ("id",) + EXEC_FIELDS})
    except CanonicalError as exc:
        raise CapabilityError(RULE_ROW_INVALID, f"{rid}: not canonical JSON ({exc})") from None
    return Capability(exec_digest=digest, **fields)


def capabilities(release_dir) -> dict:
    """rule id -> Capability for the knowledge tree of `release_dir` (`<release_dir>/knowledge`).

    Raises CapabilityError for unreadable rule files, rows without a string id, duplicate ids and unknown maturities."""
    kb = load_knowledge(Path(release_dir) / "knowledge")
    errors = [f for f in kb.load_findings if f.severity == "ERROR"]
    if errors:
        raise CapabilityError(RULES_UNREADABLE, "; ".join(f"{f.file}: {f.message}" for f in errors))
    result = {}
    for row in kb.rules:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise CapabilityError(RULE_ROW_INVALID, "rule row without a string id")
        rid = row["id"]
        if rid in result:
            raise CapabilityError(DUPLICATE_RULE_ID, f"rule id {rid} appears more than once")
        result[rid] = _capability(row)
    return result


def _is_downgrade(old: str, new: str) -> bool:
    return MATURITY_RANK[new] < MATURITY_RANK[old]


def diff_capabilities(old: dict, new: dict) -> CapabilityDiff:
    """Compare two `capabilities()` maps. Pure; see the module docstring for the rules."""
    lost, downgraded, changed, added = [], [], [], []
    unchanged = 0
    for rid in sorted(set(old) | set(new)):
        before, after = old.get(rid), new.get(rid)
        if before is None:
            added.append(rid)
            continue
        if after is None:
            if before.maturity != RETIRED:
                lost.append(rid)
            continue
        if after.maturity == RETIRED and before.maturity != RETIRED:
            lost.append(rid)
            continue
        if before.exec_digest == after.exec_digest:
            unchanged += 1
            continue
        down = _is_downgrade(before.maturity, after.maturity)
        if down:
            downgraded.append({"id": rid, "from": before.maturity, "to": after.maturity})
        fields = [name for name in EXEC_FIELDS
                  if getattr(before, name) != getattr(after, name) and not (down and name == "maturity")]
        if fields:
            changed.append({"id": rid, "fields": fields})
    return CapabilityDiff(lost=tuple(lost), downgraded=tuple(downgraded), changed=tuple(changed),
                          added=tuple(added), unchanged=unchanged)


def compare(prev_dir, new_dir) -> CapabilityDiff:
    """Capability diff from the previous release to the new one. `prev_dir` None means no previous capabilities."""
    old = {} if prev_dir is None else capabilities(prev_dir)
    return diff_capabilities(old, capabilities(new_dir))


# --- semantic supersede policy (feature 012, Wave 3c, owner decision A) ---------------------------------------------

POLICY_NAME = "semantic-replacement/1"  # recorded in the plan fingerprint and the audit trail; bump on any rule change
GENERATED_ORIGIN = "GENERATED"
SEMANTIC_FIELDS = tuple(name for name in EXEC_FIELDS if name != "maturity")  # maturity is judged by rank, not equality


def _rule_rows(release_dir) -> dict:
    """id -> raw rule row of `<release_dir>/knowledge`, read through the loader like `capabilities`."""
    kb = load_knowledge(Path(release_dir) / "knowledge")
    return {row["id"]: row for row in kb.rules if isinstance(row, dict) and isinstance(row.get("id"), str)}


def _semantic_key(cap: Capability, row: dict) -> tuple:
    """What a rule does, without its id, its maturity and its descriptive text. `category` is compared here (the owner
    rule names it), though `Capability` does not carry it."""
    return tuple(getattr(cap, name) for name in SEMANTIC_FIELDS) + (row.get("category"),)


def _plan_replacements(prev_dir, new_dir) -> tuple:
    """``({removed_rule_id: replacement_id}, parent_rows)``. A removed rule is replaced only by a rule of the new release
    with equal semantics and a maturity rank at least its own; each replacement serves at most one removed rule, and the
    removed rules are matched in sorted id order. Only GENERATED, non-RETIRED rows qualify."""
    old_caps, new_caps = capabilities(prev_dir), capabilities(new_dir)
    old_rows, new_rows = _rule_rows(prev_dir), _rule_rows(new_dir)
    removed = sorted(rid for rid in old_caps if rid not in new_caps)
    removed_set = set(removed)
    mapping, claimed = {}, set()
    for rid in removed:
        before, row = old_caps[rid], old_rows[rid]
        if row.get("origin") != GENERATED_ORIGIN or before.maturity == RETIRED:
            continue
        key = _semantic_key(before, row)
        for candidate in sorted(new_caps):
            if candidate in removed_set or candidate in claimed:
                continue
            if MATURITY_RANK[new_caps[candidate].maturity] < MATURITY_RANK[before.maturity]:
                continue
            if _semantic_key(new_caps[candidate], new_rows[candidate]) != key:
                continue
            mapping[rid] = candidate
            claimed.add(candidate)
            break
    return mapping, old_rows


def semantic_replacements(prev_dir, new_dir) -> dict:
    """removed rule id -> replacement rule id, for every removed GENERATED rule that the new release replaces with an
    equal-semantics rule (see `_plan_replacements`). Removed MANUAL or BUILTIN rules, and rules without a replacement, are
    absent. Raises CapabilityError when a release cannot be read."""
    return _plan_replacements(prev_dir, new_dir)[0]


def semantic_supersede_policy():
    """A supersede policy for `pipeline.BuildPlan.supersede_policy`: callable(diff, parent_dir, new_release_dir) returning
    {id: reason} for every destructive id it approves. Rules: `semantic_replacements`. A removed VERIFIED evidence record
    is approved only when it is cited by at least one parent rule and every citing parent rule is approved as a rule.
    An unreadable release approves nothing (fail closed: the build then stops as it does without a policy)."""

    def policy(diff, parent_dir, new_release_dir) -> dict:
        try:
            mapping, parent_rows = _plan_replacements(parent_dir, new_release_dir)
        except CapabilityError:
            return {}
        approved = {rid: f"semantic replacement by {replacement}" for rid, replacement in mapping.items()}
        for entry in diff.entries:
            if entry.get("family") != "evidence" or entry.get("change") != "REMOVED" or not entry.get("destructive"):
                continue
            evidence_id = entry["id"]
            citing = sorted(rid for rid, row in parent_rows.items() if evidence_id in (row.get("evidence") or []))
            if citing and all(rid in mapping for rid in citing):
                approved[evidence_id] = f"evidence of replaced rule(s) {', '.join(citing)}"
        return approved

    policy.policy_name = POLICY_NAME
    return policy
