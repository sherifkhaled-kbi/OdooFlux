"""TST-006-005 (REQ-PY-003, REQ-EVD-001): binding rule metadata to generic detector and fixer functions.

Invalid bindings must fail loading with a message that names the rule and the specific problem.
"""

import copy
import unittest

from odooflux.core.engine.documents import Document
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import BindingError
from odooflux.rules.shared.loader import bind_rule as _bind_rule

from .. import _setup  # noqa: F401  (src first on sys.path)

PY = "odooflux.rules.python.generic:"
XML = "odooflux.rules.xml.generic:"

FIX_RULE = {
    "id": "17-18.python.group-operator-renamed",
    "step": "17-18",
    "severity": "WARNING",
    "maturity": "FIX_ENABLED",
    "review_required": False,
    "detector_ref": PY + "keyword_in_call",
    "fixer_ref": PY + "rename_keyword",
    "params": {"callee": "fields.", "keyword": "group_operator", "new_keyword": "aggregator"},
    "tests": {"positive": "TST-006-008", "negative": "TST-006-008", "idempotence": "TST-006-008"},
    "message": "Field attribute group_operator was renamed aggregator.",
    "suggestion": "Rename the keyword argument.",
}

DETECT_RULE = {
    "id": "17-18.python.name-get-removed",
    "step": "17-18",
    "severity": "WARNING",
    "maturity": "DETECT_ONLY",
    "review_required": True,
    "detector_ref": PY + "flag_method_override",
    "params": {"method": "name_get"},
    "tests": {"positive": "TST-006-009", "negative": "TST-006-009"},
}


def bind_rule(meta):
    return _bind_rule(meta, BINDABLE_MODULES)


def rule(base, **changes):
    meta = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            meta.pop(key, None)
        else:
            meta[key] = value
    return meta


class ValidBindingTests(unittest.TestCase):
    def test_fix_rule_binds_and_detects_and_fixes(self):
        bound = bind_rule(FIX_RULE)
        self.assertEqual(bound.rule_id, FIX_RULE["id"])
        self.assertEqual(bound.context.severity, "WARNING")
        document = Document.from_text("m.py", "x = fields.Char(group_operator='sum')\n")
        self.assertEqual(len(bound.detect(document)), 1)
        self.assertEqual(len(bound.fix(document)), 1)

    def test_detect_only_rule_binds_with_no_fixer(self):
        bound = bind_rule(DETECT_RULE)
        self.assertIsNone(bound.fixer)
        document = Document.from_text("m.py", "class A:\n    def name_get(self):\n        pass\n")
        self.assertEqual(len(bound.detect(document)), 1)
        self.assertEqual(bound.fix(document), [])

    def test_retired_rule_binds_without_refs_or_tests(self):
        bound = bind_rule({"id": "12-13.python.old", "step": "12-13", "severity": "INFO",
                           "maturity": "RETIRED", "review_required": False})
        self.assertIsNone(bound.detector)
        self.assertEqual(bound.detect(Document.from_text("m.py", "x = 1\n")), [])

    def test_missing_params_default_to_empty(self):
        meta = {"id": "17-18.python.draft", "step": "17-18", "severity": "INFO", "maturity": "DRAFT",
                "review_required": False}
        self.assertEqual(bind_rule(meta).detect(Document.from_text("m.py", "x = 1\n")), [])

    def test_each_function_receives_only_the_params_it_accepts(self):
        bound = bind_rule(FIX_RULE)
        self.assertEqual(bound.detector_params, {"callee": "fields.", "keyword": "group_operator"})
        self.assertEqual(bound.fixer_params, {"callee": "fields.", "keyword": "group_operator",
                                              "new_keyword": "aggregator"})


class InvalidBindingTests(unittest.TestCase):
    def assertBindingError(self, meta, *fragments):
        with self.assertRaises(BindingError) as raised:
            bind_rule(meta)
        message = str(raised.exception)
        self.assertTrue(message.startswith(f"rule {meta.get('id')}: ") or "id is required" in message, message)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_review_required_rule_with_fixer_is_rejected(self):
        self.assertBindingError(rule(FIX_RULE, review_required=True),
                                "review_required rule must not have a fixer_ref")

    def test_fix_enabled_without_fixer_is_rejected(self):
        self.assertBindingError(rule(FIX_RULE, fixer_ref=None), "FIX_ENABLED rule has no fixer_ref")

    def test_fix_enabled_missing_idempotence_test_is_rejected(self):
        meta = rule(FIX_RULE, tests={"positive": "TST-006-008", "negative": "TST-006-008"})
        self.assertBindingError(meta, "missing idempotence test")

    def test_fix_enabled_missing_positive_test_is_rejected(self):
        meta = rule(FIX_RULE, tests={"negative": "TST-006-008", "idempotence": "TST-006-008"})
        self.assertBindingError(meta, "missing positive test")

    def test_detect_only_missing_negative_test_is_rejected(self):
        meta = rule(DETECT_RULE, tests={"positive": "TST-006-009"})
        self.assertBindingError(meta, "missing negative test")

    def test_fixer_on_detect_only_rule_is_rejected(self):
        meta = rule(DETECT_RULE, review_required=False, fixer_ref=PY + "rename_keyword")
        self.assertBindingError(meta, "fixer_ref requires FIX_ENABLED maturity")

    def test_missing_detector_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref=None), "detector_ref is required")

    def test_unknown_function_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref=PY + "no_such_detector"),
                                f"detector_ref '{PY}no_such_detector' does not resolve")

    def test_unknown_module_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref="odooflux.rules.nowhere:flag_call"),
                                "does not resolve")

    def test_private_function_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref=PY + "_edit"), "does not resolve")

    def test_imported_helper_is_not_a_generic_function(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref=PY + "finding"), "does not resolve")

    def test_reference_without_colon_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, detector_ref="flag_method_override"),
                                "must look like module:function")

    def test_params_missing_a_required_argument_are_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, params={}),
                                f"params missing for detector_ref '{PY}flag_method_override': method")

    def test_params_no_bound_function_accepts_are_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, params={"method": "x", "extra": 1}),
                                "params not accepted by any bound function: extra")

    def test_params_that_are_not_a_mapping_are_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, params=["name_get"]), "params must be a mapping")

    def test_fixer_params_are_checked_against_the_fixer(self):
        meta = rule(FIX_RULE, params={"callee": "fields.", "keyword": "group_operator"})
        self.assertBindingError(meta, f"params missing for fixer_ref '{PY}rename_keyword': new_keyword")

    def test_retired_rule_with_detector_is_rejected(self):
        self.assertBindingError({"id": "12-13.python.old", "step": "12-13", "severity": "INFO",
                                 "maturity": "RETIRED", "review_required": False,
                                 "detector_ref": PY + "flag_call", "params": {"callee": "a"}},
                                "RETIRED rule must not bind a detector_ref or fixer_ref")

    def test_unknown_maturity_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, maturity="SOMETIMES"),
                                "maturity 'SOMETIMES' is not one of")

    def test_unknown_severity_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, severity="FATAL"), "severity 'FATAL' is not one of")

    def test_missing_rule_id_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, id=None), "id is required")

    def test_non_boolean_review_required_is_rejected(self):
        self.assertBindingError(rule(DETECT_RULE, review_required="yes"),
                                "review_required must be true or false")

    def test_all_problems_are_reported_together(self):
        meta = rule(FIX_RULE, review_required=True, tests={})
        with self.assertRaises(BindingError) as raised:
            bind_rule(meta)
        message = str(raised.exception)
        for fragment in ("review_required rule must not have a fixer_ref", "missing positive test",
                         "missing negative test", "missing idempotence test"):
            self.assertIn(fragment, message)


if __name__ == "__main__":
    unittest.main()
