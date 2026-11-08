"""Candidate acceptance (feature 011, T059; contract candidate-rule-generation step 8, manual-rule-cli).

`accept` moves one PROPOSED candidate to ACCEPTED. It refuses (raising AcceptError, candidate status unchanged or
CONFLICT, nothing written) when:
- the candidate is not PROPOSED, or it carries a fixer or FIX_ENABLED maturity;
- its detectors were not verified (`detectors_verified` is not True): `detectors_unverified`;
- the candidate collides with an active MANUAL rule (authoring/conflicts.detect; the manual rule wins);
- its evidence is missing or does not match the evidence schema;
- the ledger disposition already settled the change, or the rule id exists.

Otherwise it writes the evidence records, then the rule through `authoring/ops.create_rule` with origin GENERATED and
the candidate id as provenance (ops runs the schema and A001..A006 checks on the tree after the write and rolls back
on a fresh error). The ledger change gets disposition RULE_CREATED. The disposition is first dry-run on a copy of
the ledger so a refusal there also writes nothing. Pure stdlib.

Named rule tests: generated skeletons carry no test fixtures (`tests` is empty), so there is nothing extra to run
beyond the checks above; the rule must still pass ops validation.
"""

import copy
import json
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.authoring import conflicts as cf
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.ledger import dispositions as dsp
from odooflux.knowledge.ledger.ledger import LedgerError
from odooflux.knowledge.release.canonical import write_json_file

__all__ = ["AcceptError", "accept"]

ACCEPTABLE_MATURITY = ("DRAFT", "DETECT_ONLY")
SETTLED = ("RULE_CREATED", "EXISTING_RULE_LINKED")


class AcceptError(ValueError):
    """The candidate cannot be accepted. Nothing was written."""


def _evidence_by_id(records) -> dict:
    by_id = {}
    for record in records:
        if record.get("id") in by_id:
            raise AcceptError(f"duplicate evidence record {record.get('id')}")
        by_id[record.get("id")] = record
    return by_id


def accept(tree, candidate: dict, *, ledger, evidence, author=None, at=None) -> dict:
    """Accept `candidate` into `tree` (a knowledge tree) and record RULE_CREATED on `ledger`.

    `evidence` is the list of EvidenceRecords the candidate cites (generator result["evidence"]). On success the
    candidate's status becomes ACCEPTED and a summary dict is returned."""
    tree = Path(tree)
    if candidate.get("status") != "PROPOSED":
        raise AcceptError(f"candidate is {candidate.get('status')}; only PROPOSED candidates are accepted")
    if candidate.get("detectors_verified") is not True:
        raise AcceptError("detectors_unverified: the candidate's detector_ref was not checked against the bindable "
                          "detector table; regenerate it from verified templates")
    rule = candidate["rule"]
    if rule.get("fixer_ref") is not None or rule.get("maturity") == "FIX_ENABLED":
        raise AcceptError("a candidate never carries a fixer or FIX_ENABLED maturity")
    if rule.get("maturity") not in ACCEPTABLE_MATURITY:
        raise AcceptError(f"candidate maturity {rule.get('maturity')!r} is not acceptable")
    found = cf.detect(gen.read_rule_rows(tree), rule)
    if found:
        candidate["status"] = "CONFLICT"
        candidate["conflicts"] = found
        raise AcceptError(f"collides with MANUAL rule(s) {[f['with'] for f in found]}; manual wins by default")
    ev_ids = list(rule.get("evidence") or [])
    if not ev_ids:
        raise AcceptError("a candidate needs at least one evidence record")
    by_id = _evidence_by_id(evidence)
    schema = json.loads(eb.SCHEMA_PATH.read_text(encoding="utf-8"))
    for ev_id in ev_ids:
        record = by_id.get(ev_id)
        if record is None:
            raise AcceptError(f"evidence {ev_id} is not supplied")
        problems = v.check(record, schema)
        if problems:
            raise AcceptError(f"evidence {ev_id} fails the schema: {problems[:3]}")
    change_id = candidate["change_id"]
    try:
        current = ledger.get(change_id)
    except LedgerError as exc:
        raise AcceptError(str(exc)) from exc
    if current["disposition"] in SETTLED:
        raise AcceptError(f"change {change_id} is already {current['disposition']}")
    rule_id = rule["id"]
    if any(row.get("id") == rule_id for row in gen.read_rule_rows(tree)):
        raise AcceptError(f"rule {rule_id} already exists")
    actor = ops.resolve_author(author)
    when = at or ops._now()
    known = {rule_id: rule["maturity"]}
    # Dry run of the disposition on a copy, so a refusal there writes nothing.
    dsp.set_disposition(copy.deepcopy(ledger), change_id, "RULE_CREATED", actor=actor, rule_ids=[rule_id],
                        evidence_ids=ev_ids, known_rules=known)
    written = []
    try:
        for ev_id in ev_ids:
            path = tree / "evidence" / f"{ev_id}.json"
            if path.exists():
                raise AcceptError(f"evidence file {ev_id}.json already exists; ids are never reused")
            write_json_file(path, by_id[ev_id])
            written.append(path)
        ops.create_rule(tree, dict(rule), author=actor, at=when, origin="GENERATED", detectors_verified=True,
                        source_candidate=candidate["candidate_id"])
    except AcceptError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        for path in written:
            path.unlink(missing_ok=True)
        raise AcceptError(str(exc)) from exc
    dsp.set_disposition(ledger, change_id, "RULE_CREATED", actor=actor, rule_ids=[rule_id], evidence_ids=ev_ids,
                        known_rules=known)
    candidate["status"] = "ACCEPTED"
    return {"candidate_id": candidate["candidate_id"], "rule_id": rule_id, "evidence_ids": ev_ids,
            "status": "ACCEPTED"}
