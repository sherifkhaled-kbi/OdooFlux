"""TST-004-003 (REQ-EVD-001, REQ-EVD-003): rules need evidence; unverified evidence caps maturity."""

import json
import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.shared.loader import resolve_rules

from .helpers import codes, copy_fixture


def _rules(root, rules):
    (root / "compatibility" / "16-17.rules.json").write_text(json.dumps(rules), encoding="utf-8")
    return load_knowledge(root)


def _rule(**over):
    base = {"id": "16-17.python.name-get-deprecated", "step": "16-17", "category": "python", "maturity": "FIX_ENABLED",
            "risk": "LOW", "evidence": ["EV-001"], "detector_ref": None, "fixer_ref": None, "tests": []}
    base.update(over)
    return base


class RuleEvidenceTests(unittest.TestCase):
    def test_rule_without_evidence_fails_loading(self):
        root = copy_fixture("valid")
        kb = _rules(root, [_rule(evidence=[])])
        with self.assertRaisesRegex(ValueError, "rule 16-17.python.name-get-deprecated: missing evidence"):
            resolve_rules(kb)

    def test_unknown_evidence_id_is_rejected(self):
        root = copy_fixture("valid")
        kb = _rules(root, [_rule(evidence=["EV-404"])])
        with self.assertRaisesRegex(ValueError, "unknown evidence EV-404"):
            resolve_rules(kb)

    def test_unverified_evidence_caps_fix_enabled_and_warns(self):
        root = copy_fixture("valid")
        path = root / "evidence" / "EV-001.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = "UNVERIFIED"
        path.write_text(json.dumps(record), encoding="utf-8")
        kb = _rules(root, [_rule()])
        rules, warnings = resolve_rules(kb)
        self.assertEqual(rules[0]["effective_maturity"], "DETECT_ONLY")
        self.assertTrue(any("capped to DETECT_ONLY" in w for w in warnings))
        self.assertIn("W001", codes(root))

    def test_conflicting_evidence_also_caps(self):
        root = copy_fixture("valid")
        path = root / "evidence" / "EV-001.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["status"] = "CONFLICTING"
        path.write_text(json.dumps(record), encoding="utf-8")
        rules, _ = resolve_rules(_rules(root, [_rule()]))
        self.assertEqual(rules[0]["effective_maturity"], "DETECT_ONLY")

    def test_shared_rule_not_applicable_is_accepted(self):
        root = copy_fixture("valid")
        kb = _rules(root, [_rule(id="*.any.encoding-hygiene", step="*", category="any", evidence=[],
                                 not_applicable_reason="shared hygiene rule; no official claim applies")])
        rules, _ = resolve_rules(kb)
        self.assertEqual(rules[0]["effective_maturity"], "FIX_ENABLED")

    def test_validator_reports_missing_evidence_as_e005(self):
        root = copy_fixture("valid")
        self.assertIn("E005", codes(root) | (lambda: codes(_make_e005(root)))())


def _make_e005(root):
    _rules(root, [_rule(evidence=[])])
    return root


if __name__ == "__main__":
    unittest.main()
