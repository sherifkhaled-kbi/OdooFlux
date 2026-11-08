"""TST-005-014 (REQ-JS-004, REQ-JS-001): JS syntax validator and detect-only downgrade, both modes.

Without a parser adapter the validator reports UNAVAILABLE and the JS rule layer downgrades to
NEEDS_REVIEW. The adapter-available branch is exercised with an injected test double. The real
tree-sitter adapter is not implemented (T027/T028 skipped, D-02 pending).
"""

import json
import unittest

from .. import _setup  # noqa: F401  (src first on sys.path)
from .._setup import REPO
from odooflux.core.contracts.records import Edit, ValidationResult
from odooflux.validation.syntax.javascript import (
    JavaScriptSyntaxValidator,
    detect_only_plan,
)

CORPUS = REPO / "tests" / "golden_fixtures" / "transformations" / "js"


class FakeAdapter:
    """Test double with the adapter shape: ``available()`` and ``has_errors(text)``."""

    def __init__(self, available=True, errors=False):
        self._available = available
        self._errors = errors
        self.calls = []

    def available(self):
        return self._available

    def has_errors(self, text):
        self.calls.append(text)
        return self._errors


def corpus_cases():
    return sorted(path for path in CORPUS.iterdir() if (path / "meta.json").is_file())


def read_case(case):
    text = (case / "input.js").read_bytes().decode("utf-8")
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
    return text, meta


class JavaScriptValidatorUnavailableTests(unittest.TestCase):
    """Default mode: no adapter installed."""

    def test_applies_to_javascript_only(self):
        validator = JavaScriptSyntaxValidator()
        self.assertTrue(validator.applies_to("web/static/src/a.js"))
        self.assertFalse(validator.applies_to("models/a.py"))
        self.assertFalse(validator.applies_to("views/a.xml"))

    def test_registry_metadata(self):
        validator = JavaScriptSyntaxValidator()
        self.assertEqual(validator.key, "syntax.javascript")
        self.assertEqual(validator.layer, 1)

    def test_every_corpus_case_is_unavailable_without_adapter(self):
        validator = JavaScriptSyntaxValidator()
        for case in corpus_cases():
            with self.subTest(case=case.name):
                text, _ = read_case(case)
                result = validator.validate("web/static/src/a.js", text)
                self.assertEqual(result.outcome, "UNAVAILABLE")
                self.assertTrue(result.reason)

    def test_unavailable_when_adapter_reports_not_available(self):
        validator = JavaScriptSyntaxValidator(adapter=FakeAdapter(available=False))
        self.assertEqual(validator.validate("a.js", "var x = 1;").outcome, "UNAVAILABLE")

    def test_unavailable_when_adapter_cannot_decide(self):
        validator = JavaScriptSyntaxValidator(adapter=FakeAdapter(errors=None))
        self.assertEqual(validator.validate("a.js", "var x = 1;").outcome, "UNAVAILABLE")

    def test_unavailable_never_fails_a_file(self):
        result = JavaScriptSyntaxValidator().validate("a.js", "var = ;")
        self.assertNotEqual(result.outcome, "FAIL")
        self.assertIsInstance(result, ValidationResult)


class JavaScriptValidatorAdapterTests(unittest.TestCase):
    """Adapter-available branch, with an injected double (no real parser is installed)."""

    def test_error_nodes_fail_validation(self):
        adapter = FakeAdapter(errors=True)
        result = JavaScriptSyntaxValidator(adapter=adapter).validate("a.js", "odoo.define(")
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("error", result.reason)
        self.assertEqual(adapter.calls, ["odoo.define("])

    def test_clean_tree_passes_validation(self):
        result = JavaScriptSyntaxValidator(adapter=FakeAdapter(errors=False)).validate("a.js", "var x = 1;")
        self.assertEqual(result.outcome, "PASS")

    def test_corpus_outcomes_follow_the_adapter_verdict(self):
        for case in corpus_cases():
            with self.subTest(case=case.name):
                text, meta = read_case(case)
                broken = meta["syntax"] == "broken"
                validator = JavaScriptSyntaxValidator(adapter=FakeAdapter(errors=broken))
                expected = "FAIL" if broken else "PASS"
                self.assertEqual(validator.validate("a.js", text).outcome, expected)


class DetectOnlyDowngradeTests(unittest.TestCase):
    def edit(self):
        return Edit(path="web/static/src/a.js", start=0, end=3, before="odo", after="ODO")

    def test_without_adapter_detections_downgrade_to_needs_review(self):
        edits, floor = detect_only_plan(None, [self.edit()], ["finding"])
        self.assertEqual(edits, [])
        self.assertEqual(floor, "NEEDS_REVIEW")

    def test_without_adapter_edits_are_dropped_even_without_findings(self):
        edits, floor = detect_only_plan(None, [self.edit()], [])
        self.assertEqual(edits, [])
        self.assertEqual(floor, "NEEDS_REVIEW")

    def test_without_adapter_and_nothing_detected_has_no_floor(self):
        self.assertEqual(detect_only_plan(None, [], []), ([], None))

    def test_unavailable_adapter_is_treated_as_absent(self):
        edits, floor = detect_only_plan(FakeAdapter(available=False), [], ["finding"])
        self.assertEqual((edits, floor), ([], "NEEDS_REVIEW"))

    def test_with_adapter_edits_pass_through_without_floor(self):
        edit = self.edit()
        edits, floor = detect_only_plan(FakeAdapter(available=True), [edit], ["finding"])
        self.assertEqual(edits, [edit])
        self.assertIsNone(floor)


if __name__ == "__main__":
    unittest.main()
