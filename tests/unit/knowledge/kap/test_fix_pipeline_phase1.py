"""Feature 012, Addendum F phase 1 (plan F3 steps 3, 4 and 6): the trust and pipeline wiring that does not need the proof
(A) or the bound transformers (B).

Covered: the change class of a certified row comes only from a verified confirmation (`safety.confirmed_class`), never
from the record; a GENERATED row is refused by certification without `confirmation_verified`; `accept_fix_rule` accepts
only the DETECT_ONLY, fixer-less, review-required shape; `generate(skip_change_ids=...)` settles nothing for a skipped
change; step 9 writes provenance before any trust check and reports demotions.

Synthetic fixtures only. Stdlib unittest. Helpers are imported as functions so no TestCase is collected twice.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux import builtins as composition_root
from odooflux.knowledge import pipeline
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.release import safety
from odooflux.knowledge.update import certification as cert
from tests.unit.knowledge.kap.test_accept import AT, DATA_DIRS, KNOWN_DETECTORS, SOURCE, _draft, _ledger
from tests.unit.knowledge.kap.test_certified_fix_trust import (
    INDEX, RULE_ID, make_evidence, make_row, store_record, trust, write_tree)


class FakeExecutor:
    """Stands in for the bound executor. It records what certification asks of it and refuses every row."""

    def __init__(self):
        self.eligible_calls = []

    def eligible(self, rule_row, change_class=None, **kwargs):
        self.eligible_calls.append((change_class, dict(kwargs)))
        return None, "stub refusal"

    def transformer_identity(self, template_id):
        return {"qualified_name": "stub", "source_digest": "0" * 64}

    def exercise(self, rule_row, template_id, params):
        raise AssertionError("certification must refuse before exercising a row the executor did not elect")


class CertificationGeneratedGateTests(unittest.TestCase):
    """certification.issue/verify: a GENERATED row needs the confirmation flag; the executor sees it only then."""

    def setUp(self):
        cert._reset_for_tests()
        self.executor = FakeExecutor()
        cert.attach_executor(self.executor)
        self.addCleanup(self._restore_executor)
        self.evidence = [make_evidence()]
        self.mapping = cert.source_confidentiality_from_index(INDEX)

    def _restore_executor(self):
        cert._reset_for_tests()
        composition_root.build_context()

    def _row(self, origin):
        return make_row(origin=origin)

    def test_generated_row_without_confirmation_is_refused_before_the_executor(self):
        with self.assertRaises(cert.CertificationError) as raised:
            cert.issue(self._row("GENERATED"), self.evidence, source_confidentiality=self.mapping,
                       change_class="REPLACEMENT_CONFIRMED")
        self.assertEqual(raised.exception.code, "not_eligible")
        self.assertIn("GENERATED", raised.exception.detail)
        self.assertEqual(self.executor.eligible_calls, [])

    def test_verify_reports_the_generated_refusal_as_a_finding(self):
        findings = cert.verify(self._row("GENERATED"), self.evidence, {"schema": "x"},
                               source_confidentiality=self.mapping, change_class="REPLACEMENT_CONFIRMED")
        self.assertIn("not_eligible", {f["code"] for f in findings})
        self.assertEqual(self.executor.eligible_calls, [])

    def test_generated_row_with_confirmation_asks_the_executor_with_the_flag(self):
        with self.assertRaises(cert.CertificationError) as raised:
            cert.issue(self._row("GENERATED"), self.evidence, source_confidentiality=self.mapping,
                       change_class="REPLACEMENT_CONFIRMED", confirmation_verified=True)
        self.assertEqual(raised.exception.detail, "stub refusal")
        self.assertEqual(self.executor.eligible_calls, [("REPLACEMENT_CONFIRMED", {"confirmation_verified": True})])

    def test_other_origins_keep_the_executor_contract_exactly(self):
        for origin in ("MANUAL", "BUILTIN"):
            with self.subTest(origin=origin):
                self.executor.eligible_calls.clear()
                with self.assertRaises(cert.CertificationError):
                    cert.issue(self._row(origin), self.evidence, source_confidentiality=self.mapping,
                               change_class="REPLACEMENT_CONFIRMED")
                self.assertEqual(self.executor.eligible_calls, [("REPLACEMENT_CONFIRMED", {})])


class ConfirmedClassTrustTests(unittest.TestCase):
    """The trust path never reads the class a record declares."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        cert._reset_for_tests()
        composition_root.build_context()
        safety._reset_trust_cache_for_tests()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(cert._reset_for_tests)
        self.addCleanup(composition_root.build_context)

    def _gate_passing_tree(self):
        tree = write_tree(self.base, [make_row()], [make_evidence()])
        return tree

    def test_no_verified_confirmation_establishes_no_class(self):
        tree = self._gate_passing_tree()
        kb = load_knowledge(tree)
        row = next(r for r in kb.rules if r["id"] == RULE_ID)
        change_class, findings = safety.confirmed_class(row, tree, kb, INDEX, None)
        self.assertIsNone(change_class)
        self.assertEqual([f["code"] for f in findings], [safety.CONFIRMATION_MISSING])

    def test_certified_row_without_a_confirmation_is_untrusted(self):
        tree = self._gate_passing_tree()
        store_record(tree, RULE_ID, {"schema": "odooflux.fix-certification/1", "change_class": "REPLACEMENT_CONFIRMED"})
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn(safety.CONFIRMATION_MISSING, {f["code"] for f in findings})

    def test_the_class_passed_to_verification_is_the_confirmed_one_not_the_records(self):
        tree = self._gate_passing_tree()
        record = {"schema": "odooflux.fix-certification/1", "change_class": "REPLACEMENT_CONFIRMED"}
        store_record(tree, RULE_ID, record)
        with mock.patch.object(safety, "confirmed_class", lambda *args: ("REMOVED", [])), \
                mock.patch.object(safety, "_verify_record", return_value=[]) as verify:
            trusted, _ = trust(tree, RULE_ID)
        self.assertTrue(trusted)
        args = verify.call_args.args
        self.assertEqual(args[2], record)  # the stored record is what is checked
        self.assertEqual(args[4], "REMOVED")  # the confirmed class, never record["change_class"]
        self.assertIs(verify.call_args.kwargs["confirmation_verified"], True)  # a non-None class is confirmed

    def test_a_refused_confirmation_leaves_verification_out_of_it(self):
        tree = self._gate_passing_tree()
        store_record(tree, RULE_ID, {"schema": "odooflux.fix-certification/1"})
        with mock.patch.object(safety, "confirmed_class", lambda *args: (None, [{
                "rule_id": RULE_ID, "gate": 6, "code": safety.CONFIRMATION_MISSING, "detail": "x"}])), \
                mock.patch.object(safety, "_verify_record") as verify:
            trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        verify.assert_not_called()
        self.assertEqual([f["code"] for f in findings], [safety.CONFIRMATION_MISSING])


class AcceptFixRuleTests(unittest.TestCase):
    """accept_fix_rule writes only the pending shape: DETECT_ONLY, no fixer, review required, origin GENERATED."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _candidate(self, cls="REMOVED"):
        ledger = _ledger([_draft("res.partner::field::foo", "field", cls)])
        result = gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                              known_detectors=KNOWN_DETECTORS)
        candidate = copy.deepcopy(result["candidates"][0])
        candidate["rule"]["maturity"] = "DETECT_ONLY"
        candidate["rule"]["review_required"] = True
        return ledger, candidate, result["evidence"]

    def _rows(self):
        return json.loads((self.tree / "compatibility" / "17-18.rules.json").read_text(encoding="utf-8"))

    def test_pending_rule_is_written_detect_only_and_settles_the_change(self):
        ledger, candidate, evidence = self._candidate()
        out = acc.accept_fix_rule(self.tree, candidate, ledger=ledger, evidence=evidence, author="alice", at=AT)
        self.assertEqual(out["status"], "ACCEPTED")
        row = next(r for r in self._rows() if r["id"] == candidate["rule"]["id"])
        self.assertEqual((row["maturity"], row["origin"], row["fixer_ref"], row["review_required"]),
                         ("DETECT_ONLY", "GENERATED", None, True))
        self.assertEqual(ledger.get(candidate["change_id"])["disposition"], "RULE_CREATED")

    def test_a_fixer_or_fix_enabled_maturity_is_refused_and_nothing_is_written(self):
        for label, change in (("fixer", {"fixer_ref": "odooflux.rules.python.certified:x"}),
                              ("fix-enabled", {"maturity": "FIX_ENABLED"})):
            with self.subTest(label=label):
                ledger, candidate, evidence = self._candidate()
                candidate["rule"].update(change)
                before = (self.tree / "compatibility" / "17-18.rules.json").read_bytes()
                with self.assertRaises(acc.AcceptError):
                    acc.accept_fix_rule(self.tree, candidate, ledger=ledger, evidence=evidence, author="alice", at=AT)
                self.assertEqual(candidate["status"], "PROPOSED")
                self.assertEqual((self.tree / "compatibility" / "17-18.rules.json").read_bytes(), before)
                self.assertNotEqual(ledger.get(candidate["change_id"])["disposition"], "RULE_CREATED")

    def test_a_pending_rule_must_be_detect_only_and_review_required(self):
        for label, change in (("draft", {"maturity": "DRAFT"}), ("not-review", {"review_required": False}),
                              ("review-missing", {"review_required": None})):
            with self.subTest(label=label):
                ledger, candidate, evidence = self._candidate()
                candidate["rule"].update(change)
                with self.assertRaises(acc.AcceptError):
                    acc.accept_fix_rule(self.tree, candidate, ledger=ledger, evidence=evidence, author="alice", at=AT)
                self.assertEqual(candidate["status"], "PROPOSED")

    def test_plain_accept_still_refuses_a_fixer(self):
        ledger, candidate, evidence = self._candidate()
        candidate["rule"]["fixer_ref"] = "odooflux.rules.python.certified:x"
        with self.assertRaises(acc.AcceptError):
            acc.accept(self.tree, candidate, ledger=ledger, evidence=evidence, author="alice", at=AT)


class GenerateSkipTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name) / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_skipped_change_gets_no_candidate_evidence_or_disposition(self):
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        cid = ledger.records()[0]["change_id"]
        control = gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                               known_detectors=KNOWN_DETECTORS)
        self.assertEqual(len(control["candidates"]), 1)
        result = gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                              known_detectors=KNOWN_DETECTORS, skip_change_ids={cid})
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(result["dispositions"], [])
        self.assertEqual(result["skipped"], [{"change_id": cid, "reason": gen.FIX_RULE_ACCEPTED}])
        self.assertNotEqual(ledger.get(cid)["disposition"], "RULE_CREATED")


class PipelineOrderingTests(unittest.TestCase):
    """Step 9 (rule-tests): provenance is written first, then the trust check, and demotions are reported."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name) / "release" / "knowledge"
        self.tree.mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)

    def _ctx(self, outputs=None):
        return SimpleNamespace(outputs=outputs or {})

    def test_provenance_is_written_before_the_trust_check(self):
        calls = []
        with mock.patch.object(pipeline, "_stage_tree", return_value=self.tree), \
                mock.patch.object(pipeline, "_parent_rules", return_value={}), \
                mock.patch.object(pipeline, "_write_release_provenance",
                                  side_effect=lambda ctx: calls.append("provenance")), \
                mock.patch.object(pipeline, "_fix_trust_findings",
                                  side_effect=lambda tree: calls.append("trust") or []):
            out = pipeline._rule_tests(self._ctx())
        self.assertEqual(calls, ["provenance", "trust"])
        self.assertEqual(out["autofix_demoted"], [])
        self.assertEqual(out["safety_findings"], [])

    def test_a_pending_row_that_cannot_be_certified_is_demoted_and_the_build_goes_on(self):
        # The pipeline always runs the real certifier (addendum F3 step 9); a pending id with no rule in the tree (no
        # confirmation, no row) is demoted with a coded reason and nothing blocks the build.
        pending_id = "17-18.python.pending-fix"
        with mock.patch.object(pipeline, "_stage_tree", return_value=self.tree), \
                mock.patch.object(pipeline, "_parent_rules", return_value={}), \
                mock.patch.object(pipeline, "_write_release_provenance"), \
                mock.patch.object(pipeline, "_fix_trust_findings", return_value=[]):
            out = pipeline._rule_tests(self._ctx({"candidates": {"autofix_pending": [pending_id]}}))
        self.assertEqual([d["rule_id"] for d in out["autofix_demoted"]], [pending_id])
        self.assertTrue(out["autofix_demoted"][0]["code"])
        self.assertNotIn("CERTIFIER_NOT_ATTACHED", {d["code"] for d in out["autofix_demoted"]})


if __name__ == "__main__":
    unittest.main()
