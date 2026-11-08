"""Candidate rule generation (feature 011, REQ-KAP-016, REQ-KAP-014; contract candidate-rule-generation steps 1 to 7).

`generate` is pure: it reads a Ledger and the existing rule rows under `tree_root`, and returns a result dict. It does
not write files and does not mutate the ledger. `apply_dispositions` then records the proposed dispositions through
`ledger/dispositions.set_disposition`.

Per ledger change (sorted by change_id):
- a change already RULE_CREATED or EXISTING_RULE_LINKED is skipped;
- no matching template: skipped, and no evidence is invented;
- a change whose candidate id already exists in the candidate store (any status: PROPOSED, CONFLICT, ACCEPTED or
  REJECTED) is skipped entirely: no candidate, no evidence, no disposition. It is listed under `existing`, and the
  stored record is never rewritten, reset or resurrected;
- an existing rule with the same step, detector_ref and params is linked (EXISTING_RULE_LINKED), not duplicated;
- otherwise a DRAFT candidate is built with one new EvidenceRecord. Candidates never carry a fixer_ref. An unconfirmed
  rename or replacement candidate is HUMAN_REVIEW and never names a replacement. Evidence from an unofficial source
  makes the rule review_required and labels it supplementary in `message`.
- a candidate colliding with a MANUAL rule is kept as CONFLICT by `authoring/conflicts.plan_build` (manual wins).

Output ordering and ids are deterministic: two runs over the same ledger and tree are byte-identical.
Acceptance (PROPOSED -> ACCEPTED) is not done here (T059).
"""

import json
import re
from pathlib import Path

from odooflux.knowledge.authoring import conflicts as cf
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates.templates import build_skeleton, load_templates, select_template
from odooflux.knowledge.ledger import dispositions as dsp

__all__ = ["GeneratorError", "ACTOR", "generate", "apply_dispositions", "read_rule_rows"]

ACTOR = "KAP_GENERATOR"
DISPOSED = ("RULE_CREATED", "EXISTING_RULE_LINKED")
UNCONFIRMED_CLASSES = ("RENAMED_CANDIDATE", "REPLACEMENT_CANDIDATE", "UNKNOWN")
CANDIDATE_MATURITY = "DRAFT"
SUPPLEMENTARY = "Supplementary (unofficial source {sid}, not authoritative): "
DETECTION_METHOD = "KAP deterministic: ledger change classified and matched to extraction template {tid}"
TRANSFORMATION = "none; review only, no edit is proposed"
_EV_ID = re.compile(r"^EV-\d{3}$")


class GeneratorError(ValueError):
    """Generation was given an input it cannot honour."""


def read_rule_rows(tree_root) -> list:
    """Every rule row under `tree_root/compatibility/*.rules.json`, in file order."""
    rows = []
    compat = Path(tree_root) / "compatibility"
    for path in sorted(compat.glob("*.rules.json")) if compat.is_dir() else []:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(row for row in data if isinstance(row, dict))
    return rows


def _params_key(params) -> str:
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"))


def _find_equivalent(rows: list, rule: dict):
    """The first non-retired rule with the same step, detector_ref and params, or None."""
    for row in rows:
        if row.get("maturity") == "RETIRED" or row.get("step") != rule["step"]:
            continue
        if row.get("detector_ref") == rule["detector_ref"] and _params_key(row.get("params")) == _params_key(
                rule["params"]):
            return row
    return None


def _disposition(change_id, disposition, *, rule_ids=(), evidence_ids=(), rationale=None) -> dict:
    return {"change_id": change_id, "disposition": disposition, "rule_ids": sorted(rule_ids),
            "evidence_ids": sorted(evidence_ids), "rationale": rationale}


def _stored_candidates(tree_root) -> dict:
    """Every `candidates/CR-*.json` record, keyed by its file stem (the candidate id). Empty when there is no store."""
    store = Path(tree_root) / "candidates"
    if not store.is_dir():
        return {}
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(store.glob("CR-*.json"))}


def _store_evidence_ids(tree_root, stored=None) -> set:
    """EV ids held by the candidate store: `candidates/evidence/*.json` file names (rejected ones included) and the
    evidence ids cited by every `candidates/CR-*.json` record. Empty when the store does not exist."""
    store = Path(tree_root) / "candidates"
    if not store.is_dir():
        return set()
    held = set()
    folder = store / "evidence"
    if folder.is_dir():
        held.update(path.stem for path in folder.glob("EV-*.json") if _EV_ID.match(path.stem))
    for record in (_stored_candidates(tree_root) if stored is None else stored).values():
        cited = (record.get("rule") or {}).get("evidence") or []
        held.update(ev_id for ev_id in cited if isinstance(ev_id, str) and _EV_ID.match(ev_id))
    return held


def generate(ledger, *, tree_root, source: dict, checked_on: str, templates=None, known_detectors=None,
             checked_by: str = eb.CHECKER, reserved_ids=()) -> dict:
    """Candidates, evidence, links and proposed dispositions for `ledger`. See the module docstring.

    `source` describes the source the ledger was built from: source_id, official, url, repository, revision, branch.
    New evidence ids skip every id in the tree evidence dir, the candidate store (all statuses), the ledger and
    `reserved_ids`, so an id is never reused. A change whose candidate id already exists in the store (any status) is
    skipped and listed under `existing` as {candidate_id, status, change_id}; nothing about it is written or changed.
    Returns a dict with keys candidates, evidence, linked, dispositions, skipped, conflicts, existing,
    detectors_verified."""
    templates = load_templates(known_detectors=known_detectors) if templates is None else templates
    verified = getattr(templates, "detectors_verified", False) is True  # False: never verified, see accept
    rows = read_rule_rows(tree_root)
    records = ledger.records()
    stored = _stored_candidates(tree_root)
    used = eb.used_evidence_ids(tree_root, records) | _store_evidence_ids(tree_root, stored) | set(reserved_ids)
    result = {"candidates": [], "evidence": [], "linked": [], "dispositions": [], "skipped": [], "conflicts": [],
              "existing": [], "detectors_verified": verified}
    built = []
    for change in records:
        cid = change["change_id"]
        if change["disposition"] in DISPOSED:
            result["skipped"].append({"change_id": cid, "reason": "ALREADY_DISPOSED"})
            continue
        template = select_template(change, templates)
        if template is None:
            result["skipped"].append({"change_id": cid, "reason": "NO_TEMPLATE"})
            continue
        confirmed = change.get("confirmed") is True
        build_from = template if confirmed or not template.get("replacement_suggestion") else {
            **template, "replacement_suggestion": False}
        versions = eb._applicability(change["step"])
        skeleton = build_skeleton(build_from, change, known_detectors=known_detectors,
                                  ledger_entry=change if confirmed else None,
                                  applicability={"source_versions": [versions["from"]],
                                                 "target_versions": [versions["to"]]})
        held = stored.get(skeleton["candidate_id"])
        if held is not None:
            result["existing"].append({"candidate_id": skeleton["candidate_id"], "status": held.get("status"),
                                       "change_id": held.get("change_id", cid)})
            continue
        rule = skeleton["rule"]
        rule["maturity"] = CANDIDATE_MATURITY
        unconfirmed = change["class"] in UNCONFIRMED_CLASSES and not confirmed
        link = None if unconfirmed else _find_equivalent(rows, rule)
        rule_ids = [link["id"]] if link else [rule["id"]]
        ev_id = eb.next_evidence_id(used)
        used.add(ev_id)
        evidence = eb.build_evidence(
            change, evidence_id=ev_id, rule_ids=rule_ids, source=source, risk=rule["risk"],
            detection_method=DETECTION_METHOD.format(tid=template["template_id"]),
            proposed_transformation=TRANSFORMATION, checked_on=checked_on, checked_by=checked_by)
        result["evidence"].append(evidence)
        if link:
            result["linked"].append({"change_id": cid, "rule_ids": [link["id"]], "evidence_ids": [ev_id]})
            result["dispositions"].append(_disposition(cid, "EXISTING_RULE_LINKED", rule_ids=[link["id"]],
                                                       evidence_ids=[ev_id]))
            continue
        rule["evidence"] = [ev_id]
        if not source.get("official"):
            rule["review_required"] = True
            rule["message"] = SUPPLEMENTARY.format(sid=source["source_id"]) + rule["message"]
        if unconfirmed:
            rule["review_required"] = True
            result["dispositions"].append(_disposition(
                cid, "HUMAN_REVIEW", evidence_ids=[ev_id],
                rationale=f"Unconfirmed {change['class']} candidate for {change['subject_key']}; "
                          "review before any mapping is considered."))
        skeleton["detectors_verified"] = verified
        built.append(skeleton)
    plan = cf.plan_build(rows, built)
    result["candidates"] = sorted(plan["candidates"], key=lambda c: c["candidate_id"])
    result["conflicts"] = plan["conflicts"]
    result["evidence"].sort(key=lambda e: e["id"])
    result["dispositions"].sort(key=lambda d: d["change_id"])
    result["linked"].sort(key=lambda d: d["change_id"])
    result["skipped"].sort(key=lambda d: d["change_id"])
    result["existing"].sort(key=lambda d: (d["change_id"], d["candidate_id"]))
    return result


def apply_dispositions(ledger, result: dict, *, tree_root, actor: str = ACTOR):
    """Record the proposed dispositions of `result` on `ledger` through the disposition API. Returns the ledger."""
    known = {row["id"]: row.get("maturity") for row in read_rule_rows(tree_root) if isinstance(row.get("id"), str)}
    for item in result["dispositions"]:
        dsp.set_disposition(ledger, item["change_id"], item["disposition"], actor=actor,
                            rationale=item.get("rationale"), rule_ids=item["rule_ids"],
                            evidence_ids=item["evidence_ids"], known_rules=known)
    return ledger
