"""TST-011-043 (REQ-KAP-014, REQ-KAP-012, REQ-KAP-031, REQ-KAP-030): dispositions, confirm, merge.

Rules under test: rationale for NO_CUSTOM_MODULE_IMPACT and HUMAN_REVIEW; rule links for RULE_CREATED,
EXISTING_RULE_LINKED and DETECTION_ONLY; `confirm` only for rename and replacement candidates and only by a manual
actor; merge keeps manual dispositions and their history byte for byte; stale changes are carried, never deleted.
"""

import unittest

from odooflux.knowledge.ledger import dispositions as d
from odooflux.knowledge.ledger.ledger import Ledger, LedgerError
from odooflux.knowledge.release.canonical import canonical_bytes

SNAP_A = {"snapshot_id": "ss-" + "ab" * 6, "snapshot_digest": "ab" * 32}
SNAP_B = {"snapshot_id": "ss-" + "cd" * 6, "snapshot_digest": "cd" * 32}
TS = "2026-11-08T10:00:00Z"
RULES = {"PY-ORM-001": "DETECT_ONLY", "PY-ORM-002": "DRAFT"}


def _clock():
    return TS


def _draft(subject, cls="SIGNATURE_CHANGED", kind="field", line=12):
    return {"domain": "python_orm", "kind": kind, "subject_key": subject, "class": cls,
            "detail": {"from": "Float", "to": "Monetary"},
            "locations": [{"snapshot_id": SNAP_B["snapshot_id"], "path": "addons/sale_demo/models/order.py",
                           "line": line, "sha256": "a" * 64}],
            "proposed_by": "DETERMINISTIC"}


def _ledger(drafts, clock=_clock):
    return Ledger.create("17-01", SNAP_A, SNAP_B, drafts, clock=clock)


def _rec_bytes(ledger, cid):
    return canonical_bytes(ledger.get(cid))


class DispositionRuleTests(unittest.TestCase):
    def setUp(self):
        self.ledger = _ledger([_draft("sale.demo.order::field::amount")])
        self.cid = self.ledger.unresolved()[0]

    def test_rationale_required(self):
        before = _rec_bytes(self.ledger, self.cid)
        for disposition in ("NO_CUSTOM_MODULE_IMPACT", "HUMAN_REVIEW"):
            with self.subTest(disposition=disposition):
                with self.assertRaises(LedgerError):
                    d.set_disposition(self.ledger, self.cid, disposition, actor="MANUAL")
                with self.assertRaises(LedgerError):
                    d.set_disposition(self.ledger, self.cid, disposition, actor="MANUAL", rationale="   ")
                self.assertEqual(_rec_bytes(self.ledger, self.cid), before, "refused input changes nothing")
        d.set_disposition(self.ledger, self.cid, "NO_CUSTOM_MODULE_IMPACT", actor="MANUAL",
                          rationale="field is only read by the report")
        rec = self.ledger.get(self.cid)
        self.assertEqual(rec["disposition"], "NO_CUSTOM_MODULE_IMPACT")
        self.assertEqual(rec["disposition_data"]["rationale"], "field is only read by the report")
        self.assertEqual(rec["proposed_by"], "MANUAL")
        self.assertEqual(rec["history"][-1]["action"], "set_disposition")
        self.assertEqual(self.ledger.verify(), [])
        # moving back to UNRESOLVED needs a reason as well
        with self.assertRaises(LedgerError):
            d.set_disposition(self.ledger, self.cid, "UNRESOLVED", actor="MANUAL")

    def test_disposition_requires_rule(self):
        before = _rec_bytes(self.ledger, self.cid)
        for disposition in ("RULE_CREATED", "EXISTING_RULE_LINKED", "DETECTION_ONLY"):
            with self.subTest(disposition=disposition):
                with self.assertRaises(LedgerError):
                    d.set_disposition(self.ledger, self.cid, disposition, actor="MANUAL", known_rules=RULES)
        with self.assertRaises(LedgerError):  # a rule id that is not in the tree
            d.set_disposition(self.ledger, self.cid, "EXISTING_RULE_LINKED", actor="MANUAL",
                              rule_ids=["PY-NOPE-999"], known_rules=RULES)
        with self.assertRaises(LedgerError):  # DETECTION_ONLY needs a DETECT_ONLY rule
            d.set_disposition(self.ledger, self.cid, "DETECTION_ONLY", actor="MANUAL",
                              rule_ids=["PY-ORM-002"], known_rules=RULES)
        self.assertEqual(_rec_bytes(self.ledger, self.cid), before)
        d.set_disposition(self.ledger, self.cid, "EXISTING_RULE_LINKED", actor="MANUAL",
                          rule_ids=["PY-ORM-002"], evidence_ids=["EV-K00001"], known_rules=RULES)
        self.assertEqual(self.ledger.get(self.cid)["disposition_data"]["rule_ids"], ["PY-ORM-002"])
        d.set_disposition(self.ledger, self.cid, "DETECTION_ONLY", actor="MANUAL",
                          rule_ids=["PY-ORM-001"], known_rules=RULES)
        self.assertEqual(self.ledger.get(self.cid)["disposition"], "DETECTION_ONLY")

    def test_ai_cannot_set_dispositions_other_than_human_review(self):
        before = _rec_bytes(self.ledger, self.cid)
        with self.assertRaises(LedgerError):
            d.set_disposition(self.ledger, self.cid, "RULE_CREATED", actor="AI", rule_ids=["PY-ORM-001"],
                              known_rules=RULES)
        self.assertEqual(_rec_bytes(self.ledger, self.cid), before)
        d.set_disposition(self.ledger, self.cid, "HUMAN_REVIEW", actor="AI", rationale="unclear rename")
        self.assertEqual(self.ledger.get(self.cid)["disposition"], "HUMAN_REVIEW")

    def test_unknown_change_refused(self):
        with self.assertRaises(LedgerError):
            d.set_disposition(self.ledger, "CH-0000000000000000", "HUMAN_REVIEW", actor="MANUAL",
                              rationale="x")


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.ledger = _ledger([_draft("sale.demo.order::field::amount", cls="RENAMED_CANDIDATE", line=3),
                               _draft("sale.demo.order::field::total", cls="ADDED", line=4)])
        ids = {self.ledger.get(c)["subject_key"]: c for c in self.ledger.unresolved()}
        self.rename = ids["sale.demo.order::field::amount"]
        self.added = ids["sale.demo.order::field::total"]

    def test_confirm_refused_for_ai(self):
        before = _rec_bytes(self.ledger, self.rename)
        for actor in ("AI", "AI_PROPOSED", "DETERMINISTIC"):
            with self.subTest(actor=actor):
                with self.assertRaises(LedgerError):
                    d.confirm(self.ledger, self.rename, actor=actor)
        self.assertEqual(_rec_bytes(self.ledger, self.rename), before)
        self.assertFalse(self.ledger.get(self.rename)["confirmed"])

    def test_confirm_only_for_candidate_classes(self):
        with self.assertRaises(LedgerError):
            d.confirm(self.ledger, self.added, actor="MANUAL")
        d.confirm(self.ledger, self.rename, actor="MANUAL")
        rec = self.ledger.get(self.rename)
        self.assertTrue(rec["confirmed"])
        self.assertEqual(rec["history"][-1]["action"], "confirm")
        with self.assertRaises(LedgerError):
            d.confirm(self.ledger, self.rename, actor="MANUAL")  # already confirmed
        self.assertEqual(self.ledger.verify(), [])


class MergeTests(unittest.TestCase):
    def test_merge_preserves_manual(self):
        previous = _ledger([_draft("sale.demo.order::field::amount", line=12),
                            _draft("sale.demo.order::field::total", line=20)])
        by_subject = {previous.get(c)["subject_key"]: c for c in previous.unresolved()}
        manual_id = by_subject["sale.demo.order::field::amount"]  # the one whose location moves
        other_id = by_subject["sale.demo.order::field::total"]  # unchanged: must keep its bytes
        d.set_disposition(previous, manual_id, "HUMAN_REVIEW", actor="MANUAL", rationale="checked with owner")
        manual_before = _rec_bytes(previous, manual_id)
        other_before = _rec_bytes(previous, other_id)

        fresh = _ledger([_draft("sale.demo.order::field::amount", line=40),  # moved line: locations change
                         _draft("sale.demo.order::field::total", line=20)])
        merged, report = d.merge(fresh, previous)
        self.assertEqual(merged.get(manual_id)["disposition"], "HUMAN_REVIEW")
        self.assertEqual(merged.get(manual_id)["history"], previous.get(manual_id)["history"])
        self.assertEqual(merged.get(manual_id)["disposition_data"], previous.get(manual_id)["disposition_data"])
        self.assertEqual(merged.get(manual_id)["proposed_by"], "MANUAL")
        self.assertNotEqual(merged.get(manual_id)["locations"], previous.get(manual_id)["locations"])
        self.assertEqual(_rec_bytes(previous, manual_id), manual_before, "previous ledger is not mutated")
        conflict_ids = [c["change_id"] for c in report["conflicts"]]
        self.assertIn(manual_id, conflict_ids)
        proposed = next(c for c in report["conflicts"] if c["change_id"] == manual_id)
        self.assertEqual((proposed["kept"], proposed["proposed"]), ("HUMAN_REVIEW", "UNRESOLVED"))
        self.assertEqual(_rec_bytes(merged, other_id), other_before, "unchanged ids keep their bytes")
        self.assertEqual(merged.verify(), [])

    def test_stale_never_deleted(self):
        previous = _ledger([_draft("sale.demo.order::field::amount"), _draft("sale.demo.order::field::gone")])
        gone = next(c for c in previous.unresolved() if previous.get(c)["subject_key"].endswith("gone"))
        gone_before = _rec_bytes(previous, gone)
        fresh = _ledger([_draft("sale.demo.order::field::amount")])
        merged, report = d.merge(fresh, previous)
        self.assertIn(gone, report["stale"])
        self.assertIn(gone, [r["change_id"] for r in merged.records()])
        self.assertEqual(_rec_bytes(merged, gone), gone_before)
        self.assertEqual(merged.verify(), [])

    def test_added_changes_are_unresolved(self):
        previous = _ledger([_draft("sale.demo.order::field::amount")])
        fresh = _ledger([_draft("sale.demo.order::field::amount"), _draft("sale.demo.order::field::new")])
        merged, report = d.merge(fresh, previous)
        self.assertEqual(len(report["added"]), 1)
        for cid in report["added"]:
            self.assertEqual(merged.get(cid)["disposition"], "UNRESOLVED")
            self.assertEqual(merged.get(cid)["history"][0]["action"], "create")
        self.assertIn(report["added"][0], merged.unresolved())


if __name__ == "__main__":
    unittest.main()
