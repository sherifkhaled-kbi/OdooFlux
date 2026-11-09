"""Feature 012, Addendum F phase 1: the automatic FIX orchestration (`knowledge/autofix.py`) with fake proofs.

`plan_pair` (build step 6): no prover means nothing is proposed; a proved change gets a confirmation file and a pending
rule and is settled; any refusal leaves nothing behind. `promote_certified` (build step 9): any failure at certify or at
the trust check restores the pending bytes and reports a coded demotion; one row never affects another.

The proof and the confirmation are fakes here (phase 2 supplies `machine_confirmation` and `proofs`). Synthetic only.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import autofix
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.unit.knowledge.kap.test_accept import AT, DATA_DIRS, KNOWN_DETECTORS, SOURCE, _draft, _ledger

REMOVED_A = "res.partner::field::alpha"
REMOVED_B = "res.partner::field::beta"
ADDED_C = "res.partner::field::gamma"  # a class the automatic path never proves


def _fake_proof(result, change_id, confirmation=None):
    """A proof for `change_id` built from an ordinary generation of the same ledger (fake: no proof is computed)."""
    candidate = copy.deepcopy(next(c for c in result["candidates"] if c["change_id"] == change_id))
    candidate["rule"]["maturity"] = "DETECT_ONLY"
    candidate["rule"]["review_required"] = True
    evidence = next(e for e in result["evidence"] if e["id"] in candidate["rule"]["evidence"])
    return {"candidate": candidate, "evidence": evidence,
            "confirmation": confirmation or {"schema": "odooflux.machine-confirmation/1", "change_id": change_id}}


class FakeProver:
    def __init__(self, proofs):
        self.proofs = proofs
        self.calls = []

    def __call__(self, record, store):
        self.calls.append(record["change_id"])
        if record["change_id"] in self.proofs:
            return self.proofs[record["change_id"]]
        raise autofix.Refusal("NOT_PROVEN", "no proof is available for this change in the fixture")


class AutofixTreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name) / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        self.ledger = _ledger([_draft(REMOVED_A, "field", "REMOVED"), _draft(REMOVED_B, "field", "REMOVED"),
                               _draft(ADDED_C, "field", "ADDED")])
        self.cid = {rec["subject_key"]: rec["change_id"] for rec in self.ledger.records()}
        self.result = gen.generate(self.ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                                   known_detectors=KNOWN_DETECTORS)

    def tree_bytes(self):
        return {p.relative_to(self.tree).as_posix(): p.read_bytes()
                for p in sorted(self.tree.rglob("*")) if p.is_file()}

    def _rules_path(self):
        return self.tree / "compatibility" / "17-18.rules.json"

    def _rows(self):
        return json.loads(self._rules_path().read_text(encoding="utf-8"))

    def _pending_ids(self, *subjects):
        return [self._row_id(subject) for subject in subjects]

    def _row_id(self, subject):
        return next(c["rule"]["id"] for c in self.result["candidates"] if c["change_id"] == self.cid[subject])

    def _refusals(self, out, subject):
        return [r["code"] for r in out["refused"] if r["change_id"] == self.cid[subject]]

    def _plan(self, prover):
        return autofix.plan_pair(self.ledger, self.tree, prove=prover, store=None, author="alice", at=AT)

    def _rewrite_row(self, rule_id, **changes):
        rows = self._rows()
        for row in rows:
            if row["id"] == rule_id:
                row.update(changes)
        self._rules_path().write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


class PlanPairTests(AutofixTreeTests):
    def test_without_a_prover_nothing_is_proposed_and_nothing_changes(self):
        before_tree, before_records = self.tree_bytes(), copy.deepcopy(self.ledger.records())
        out = autofix.plan_pair(self.ledger, self.tree, prove=None)
        self.assertEqual(out, {"accepted": [], "refused": []})
        self.assertEqual(self.tree_bytes(), before_tree)
        self.assertEqual(self.ledger.records(), before_records)

    def test_a_proved_eligible_change_becomes_a_pending_rule_and_is_settled(self):
        prover = FakeProver({self.cid[REMOVED_A]: _fake_proof(self.result, self.cid[REMOVED_A])})
        out = self._plan(prover)
        self.assertEqual([a["change_id"] for a in out["accepted"]], [self.cid[REMOVED_A]])
        self.assertEqual(self._refusals(out, REMOVED_B), ["NOT_PROVEN"])  # eligible, unproven: refused, not settled
        self.assertEqual(sorted(prover.calls), sorted([self.cid[REMOVED_A], self.cid[REMOVED_B]]))
        self.assertNotIn(self.cid[ADDED_C], prover.calls)  # the class ADDED is never offered to the prover
        rule_id = self._row_id(REMOVED_A)
        row = next(r for r in self._rows() if r["id"] == rule_id)
        self.assertEqual((row["maturity"], row["fixer_ref"], row["review_required"], row["origin"]),
                         ("DETECT_ONLY", None, True, "GENERATED"))
        confirmation = json.loads((self.tree / "confirmations" / f"{rule_id}.json").read_text(encoding="utf-8"))
        self.assertEqual(confirmation["change_id"], self.cid[REMOVED_A])
        self.assertEqual(self.ledger.get(self.cid[REMOVED_A])["disposition"], "RULE_CREATED")
        self.assertNotEqual(self.ledger.get(self.cid[REMOVED_B])["disposition"], "RULE_CREATED")

    def test_the_ordinary_generation_then_skips_the_settled_change(self):
        prover = FakeProver({self.cid[REMOVED_A]: _fake_proof(self.result, self.cid[REMOVED_A])})
        out = self._plan(prover)
        settled = {a["change_id"] for a in out["accepted"]}
        again = gen.generate(self.ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                             known_detectors=KNOWN_DETECTORS, skip_change_ids=settled)
        self.assertNotIn(self.cid[REMOVED_A], {c["change_id"] for c in again["candidates"]})
        self.assertIn(self.cid[REMOVED_B], {c["change_id"] for c in again["candidates"]})

    def test_a_refusal_leaves_no_confirmation_no_rule_and_no_settlement(self):
        before = self.tree_bytes()
        out = self._plan(FakeProver({}))
        self.assertEqual(out["accepted"], [])
        self.assertEqual({r["code"] for r in out["refused"]}, {"NOT_PROVEN"})
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse((self.tree / "confirmations").exists())

    def test_a_pending_rule_refused_by_accept_leaves_no_confirmation(self):
        proof = _fake_proof(self.result, self.cid[REMOVED_A])
        proof["candidate"]["rule"]["fixer_ref"] = "odooflux.rules.python.certified:rewrite_imported_symbol"
        before = self.tree_bytes()
        out = self._plan(FakeProver({self.cid[REMOVED_A]: proof}))
        self.assertEqual(out["accepted"], [])
        self.assertEqual(self._refusals(out, REMOVED_A), [autofix.ACCEPT_REFUSED])
        self.assertEqual(self.tree_bytes(), before)
        self.assertNotEqual(self.ledger.get(self.cid[REMOVED_A])["disposition"], "RULE_CREATED")

    def test_an_existing_confirmation_is_never_overwritten(self):
        rule_id = self._row_id(REMOVED_A)
        (self.tree / "confirmations").mkdir()
        existing = self.tree / "confirmations" / f"{rule_id}.json"
        existing.write_text('{"kept": true}', encoding="utf-8")
        out = self._plan(FakeProver({self.cid[REMOVED_A]: _fake_proof(self.result, self.cid[REMOVED_A])}))
        self.assertEqual(self._refusals(out, REMOVED_A), [autofix.ACCEPT_REFUSED])
        self.assertEqual(existing.read_text(encoding="utf-8"), '{"kept": true}')


class PromoteCertifiedTests(AutofixTreeTests):
    def setUp(self):
        super().setUp()
        proofs = {self.cid[REMOVED_A]: _fake_proof(self.result, self.cid[REMOVED_A]),
                  self.cid[REMOVED_B]: _fake_proof(self.result, self.cid[REMOVED_B])}
        self.plan = self._plan(FakeProver(proofs))
        self.assertEqual(len(self.plan["accepted"]), 2)
        self.pending = [a["rule_id"] for a in self.plan["accepted"]]
        self.rule_a = self._row_id(REMOVED_A)
        self.rule_b = self._row_id(REMOVED_B)

    def _certify_ok(self, tree, rule_id):
        self._rewrite_row(rule_id, maturity="FIX_ENABLED", fixer_ref="odooflux.rules.python.certified:x",
                          review_required=False)
        path = tree / "certifications" / f"{rule_id}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"schema": "fake"}', encoding="utf-8")

    def test_a_certified_and_trusted_row_is_kept(self):
        demoted = autofix.promote_certified(self.tree, self.pending,
                                            certify=self._certify_ok, trust=lambda tree, rid: [])
        self.assertEqual(demoted, [])
        row = next(r for r in self._rows() if r["id"] == self.rule_a)
        self.assertEqual(row["maturity"], "FIX_ENABLED")

    def test_a_certify_failure_restores_the_pending_bytes(self):
        before_rules = self._rules_path().read_bytes()

        def certify(tree, rule_id):
            self._certify_ok(tree, rule_id)
            raise RuntimeError("issue refused")

        demoted = autofix.promote_certified(self.tree, [self.rule_a], certify=certify, trust=lambda t, r: [])
        self.assertEqual([(d["rule_id"], d["code"]) for d in demoted], [(self.rule_a, autofix.CERTIFY_FAILED)])
        self.assertEqual(self._rules_path().read_bytes(), before_rules)
        self.assertFalse((self.tree / "certifications" / f"{self.rule_a}.json").exists())

    def test_a_trust_failure_restores_the_pending_bytes_and_reports_the_finding(self):
        before_rules = self._rules_path().read_bytes()
        finding = {"rule_id": self.rule_a, "gate": 6, "code": "cert-verify-failed", "detail": "digest differs"}
        demoted = autofix.promote_certified(self.tree, [self.rule_a], certify=self._certify_ok,
                                            trust=lambda tree, rid: [finding])
        self.assertEqual(demoted[0]["code"], autofix.TRUST_FAILED)
        self.assertIn("cert-verify-failed", demoted[0]["detail"])
        self.assertEqual(self._rules_path().read_bytes(), before_rules)
        self.assertFalse((self.tree / "certifications" / f"{self.rule_a}.json").exists())

    def test_without_a_certifier_every_pending_row_stays_detect_only(self):
        before_rules = self._rules_path().read_bytes()
        demoted = autofix.promote_certified(self.tree, self.pending, certify=None, trust=lambda t, r: [])
        self.assertEqual(sorted(d["rule_id"] for d in demoted), sorted(self.pending))
        self.assertEqual({d["code"] for d in demoted}, {autofix.CERTIFIER_MISSING})
        self.assertEqual(self._rules_path().read_bytes(), before_rules)

    def test_one_failing_row_does_not_demote_or_block_another(self):
        def certify(tree, rule_id):
            if rule_id == self.rule_a:
                raise RuntimeError("boom")
            self._certify_ok(tree, rule_id)

        demoted = autofix.promote_certified(self.tree, self.pending, certify=certify, trust=lambda t, r: [])
        self.assertEqual([d["rule_id"] for d in demoted], [self.rule_a])
        row_b = next(r for r in self._rows() if r["id"] == self.rule_b)
        self.assertEqual(row_b["maturity"], "FIX_ENABLED")


if __name__ == "__main__":
    unittest.main()
