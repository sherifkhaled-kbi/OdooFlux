"""Disposition rules, confirm and merge (REQ-KAP-014, REQ-KAP-012, REQ-KAP-031, REQ-KAP-030; change-ledger contract
rules 2, 4, 5, 6).

Functions take a `Ledger` (`ledger/ledger.py`) and use only its public API (`get`, `records`, `mutate`, `unresolved`,
constructor). Every change goes through `Ledger.mutate`, so each one is schema-checked and chained into history.

- `set_disposition`: NO_CUSTOM_MODULE_IMPACT and HUMAN_REVIEW need a non-empty rationale (moving back to UNRESOLVED
  needs one too). RULE_CREATED and EXISTING_RULE_LINKED need rule ids; every id must exist in `known_rules` (the tree
  being built). DETECTION_ONLY needs a rule with maturity DETECT_ONLY. An AI actor may only set HUMAN_REVIEW.
- `confirm`: only for RENAMED_CANDIDATE and REPLACEMENT_CANDIDATE, only by actor MANUAL, once.
- `merge(new, previous)`: returns `(merged_ledger, report)`. Previous records keep disposition, history and
  disposition_data byte for byte; only locations and detail follow the new build. Manual dispositions are never
  overwritten; a different proposal goes to `conflicts`. A class change is a conflict too (the previous class is kept).
  Ids only in the previous ledger are carried as `stale`, never deleted.

Note: the contract names `Ledger.merge`; it is provided here as `merge(new, previous)` because this task owns only
this file. The behaviour is the same.
"""

import copy

from odooflux.knowledge.ledger.ledger import INITIAL_DISPOSITION, Ledger, LedgerError

__all__ = ["DISPOSITIONS", "DispositionError", "set_disposition", "confirm", "merge", "AI_ACTORS", "CONFIRMABLE"]

DISPOSITIONS = ("RULE_CREATED", "EXISTING_RULE_LINKED", "NO_CUSTOM_MODULE_IMPACT", "DETECTION_ONLY",
                "HUMAN_REVIEW", "UNSUPPORTED", "UNRESOLVED")
RATIONALE_REQUIRED = ("NO_CUSTOM_MODULE_IMPACT", "HUMAN_REVIEW")
RULE_REQUIRED = ("RULE_CREATED", "EXISTING_RULE_LINKED")
AI_ACTORS = ("AI", "AI_PROPOSED")
AI_ALLOWED = ("HUMAN_REVIEW",)
CONFIRMABLE = ("RENAMED_CANDIDATE", "REPLACEMENT_CANDIDATE")
MANUAL = "MANUAL"


class DispositionError(LedgerError):
    """A disposition, confirm or merge input was refused."""


def set_disposition(ledger: Ledger, change_id: str, disposition: str, *, actor: str, rationale=None,
                    rule_ids=(), evidence_ids=(), known_rules=None, reviewer=None) -> dict:
    """Set one change's disposition. `known_rules` maps rule id to maturity for the tree being built."""
    if disposition not in DISPOSITIONS:
        raise DispositionError(f"unknown disposition {disposition!r}")
    if not actor:
        raise DispositionError("actor is required")
    current = ledger.get(change_id)
    text = rationale.strip() if isinstance(rationale, str) else None
    if disposition in RATIONALE_REQUIRED and not text:
        raise DispositionError(f"{disposition} needs a non-empty rationale")
    if disposition == INITIAL_DISPOSITION and not text:
        raise DispositionError("moving back to UNRESOLVED needs a reason")
    if actor in AI_ACTORS and disposition not in AI_ALLOWED:
        raise DispositionError(f"AI may only set {AI_ALLOWED}, not {disposition}")
    rules = dict(known_rules or {})
    rule_list = sorted(set(rule_ids))
    unknown = [r for r in rule_list if r not in rules]
    if unknown:
        raise DispositionError(f"rule ids not present in the tree: {unknown}")
    if disposition in RULE_REQUIRED and not rule_list:
        raise DispositionError(f"{disposition} needs at least one existing rule id")
    if disposition == "DETECTION_ONLY" and not any(rules[r] == "DETECT_ONLY" for r in rule_list):
        raise DispositionError("DETECTION_ONLY needs a rule with maturity DETECT_ONLY")
    update = {
        "disposition": disposition,
        "disposition_data": {
            "rule_ids": rule_list,
            "evidence_ids": sorted(set(evidence_ids)),
            "rationale": text or None,
            "reviewer": reviewer or actor,
            "decided_at": ledger.clock(),
        },
    }
    if actor == MANUAL:
        update["proposed_by"] = MANUAL
    ledger.mutate(change_id, actor=actor, action="set_disposition", from_value=current["disposition"],
                  to_value=disposition, update=update)
    return ledger.get(change_id)


def confirm(ledger: Ledger, change_id: str, *, actor: str) -> dict:
    """Confirm a rename or replacement candidate. Manual actors only; AI and automatic actors are refused."""
    if actor != MANUAL:
        raise DispositionError(f"confirm is a manual action, refused for actor {actor!r}")
    current = ledger.get(change_id)
    if current["class"] not in CONFIRMABLE:
        raise DispositionError(f"{current['class']} cannot be confirmed; only {CONFIRMABLE}")
    if current["confirmed"]:
        raise DispositionError("change is already confirmed")
    ledger.mutate(change_id, actor=actor, action="confirm", from_value="unconfirmed", to_value="confirmed",
                  update={"confirmed": True})
    return ledger.get(change_id)


def merge(new: Ledger, previous: Ledger):
    """Merge a fresh build into the previous ledger. Returns `(merged Ledger, report)`; inputs are not mutated."""
    prev = {r["change_id"]: r for r in previous.records()}
    fresh = {r["change_id"]: r for r in new.records()}
    report = {"added": [], "kept": [], "stale": [], "conflicts": []}
    merged: dict = {}
    for cid in sorted(set(prev) | set(fresh)):
        if cid not in fresh:
            merged[cid] = copy.deepcopy(prev[cid])
            report["stale"].append(cid)
            continue
        if cid not in prev:
            merged[cid] = copy.deepcopy(fresh[cid])
            report["added"].append(cid)
            continue
        old, draft = prev[cid], fresh[cid]
        record = copy.deepcopy(old)
        record["locations"] = copy.deepcopy(draft["locations"])
        record["detail"] = copy.deepcopy(draft["detail"])
        if draft["class"] != old["class"]:
            report["conflicts"].append({"change_id": cid, "kind": "CLASS_CHANGED", "kept": old["class"],
                                        "proposed": draft["class"]})
        if old["proposed_by"] == MANUAL and draft["disposition"] != old["disposition"]:
            report["conflicts"].append({"change_id": cid, "kind": "DISPOSITION", "kept": old["disposition"],
                                        "proposed": draft["disposition"], "proposed_by": draft["proposed_by"]})
        merged[cid] = record
        report["kept"].append(cid)
    result = Ledger(new.step, new.from_id, new.to_id, merged, clock=new.clock)
    report["findings"] = result.verify()
    return result, report
