"""Feature 012 addendum F2: machine confirmation records (`knowledge/update/machine_confirmation.py`). Stdlib unittest.

Synthetic pairs only. The record never confirms the ledger entry, and every field flip, resealed or not, must fail L1
(the record digest, the witness digest, the rule row, the evidence digests and the live proofs.py digest are all
recomputed). L2 rereads the blobs and must reproduce the witness digest byte for byte.
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from odooflux.knowledge.extract import proofs as P
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.update import machine_confirmation as mc

PATH = "odoo/tools/helpers.py"
V1 = b'''import math
def old_round(x, digits=0):
    """Old."""
    return math.floor(x * 10 ** digits) / 10 ** digits
'''
V2 = b'''import math
def new_round(x, digits=0):
    """Round.

    Replaces ``old_round``
    """
    return math.floor(x * 10 ** digits) / 10 ** digits
'''
RULE_ID = "1-1.python_orm.round-fix"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _side(snapshot, data):
    return {"source_id": "odoo-community", "snapshot_id": snapshot, "revision": "rev-1", "path": PATH,
            "blob_sha256": _sha(data), "data": data, "verified": True, "official": True, "pinned": True}


def _entry(cls="REPLACEMENT_CANDIDATE"):
    locations = {"REPLACEMENT_CANDIDATE": [("s1", V1, 2), ("s2", V2, 2)],
                 "BEHAVIOUR_CHANGED": [("s2", V2, 2)], "REMOVED": [("s1", V1, 2)]}[cls]
    detail = {"REPLACEMENT_CANDIDATE": {"from": "old_round", "to": "new_round", "source": "docs", "basis": "hint"}
              }.get(cls, {"basis": "body_digest"})
    return {"change_id": "CH-0123456789abcdef", "step": "16-17", "domain": "python_orm", "kind": "function",
            "subject_key": "tools.old_round", "class": cls, "detail": detail, "confirmed": False,
            "locations": [{"snapshot_id": s, "path": PATH, "line": line, "sha256": _sha(d)}
                          for s, d, line in locations],
            "disposition": "HUMAN_REVIEW", "proposed_by": "DETERMINISTIC",
            "history": [{"seq": 1, "at": "t", "actor": "DETERMINISTIC", "action": "create", "from": None,
                         "to": "HUMAN_REVIEW", "prev_hash": "0" * 64}]}


def _evidence(proof_data=V2):
    return {"id": "EV-001", "rule_ids": [RULE_ID], "official": True, "source_applicability": {"release": "16.0"},
            "target_applicability": {"release": "17.0"}, "locations": [{"content_sha256": _sha(proof_data)}]}


def _sides():
    return {"from": _side("s1", V1), "to": _side("s2", V2)}


def _attest(cls="REPLACEMENT_CANDIDATE", new="new_round", evidence=None, sides=None, entry=None):
    result = mc.prove(entry or _entry(cls), sides or _sides(), rule_id=RULE_ID,
                      evidence=[_evidence()] if evidence is None else evidence,
                      new=new if cls != "REMOVED" else None)
    return result


def _rule(attested):
    return {"id": RULE_ID, "params": attested.proof.derived_params, "evidence": ["EV-001"], "detector_ref": "d",
            "fixer_ref": "f", "maturity": "DETECT_ONLY", "review_required": True, "approval": None}


def _record():
    attested = _attest()
    return mc.build(attested, rule_row=_rule(attested)), _rule(attested), [_evidence()], _entry()


def _reseal(record):
    record = dict(record)
    record.pop("record_digest", None)
    record["record_digest"] = digest_obj(record)
    return record


class BuildAndVerify(unittest.TestCase):
    def test_positive_record_passes_l1_and_l2(self):
        record, rule, evidence, entry = _record()
        verdict = mc.verify(record, rule_row=rule, evidence_rows=evidence, ledger_entry=entry)
        self.assertTrue(verdict.ok, verdict.problems)
        self.assertEqual(verdict.derived_class, "REPLACEMENT_CONFIRMED")
        self.assertEqual(mc.derived_class(record, rule_row=rule, evidence_rows=evidence), "REPLACEMENT_CONFIRMED")
        sources = mc.verify_sources(record, {"from": V1, "to": V2})
        self.assertTrue(sources.ok, sources.problems)

    def test_build_is_deterministic(self):
        first, _, _, _ = _record()
        second, _, _, _ = _record()
        self.assertEqual(first["record_digest"], second["record_digest"])
        self.assertEqual(first["derived_params"], {"module": "odoo.tools.helpers", "old": "old_round",
                                                   "new": "new_round"})

    def test_record_never_confirms_and_holds_no_source_text(self):
        record, _, _, _ = _record()
        self.assertIs(record["ledger_entry"]["confirmed"], False)
        self.assertNotIn("floor", json.dumps(record))
        self.assertNotIn("Replaces", json.dumps(record))

    def test_s2_behaviour_changed_pair_builds(self):
        old = b"import warnings\ndef new_sum(a, b):\n    return a + b\ndef legacy(a, b):\n    return a + b\n"
        new = (b"import warnings\ndef new_sum(a, b):\n    return a + b\ndef legacy(a, b):\n"
               b"    warnings.warn('x', DeprecationWarning, stacklevel=2)\n    return new_sum(a, b)\n")
        entry = _entry("BEHAVIOUR_CHANGED")
        entry["subject_key"] = "tools.legacy"
        entry["locations"] = [{"snapshot_id": "s2", "path": PATH, "line": 4, "sha256": _sha(new)}]
        sides = {"from": _side("s1", old), "to": _side("s2", new)}
        evidence = [dict(_evidence(new), locations=[{"content_sha256": _sha(new)}])]
        attested = mc.prove(entry, sides, rule_id=RULE_ID, evidence=evidence, new="new_sum")
        self.assertIsInstance(attested, mc.Attested)
        record = mc.build(attested, rule_row=_rule(attested))
        self.assertEqual(record["derived_class"], "DELEGATING_ALIAS")
        self.assertTrue(mc.verify(record, rule_row=_rule(attested), evidence_rows=evidence,
                                  ledger_entry=entry).ok)

    def test_s3_removed_pair_builds(self):
        old = b"def multi(method):\n    return method\n"
        new = b"x = 1\n"
        entry = _entry("REMOVED")
        entry["subject_key"] = "api.multi"
        entry["locations"] = [{"snapshot_id": "s1", "path": PATH, "line": 1, "sha256": _sha(old)}]
        sides = {"from": _side("s1", old), "to": _side("s2", new)}
        evidence = [dict(_evidence(old), locations=[{"content_sha256": _sha(old)}])]
        attested = mc.prove(entry, sides, rule_id=RULE_ID, evidence=evidence, new=None)
        self.assertIsInstance(attested, mc.Attested, getattr(attested, "code", ""))
        record = mc.build(attested, rule_row=_rule(attested))
        self.assertEqual(record["derived_class"], "IDENTITY_DECORATOR_REMOVED")
        self.assertIsNone(record["new"])


class ProveRefusals(unittest.TestCase):
    def test_confirmed_entry_refused(self):
        entry = _entry()
        entry["confirmed"] = True
        self.assertEqual(_attest(entry=entry).code, "ENTRY_CONFIRMED")

    def test_ai_proposed_entry_refused(self):
        entry = _entry()
        entry["proposed_by"] = "AI"
        self.assertEqual(_attest(entry=entry).code, "ENTRY_PROPOSER")

    def test_unknown_and_renamed_classes_refused(self):
        entry = _entry()
        entry["class"] = "UNKNOWN"
        self.assertEqual(_attest(entry=entry).code, "ENTRY_CLASS")
        entry = _entry()
        entry["class"] = "RENAMED_CANDIDATE"
        self.assertEqual(_attest(entry=entry).code, "ENTRY_CLASS")

    def test_non_function_subject_refused(self):
        entry = _entry()
        entry["kind"] = "field"
        self.assertEqual(_attest(entry=entry).code, "ENTRY_SUBJECT")

    def test_detail_must_name_the_pair(self):
        entry = _entry()
        entry["detail"]["to"] = "other_round"
        self.assertEqual(_attest(entry=entry).code, "ENTRY_NAMES")

    def test_unpinned_source_refused(self):
        sides = _sides()
        sides["to"]["pinned"] = False
        self.assertEqual(_attest(sides=sides).code, "SOURCE_NOT_PINNED")

    def test_blob_mismatch_refused(self):
        sides = _sides()
        sides["from"]["data"] = V1 + b"# changed\n"
        self.assertEqual(_attest(sides=sides).code, "BLOB_MISMATCH")

    def test_entry_location_mismatch_refused(self):
        entry = _entry()
        entry["locations"][1]["sha256"] = _sha(b"other")
        self.assertEqual(_attest(entry=entry).code, "ENTRY_LOCATIONS")

    def test_evidence_not_official_refused(self):
        evidence = _evidence()
        evidence["official"] = False
        self.assertEqual(_attest(evidence=[evidence]).code, "EVIDENCE_INVALID")

    def test_evidence_without_proof_file_digest_refused(self):
        evidence = _evidence()
        evidence["locations"] = [{"content_sha256": _sha(b"unrelated")}]
        self.assertEqual(_attest(evidence=[evidence]).code, "EVIDENCE_INVALID")

    def test_no_evidence_refused(self):
        self.assertEqual(_attest(evidence=[]).code, "EVIDENCE_MISSING")

    def test_proof_refusal_passes_through(self):
        sides = _sides()
        sides["to"]["data"] = V2.replace(b"math.floor", b"math.ceil")
        sides["to"]["blob_sha256"] = _sha(sides["to"]["data"])
        entry = _entry()
        entry["locations"][1]["sha256"] = sides["to"]["blob_sha256"]
        evidence = [_evidence(sides["to"]["data"])]
        self.assertEqual(_attest(sides=sides, entry=entry, evidence=evidence).code, "S1_NOT_IDENTICAL")


class BuildRefusals(unittest.TestCase):
    def test_rule_params_must_match_derived_params(self):
        attested = _attest()
        rule = _rule(attested)
        rule["params"] = {"module": "odoo.tools.helpers", "old": "old_round", "new": "other"}
        with self.assertRaises(mc.ConfirmationError) as ctx:
            mc.build(attested, rule_row=rule)
        self.assertEqual(ctx.exception.code, "params_mismatch")

    def test_rule_evidence_must_match_proof_evidence(self):
        attested = _attest()
        rule = _rule(attested)
        rule["evidence"] = []
        with self.assertRaises(mc.ConfirmationError) as ctx:
            mc.build(attested, rule_row=rule)
        self.assertEqual(ctx.exception.code, "evidence_mismatch")


class L1Tampering(unittest.TestCase):
    def _check(self, record, rule, evidence, entry, code):
        verdict = mc.verify(record, rule_row=rule, evidence_rows=evidence, ledger_entry=entry)
        self.assertFalse(verdict.ok)
        self.assertIsNone(verdict.derived_class)
        self.assertIn(code, [c for c, _ in verdict.problems], verdict.problems)

    def test_extra_key_fails_schema(self):
        record, rule, evidence, entry = _record()
        record["change_class"] = "IDENTITY_DECORATOR_REMOVED"
        self._check(record, rule, evidence, entry, "schema")

    def test_missing_key_fails_schema(self):
        record, rule, evidence, entry = _record()
        del record["sources"]
        self._check(record, rule, evidence, entry, "schema")

    def test_confirmed_true_fails_schema(self):
        record, rule, evidence, entry = _record()
        record["ledger_entry"]["confirmed"] = True
        self._check(_reseal(record), rule, evidence, entry, "schema")

    def test_unsealed_field_flip_fails_record_digest(self):
        record, rule, evidence, entry = _record()
        record["old"] = "other"
        self._check(record, rule, evidence, entry, "record_digest")

    def test_witness_tamper_resealed_fails_witness_digest(self):
        record, rule, evidence, entry = _record()
        record["witness"]["to"]["bindings"]["extra"] = ["store"]
        self._check(_reseal(record), rule, evidence, entry, "witness_digest")

    def test_derived_class_flip_resealed_fails(self):
        record, rule, evidence, entry = _record()
        record["derived_class"] = "IDENTITY_DECORATOR_REMOVED"
        self._check(_reseal(record), rule, evidence, entry, "derived_class")

    def test_witness_with_source_text_resealed_fails(self):
        record, rule, evidence, entry = _record()
        record["witness"]["from"]["defs"]["old_round"]["free_names"] = ["return x"]
        record["witness_digest"] = digest_obj(record["witness"])
        self._check(_reseal(record), rule, evidence, entry, "witness")

    def test_rule_params_tamper_fails(self):
        record, rule, evidence, entry = _record()
        rule["params"] = dict(rule["params"], new="other_round")
        self._check(record, rule, evidence, entry, "rule_params")

    def test_rule_digest_tamper_fails(self):
        record, rule, evidence, entry = _record()
        rule["fixer_ref"] = "other.fixer"
        self._check(record, rule, evidence, entry, "rule_digest")

    def test_evidence_digest_mismatch_fails(self):
        record, rule, evidence, entry = _record()
        evidence = [dict(evidence[0], description="changed")]
        self._check(record, rule, evidence, entry, "evidence_digest")

    def test_missing_evidence_fails(self):
        record, rule, evidence, entry = _record()
        self._check(record, rule, [], entry, "evidence_missing")

    def test_wrong_rule_row_fails(self):
        record, rule, evidence, entry = _record()
        rule = dict(rule, id="1-1.python_orm.other")
        self._check(record, rule, evidence, entry, "rule_id")

    def test_proof_tool_digest_tamper_fails(self):
        record, rule, evidence, entry = _record()
        record["proof_tool"]["source_digest"] = "0" * 64
        self._check(_reseal(record), rule, evidence, entry, "proof_tool")

    def test_another_change_ledger_entry_fails(self):
        record, rule, evidence, entry = _record()
        other = dict(entry, change_id="CH-fedcba9876543210")
        self._check(record, rule, evidence, other, "ledger_identity")

    def test_ledger_entry_changed_fails(self):
        record, rule, evidence, entry = _record()
        changed = copy.deepcopy(entry)
        changed["detail"]["basis"] = "other"
        self._check(record, rule, evidence, changed, "ledger_entry")

    def test_ledger_history_is_not_bound(self):
        record, rule, evidence, entry = _record()
        grown = copy.deepcopy(entry)
        grown["history"].append({"seq": 2, "at": "t2", "actor": "MACHINE:machine-confirmation/1",
                                 "action": "machine_confirm", "from": None, "to": "x", "prev_hash": "1" * 64})
        self.assertTrue(mc.verify(record, rule_row=rule, evidence_rows=evidence, ledger_entry=grown).ok)

    def test_derived_class_is_none_when_tampered(self):
        record, rule, evidence, entry = _record()
        record["module"] = "odoo.other"
        self.assertIsNone(mc.derived_class(record, rule_row=rule, evidence_rows=evidence))


class L2Sources(unittest.TestCase):
    def test_corrupted_blob_fails(self):
        record, _, _, _ = _record()
        verdict = mc.verify_sources(record, {"from": V1, "to": V2 + b"#"})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.problems[0][0], "blob")

    def test_missing_blob_fails(self):
        record, _, _, _ = _record()
        self.assertFalse(mc.verify_sources(record, {"from": V1}).ok)

    def test_resealed_source_that_reproves_differently_fails(self):
        record, _, _, _ = _record()
        new_data = V2.replace(b"math.floor", b"math.ceil")  # a body change, not a docstring change
        record["sources"][1]["blob_sha256"] = _sha(new_data)
        record = _reseal(record)
        verdict = mc.verify_sources(record, {"from": V1, "to": new_data})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.problems, [("reprove", "S1_NOT_IDENTICAL")])

    def test_docstring_only_change_keeps_the_witness(self):
        record, _, _, _ = _record()
        new_data = V2.replace(b"Round.", b"Rounded.")
        record["sources"][1]["blob_sha256"] = _sha(new_data)
        record = _reseal(record)
        self.assertTrue(mc.verify_sources(record, {"from": V1, "to": new_data}).ok)

    def test_live_proofs_digest_is_the_file_digest(self):
        self.assertEqual(mc.live_source_digest(), _sha(Path(P.__file__).read_bytes()))


if __name__ == "__main__":
    unittest.main()
