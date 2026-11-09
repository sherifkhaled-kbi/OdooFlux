"""Feature 012 hardening (review item 2): L1 binds every identity to the release tree, not only to itself.

L1 (`machine_confirmation.verify`) is SELF-CONSISTENCY: a record that recomputes its own digests and re-proves its own
witness passes. It is not authenticity. Authenticity rests on the manifest digest of the release tree and on L2 where the
retained blobs exist. These tests pin the L1 cross-checks that a forger who recomputes every digest still cannot pass:
the module must be the one the source path names, and the evidence must be bound to the side that carries the proof.
"""

import copy
import hashlib
import unittest

from odooflux.knowledge.extract import proofs
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.update import machine_confirmation as mc

RULE_ID = "R1"
OLD_TEXT = b"def old(a):\n    return a\n"
NEW_TEXT = b'def new(a):\n    """Replaces ``old``."""\n    return a\n'
PATH = "odoo/x/y.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _side(data: bytes, snapshot: str, path: str = PATH) -> dict:
    return {"source_id": "s", "snapshot_id": snapshot, "revision": "a" * 40, "path": path,
            "blob_sha256": _sha(data), "verified": True, "official": True, "pinned": True, "data": data}


def _entry() -> dict:
    return {"change_id": "CH-0123456789abcdef", "confirmed": False, "proposed_by": "DETERMINISTIC",
            "class": "REPLACEMENT_CANDIDATE", "domain": "python_orm", "kind": "function", "subject_key": "old",
            "detail": {"from": "old", "to": "new", "source": "docs"},
            "locations": [{"snapshot_id": "ss-1", "path": PATH, "sha256": _sha(OLD_TEXT), "line": 1},
                          {"snapshot_id": "ss-2", "path": PATH, "sha256": _sha(NEW_TEXT), "line": 1}]}


def _evidence(digest_of: bytes = NEW_TEXT) -> dict:
    return {"id": "EV-001", "official": True, "rule_ids": [RULE_ID],
            "source_applicability": {"from": "a", "to": "b"}, "target_applicability": {"from": "x"},
            "locations": [{"content_sha256": _sha(digest_of)}]}


def _rule_row(record_params: dict) -> dict:
    return {"id": RULE_ID, "evidence": ["EV-001"], "params": dict(record_params), "origin": "GENERATED"}


def _sealed_record():
    sides = {"from": _side(OLD_TEXT, "ss-1"), "to": _side(NEW_TEXT, "ss-2")}
    attested = mc.prove(_entry(), sides, rule_id=RULE_ID, evidence=[_evidence()], new="new")
    assert not isinstance(attested, proofs.Refusal), attested
    row = _rule_row(attested.proof.derived_params)
    return mc.build(attested, rule_row=row), row


def _reseal(record: dict) -> dict:
    """Recompute every digest the verifier checks, as a forger with the code would."""
    forged = copy.deepcopy(record)
    forged["witness_digest"] = digest_obj(forged["witness"])
    body = {k: v for k, v in forged.items() if k != "record_digest"}
    forged["record_digest"] = digest_obj(body)
    return forged


class L1SelfConsistencyTests(unittest.TestCase):
    def test_the_honest_record_verifies(self):
        record, row = _sealed_record()
        verdict = mc.verify(record, rule_row=row, evidence_rows=[_evidence()])
        self.assertTrue(verdict.ok, verdict.problems)
        self.assertEqual(verdict.derived_class, "REPLACEMENT_CONFIRMED")

    def test_module_forged_away_from_the_source_path_fails_l1_even_with_recomputed_digests(self):
        # t3: module, witness and params are rewritten to `custom.pay` and every digest is recomputed. The source path
        # still names `odoo.x.y`, so L1 must refuse. (Before the fix this verified, and only L2 caught it.)
        record, row = _sealed_record()
        forged = copy.deepcopy(record)
        forged["witness"]["module"] = "custom.pay"
        forged["module"] = "custom.pay"
        forged["derived_params"]["module"] = "custom.pay"
        forged["witness_digest"] = digest_obj(forged["witness"])
        forged_row = dict(row, params=dict(forged["derived_params"]))
        forged["rule_digest"] = mc.certification.rule_digest(forged_row)
        forged["record_digest"] = digest_obj({k: v for k, v in forged.items() if k != "record_digest"})
        verdict = mc.verify(forged, rule_row=forged_row, evidence_rows=[_evidence()])
        self.assertFalse(verdict.ok)
        self.assertIn("module_path", {code for code, _ in verdict.problems})

    def test_subject_key_must_name_the_old_symbol(self):
        record, row = _sealed_record()
        record["subject"]["subject_key"] = "other_symbol"
        record = _reseal(record)
        verdict = mc.verify(record, rule_row=row, evidence_rows=[_evidence()])
        self.assertFalse(verdict.ok)
        self.assertIn("identity", {code for code, _ in verdict.problems})

    def test_derived_params_must_be_bound_to_the_witness_names(self):
        record, row = _sealed_record()
        record["derived_params"]["new"] = "other"
        row = dict(row, params=dict(record["derived_params"]))
        record["rule_digest"] = mc.certification.rule_digest(row)
        record = _reseal(record)
        verdict = mc.verify(record, rule_row=row, evidence_rows=[_evidence()])
        self.assertFalse(verdict.ok)

    def test_evidence_must_be_bound_to_the_side_that_carries_the_proof(self):
        # the proof side of a replacement is `to`; evidence that only carries the `from` digest is not that proof
        record, row = _sealed_record()
        wrong = _evidence(digest_of=OLD_TEXT)
        record["evidence"] = [{"id": "EV-001", "digest": digest_obj(wrong)}]
        record = _reseal(record)
        verdict = mc.verify(record, rule_row=row, evidence_rows=[wrong])
        self.assertFalse(verdict.ok)
        self.assertIn("evidence_side", {code for code, _ in verdict.problems})


if __name__ == "__main__":
    unittest.main()
