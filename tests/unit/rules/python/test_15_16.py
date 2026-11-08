"""TST-006-021 (REQ-PY-002, REQ-PY-003): rules for 15.0 -> 16.0.

- ``15-16.python.search-args-keyword`` (FIX, EV-013): ``search(args=...)`` keyword renamed to ``domain``. Only
  ``search`` is bound: the location evidence covers ``search`` alone (EV-013 line 150).
- ``15-16.python.x2many-limit-attribute`` (DETECT, EV-013): the ``limit`` keyword of field calls. Detect only: the
  removal claim is description-only in EV-013 (no location).
- ``15-16.python.removed-field-attributes`` (FIX, EV-014): ``column_format`` removed from field calls (location at
  EV-014 line 167). ``deprecated`` is not bound: its removal is description-only in EV-014.
- ``15-16.python.browse-str-ids`` (DETECT, EV-013), ``15-16.python.deprecated-model-methods`` (DETECT, EV-013),
  ``15-16.python.fields-view-get`` (DETECT review, EV-107).
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

SEARCH = "15-16.python.search-args-keyword"
X2MANY = "15-16.python.x2many-limit-attribute"
FIELD_ATTRS = "15-16.python.removed-field-attributes"
BROWSE = "15-16.python.browse-str-ids"
DEPRECATED = "15-16.python.deprecated-model-methods"
FIELDS_VIEW_GET = "15-16.python.fields-view-get"
PATH = "m.py"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def run_fix(rule_id, src):
    rule = bound(rule_id)
    document = Document.from_text(PATH, src)
    result = apply_edits(document, rule.fix(document), precedence=[rule_id])
    second = rule.fix(Document.from_text(PATH, result.text))
    return result.text, second


def detect(rule_id, src):
    return bound(rule_id).detect(Document.from_text(PATH, src))


class SearchArgsTests(unittest.TestCase):
    def test_search_args_keyword_is_renamed_to_domain(self):
        text, _ = run_fix(SEARCH, "recs = self.search(args=[('a', '=', 1)])\n")
        self.assertEqual(text, "recs = self.search(domain=[('a', '=', 1)])\n")

    def test_receiver_chain_is_matched_and_other_keywords_kept(self):
        text, _ = run_fix(SEARCH, "recs = self.env['res.partner'].search(args=dom, limit=1)\n")
        self.assertEqual(text, "recs = self.env['res.partner'].search(domain=dom, limit=1)\n")

    def test_detector_reports_each_occurrence(self):
        findings = detect(SEARCH, "a = self.search(args=d1)\nb = self.search(args=d2)\n")
        self.assertEqual([f.line for f in findings], [1, 2])

    def test_positional_domain_is_untouched(self):
        text, second = run_fix(SEARCH, "recs = self.search([('a', '=', 1)])\n")
        self.assertEqual(text, "recs = self.search([('a', '=', 1)])\n")
        self.assertEqual(second, [])

    def test_already_renamed_keyword_is_untouched(self):
        self.assertEqual(detect(SEARCH, "recs = self.search(domain=dom)\n"), [])

    def test_search_count_is_not_bound(self):
        self.assertEqual(detect(SEARCH, "n = self.search_count(args=dom)\n"), [])

    def test_fixed_text_is_idempotent(self):
        _, second = run_fix(SEARCH, "recs = self.search(args=dom)\n")
        self.assertEqual(second, [])


class X2ManyLimitTests(unittest.TestCase):
    def test_limit_on_field_call_is_reported(self):
        findings = detect(X2MANY, "lines = fields.One2many('line', 'order', limit=5)\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_field_without_limit_is_not_reported(self):
        self.assertEqual(detect(X2MANY, "lines = fields.One2many('line', 'order')\n"), [])

    def test_limit_on_other_callee_is_not_reported(self):
        self.assertEqual(detect(X2MANY, "x = models.One2many('a', 'b', limit=5)\n"), [])

    def test_rule_is_detect_only_without_a_fixer(self):
        rule = bound(X2MANY)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertIsNone(rule.fixer)
        self.assertFalse(rule.review_required)


class FieldAttributesTests(unittest.TestCase):
    def test_column_format_is_removed_from_field_call(self):
        text, _ = run_fix(FIELD_ATTRS, "body = fields.Html(string='B', column_format='x')\n")
        self.assertEqual(text, "body = fields.Html(string='B')\n")

    def test_column_format_is_reported(self):
        findings = detect(FIELD_ATTRS, "body = fields.Html(column_format='x')\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_other_callee_is_untouched(self):
        text, second = run_fix(FIELD_ATTRS, "x = models.Html(column_format='x')\n")
        self.assertEqual(text, "x = models.Html(column_format='x')\n")
        self.assertEqual(second, [])

    def test_fixed_text_is_idempotent(self):
        _, second = run_fix(FIELD_ATTRS, "body = fields.Html(column_format='x')\n")
        self.assertEqual(second, [])


class BrowseStrIdsTests(unittest.TestCase):
    def test_browse_with_string_id_is_reported(self):
        self.assertEqual([f.line for f in detect(BROWSE, "rec = self.env['x'].browse('5')\n")], [1])

    def test_browse_with_string_list_is_reported(self):
        self.assertEqual(len(detect(BROWSE, "recs = self.browse(['1', '2'])\n")), 1)

    def test_browse_with_integer_or_variable_is_not_reported(self):
        self.assertEqual(detect(BROWSE, "a = self.browse(5)\nb = self.browse(ids)\nc = self.browse([1, 2])\n"), [])

    def test_rule_is_detect_only_and_not_review_required(self):
        rule = bound(BROWSE)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertFalse(rule.review_required)
        self.assertIsNone(rule.fixer)


class DeprecatedModelMethodsTests(unittest.TestCase):
    def test_fields_get_keys_and_get_xml_id_calls_are_reported(self):
        findings = detect(DEPRECATED, "keys = self.fields_get_keys()\nxid = rec.get_xml_id()\n")
        self.assertEqual([f.line for f in findings], [1, 2])

    def test_fields_get_and_similar_names_are_not_reported(self):
        self.assertEqual(detect(DEPRECATED, "f = self.fields_get()\ng = rec.get_xml_id_map()\n"), [])

    def test_rule_is_detect_only_and_not_review_required(self):
        rule = bound(DEPRECATED)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertFalse(rule.review_required)


class FieldsViewGetTests(unittest.TestCase):
    def test_fields_view_get_override_is_reported(self):
        src = "class A(models.Model):\n    def fields_view_get(self, view_id=None):\n        return {}\n"
        self.assertEqual([f.line for f in detect(FIELDS_VIEW_GET, src)], [2])

    def test_fields_view_get_call_and_get_view_are_not_reported(self):
        src = "class A(models.Model):\n    def f(self):\n        self.fields_view_get()\n        self.get_view()\n"
        self.assertEqual(detect(FIELDS_VIEW_GET, src), [])

    def test_rule_is_detect_only_review_required_without_a_fixer(self):
        rule = bound(FIELDS_VIEW_GET)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertTrue(rule.review_required)
        self.assertIsNone(rule.fixer)


class CatalogueTests(unittest.TestCase):
    def test_tests_are_recorded_for_each_rule(self):
        expected = {SEARCH: ("positive", "negative", "idempotence"), FIELD_ATTRS: ("positive", "negative", "idempotence")}
        for rule_id in (SEARCH, X2MANY, FIELD_ATTRS, BROWSE, DEPRECATED, FIELDS_VIEW_GET):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            kinds = expected.get(rule_id, ("positive", "negative"))
            self.assertEqual(set(meta["tests"]), set(kinds), rule_id)
            self.assertEqual(meta["tests"]["positive"], "TST-006-021", rule_id)


if __name__ == "__main__":
    unittest.main()
