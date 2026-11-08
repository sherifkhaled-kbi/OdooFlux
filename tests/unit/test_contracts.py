"""TST-003-004 (REQ-TRF-001): data contracts validate their required fields and invariants."""

import unittest

from odooflux.core.contracts.records import (
    Edit, Finding, MigrationStep, ModuleRef, OdooVersion, ValidationResult)

from ._setup import SRC  # noqa: F401


class ContractTests(unittest.TestCase):
    def test_constructs_each_contract(self):
        self.assertEqual(OdooVersion("14.0").major, 14)
        self.assertEqual(MigrationStep("14.0", "15.0", "RESEARCH_SEEDED").id, "14.0->15.0")
        ref = ModuleRef(name="m", path="/x/m", manifest_path=None, declared_version=None)
        self.assertEqual(ref.name, "m")
        self.assertEqual(Finding(rule_id="R", path="p", line=1, severity="INFO", message="m").status, "OPEN")

    def test_rejected_edit_requires_reason(self):
        with self.assertRaises(ValueError):
            Edit(path="p", start=0, end=1, before="a", after="b", status="REJECTED")
        Edit(path="p", start=0, end=1, before="a", after="b", status="REJECTED", rejection_reason="why")

    def test_validation_result_needs_reason_when_not_pass(self):
        with self.assertRaises(ValueError):
            ValidationResult(layer=1, outcome="FAIL")
        with self.assertRaises(ValueError):
            ValidationResult(layer=3, outcome="UNAVAILABLE")
        ValidationResult(layer=3, outcome="UNAVAILABLE", reason="no core-module list")

    def test_coverage_accepts_only_full_partial_or_none(self):
        for ok in (None, "full", "partial"):
            ValidationResult(layer=5, outcome="PASS", coverage=ok)
        with self.assertRaises(ValueError):
            ValidationResult(layer=5, outcome="PASS", coverage="most")

    def test_finding_id_is_stable_for_equal_inputs(self):
        a = Finding(rule_id="R", path="p", line=3, severity="WARNING", message="m", matched="x")
        b = Finding(rule_id="R", path="p", line=3, severity="CRITICAL", message="other", matched="x")
        self.assertEqual(a.id, b.id)
        self.assertEqual(len(a.id), 16)
        self.assertNotEqual(a.id, Finding(rule_id="R", path="p", line=4, severity="WARNING",
                                          message="m", matched="x").id)


if __name__ == "__main__":
    unittest.main()
