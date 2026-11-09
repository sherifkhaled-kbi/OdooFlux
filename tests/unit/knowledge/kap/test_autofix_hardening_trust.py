"""Feature 012 hardening (review item 1): who may be trusted as FIX_ENABLED.

A row whose origin is not MANUAL or BUILTIN (GENERATED, AI_PROPOSED, an unknown origin, or no origin and not shipped) is
always governed by its certification: it must carry an `auto-cert:` approval, a verified machine confirmation and a
valid record. A row whose fixer or detector is bound from `odooflux.rules.python.certified` is governed whatever its
origin or approval string, so a human approval or a missing record never makes it trusted.

These tests use the real confirmation path (no stub of `confirmed_class`), except where a test states it.
Shared fixtures come from test_certified_fix_trust by module reference, so that module's test cases are not re-run here.
"""

import unittest
from unittest import mock

from odooflux import builtins as composition_root
from odooflux.knowledge.release import safety
from odooflux.knowledge.update import certification as cert
from tests.unit.knowledge.kap import test_certified_fix_trust as base

CHANGE_CLASS = base.CHANGE_CLASS
RULE_ID = base.RULE_ID


class HardeningBase(unittest.TestCase):
    """The real executor and the real confirmation check. Only the caches are reset."""

    def setUp(self):
        self._tmp = base.tempfile.TemporaryDirectory()
        self.root = base.Path(self._tmp.name)
        cert._reset_for_tests()
        composition_root.build_context()
        safety._reset_trust_cache_for_tests()

    def tearDown(self):
        cert._reset_for_tests()
        composition_root.build_context()
        safety._reset_trust_cache_for_tests()
        self._tmp.cleanup()

    def trust_of(self, tree, rule_id=RULE_ID):
        return base.trust(tree, rule_id)

    def write_confirmation(self, tree, record):
        path = tree / safety.CONFIRMATION_DIR / f"{RULE_ID}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(base.json.dumps(record), encoding="utf-8")


class GovernedOriginTests(HardeningBase):
    def test_generated_row_with_a_human_approval_and_nothing_else_is_untrusted(self):
        # t4: origin GENERATED, approval `human:alice`, no record and no confirmation was trusted before the fix
        row = base.make_row(origin="GENERATED", approval="human:alice")
        tree = base.write_tree(self.root / "gen-human", [row], [base.make_evidence()])
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertTrue(findings)

    def test_generated_row_without_any_approval_is_untrusted(self):
        tree = base.write_tree(self.root / "gen-none", [base.make_row(origin="GENERATED")], [base.make_evidence()])
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertIn("cert-approval-missing", base.codes(findings))

    def test_generated_row_with_auto_approval_but_no_confirmation_is_untrusted(self):
        evidence = [base.make_evidence()]
        row = base.make_row(origin="GENERATED")
        record = cert.issue(row, evidence, source_confidentiality=base.CONFIDENTIALITY,
                            change_class=CHANGE_CLASS, confirmation_verified=True)
        row["approval"] = cert.reference(record)
        tree = base.write_tree(self.root / "gen-noconf", [row], evidence)
        base.store_record(tree, RULE_ID, record)
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertIn(safety.CONFIRMATION_MISSING, base.codes(findings))

    def test_generated_row_with_auto_approval_confirmation_and_record_is_trusted(self):
        # the positive case: the chain is complete, so the governed row is trusted (the verifier is stubbed here,
        # standing in for a confirmation that verifies; L1 itself is covered in test_machine_confirmation_hardening)
        evidence = [base.make_evidence()]
        row = base.make_row(origin="GENERATED")
        record = cert.issue(row, evidence, source_confidentiality=base.CONFIDENTIALITY,
                            change_class=CHANGE_CLASS, confirmation_verified=True)
        row["approval"] = cert.reference(record)
        tree = base.write_tree(self.root / "gen-ok", [row], evidence)
        base.store_record(tree, RULE_ID, record)
        with mock.patch.object(safety, "confirmed_class", lambda *args: (CHANGE_CLASS, [])):
            self.assertEqual(self.trust_of(tree), (True, []))

    def test_ai_proposed_row_is_always_governed(self):
        tree = base.write_tree(self.root / "ai", [base.make_row(origin="AI_PROPOSED", approval="human:bob")],
                               [base.make_evidence()])
        self.assertFalse(self.trust_of(tree)[0])

    def test_unknown_origin_is_governed(self):
        tree = base.write_tree(self.root / "unknown", [base.make_row(origin="SCRAPED")], [base.make_evidence()])
        self.assertFalse(self.trust_of(tree)[0])

    def test_absent_origin_that_is_not_shipped_is_governed(self):
        row = base.make_row()
        row.pop("origin")
        tree = base.write_tree(self.root / "absent", [row], [base.make_evidence()])
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertTrue(findings)

    def test_manual_origin_with_a_plain_gate_passing_row_and_no_certified_refs_is_unchanged(self):
        # a human row whose refs are not certified keeps the gates path exactly
        row = base.make_row(fixer_ref="odooflux.rules.python.other:fix", detector_ref="odooflux.rules.python.other:d")
        tree = base.write_tree(self.root / "plain", [row], [base.make_evidence()])
        self.assertEqual(self.trust_of(tree), (True, []))


class CertifiedRefTests(HardeningBase):
    def test_certified_fixer_with_a_human_approval_and_no_record_is_untrusted(self):
        row = base.make_row(approval="human:alice")
        tree = base.write_tree(self.root / "ref-human", [row], [base.make_evidence()])
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertIn(safety.CERT_MISSING, base.codes(findings))

    def test_certified_fixer_without_a_record_file_is_untrusted_whatever_the_origin(self):
        for origin in ("MANUAL", "BUILTIN", "GENERATED"):
            with self.subTest(origin=origin):
                tree = base.write_tree(self.root / f"ref-{origin}", [base.make_row(origin=origin)],
                                       [base.make_evidence()])
                self.assertFalse(self.trust_of(tree)[0])

    def test_certified_detector_alone_also_governs_the_row(self):
        row = base.make_row(fixer_ref="odooflux.rules.python.other:fix")
        tree = base.write_tree(self.root / "det", [row], [base.make_evidence()])
        self.assertIn(safety.CERT_MISSING, base.codes(self.trust_of(tree)[1]))

    def test_certified_row_with_a_human_approval_and_a_valid_record_is_refused(self):
        evidence = [base.make_evidence()]
        record = cert.issue(base.make_row(), evidence, source_confidentiality=base.CONFIDENTIALITY,
                            change_class=CHANGE_CLASS)
        row = base.make_row(approval="human:alice")
        tree = base.write_tree(self.root / "ref-valid-human", [row], evidence)
        base.store_record(tree, RULE_ID, record)
        trusted, findings = self.trust_of(tree)
        self.assertFalse(trusted)
        self.assertIn(safety.CERT_APPROVAL_MISMATCH, base.codes(findings))

    def test_certified_row_with_no_approval_and_a_valid_record_still_verifies_through_the_record(self):
        # approval may be absent on a certified-ref row: the record decides (existing record-only path)
        evidence = [base.make_evidence()]
        record = cert.issue(base.make_row(), evidence, source_confidentiality=base.CONFIDENTIALITY,
                            change_class=CHANGE_CLASS)
        tree = base.write_tree(self.root / "ref-record", [base.make_row()], evidence)
        base.store_record(tree, RULE_ID, record)
        with mock.patch.object(safety, "confirmed_class", lambda *args: (CHANGE_CLASS, [])):
            self.assertEqual(self.trust_of(tree), (True, []))


class PackageAndLoadBoundaryTests(HardeningBase):
    def test_package_import_refuses_a_generated_row_with_a_human_approval(self):
        row = base.make_row(origin="GENERATED", approval="human:alice")
        tree = base.write_tree(self.root / "pkg", [row], [base.make_evidence()], provenance=None)
        findings, inherited, _ = safety.package_fix_findings(tree, inherit=False)
        self.assertTrue(findings)
        self.assertEqual(inherited, [])

    def test_gate_only_helper_is_unchanged(self):
        # the gate functions still answer exactly as before for a row that passes gates 1 to 5
        tree = base.write_tree(self.root / "gates", [base.make_row(origin="GENERATED")], [base.make_evidence()])
        self.assertEqual(safety.fix_gate_findings(tree), [])


if __name__ == "__main__":
    unittest.main()
