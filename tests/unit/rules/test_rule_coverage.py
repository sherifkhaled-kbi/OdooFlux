"""TST-006-001 (REQ-TST-002, REQ-PY-003): every registered rule carries the tests its maturity requires.

Required tests come from data-model.md: FIX_ENABLED needs a fixer and positive, negative and
idempotence tests; DETECT_ONLY needs positive and negative tests; a review-required rule has no
fixer. ``review_required`` is not in the rule schema, so it is read with a default of false.
"""

import unittest

from odooflux.knowledge.loader import load_knowledge

FIX_TESTS = ("positive", "negative", "idempotence")
DETECT_TESTS = ("positive", "negative")


def coverage_problems(rules) -> list:
    """Return ``"<rule id>: <problem>"`` strings for every rule that breaks the coverage contract."""
    problems = []
    for rule in rules:
        rid = rule.get("id", "?")
        tests = rule.get("tests") or {}
        maturity = rule.get("maturity")
        if rule.get("review_required", False) and rule.get("fixer_ref") is not None:
            problems.append(f"{rid}: review_required rule must not have a fixer")
        if maturity == "FIX_ENABLED":
            if not rule.get("fixer_ref"):
                problems.append(f"{rid}: FIX_ENABLED rule has no fixer")
            required = FIX_TESTS
        elif maturity == "DETECT_ONLY":
            required = DETECT_TESTS
        else:
            continue
        for kind in required:
            if not tests.get(kind):
                problems.append(f"{rid}: missing {kind} test")
    return problems


def _fix_rule(**overrides):
    rule = {
        "id": "17-18.python.fixture-rule",
        "step": "17-18",
        "maturity": "FIX_ENABLED",
        "fixer_ref": "odooflux.rules.python.generic:rename_keyword",
        "tests": {"positive": "TST-006-900", "negative": "TST-006-901", "idempotence": "TST-006-902"},
    }
    rule.update(overrides)
    return rule


class RuleCoverageTests(unittest.TestCase):
    def test_registered_rules_have_required_tests(self):
        rules = load_knowledge().rules
        self.assertEqual(coverage_problems(rules), [])

    def test_complete_fix_rule_passes(self):
        self.assertEqual(coverage_problems([_fix_rule()]), [])

    def test_fix_rule_missing_idempotence_fails(self):
        rule = _fix_rule(tests={"positive": "TST-006-900", "negative": "TST-006-901"})
        self.assertEqual(coverage_problems([rule]), ["17-18.python.fixture-rule: missing idempotence test"])

    def test_detect_only_rule_missing_negative_fails(self):
        rule = _fix_rule(maturity="DETECT_ONLY", fixer_ref=None, tests={"positive": "TST-006-900"})
        self.assertEqual(coverage_problems([rule]), ["17-18.python.fixture-rule: missing negative test"])

    def test_detect_only_rule_with_both_tests_passes(self):
        rule = _fix_rule(maturity="DETECT_ONLY", fixer_ref=None,
                         tests={"positive": "TST-006-900", "negative": "TST-006-901"})
        self.assertEqual(coverage_problems([rule]), [])

    def test_review_required_rule_with_fixer_fails(self):
        rule = _fix_rule(maturity="DETECT_ONLY", review_required=True)
        self.assertEqual(coverage_problems([rule]),
                         ["17-18.python.fixture-rule: review_required rule must not have a fixer"])


if __name__ == "__main__":
    unittest.main()
