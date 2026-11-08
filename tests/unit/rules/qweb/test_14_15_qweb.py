"""TST-006-022 (REQ-XML-005): rules 14-15.qweb.t-esc-deprecated (FIX) and 14-15.qweb.t-raw-deprecated (review).

``t-esc`` is replaced by ``t-out`` (EV-203 names ``t-out`` as the replacement; ``t-out`` is compiled from 15.0, EV-201).
``t-raw`` warns from 15.0 (EV-202) and is review-only. The 14.0 -> 15.0 directive diff (EV-331) adds directives and
removes none, so it yields no further rule (T017 contributes nothing to this step).
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

ESC = "14-15.qweb.t-esc-deprecated"
RAW = "14-15.qweb.t-raw-deprecated"
PATH = "t.xml"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def run_fix(src):
    rule = bound(ESC)
    document = Document.from_text(PATH, src)
    result = apply_edits(document, rule.fix(document), precedence=[ESC])
    second = rule.fix(Document.from_text(PATH, result.text))
    return result.text, second


def detect(rule_id, src):
    return bound(rule_id).detect(Document.from_text(PATH, src))


class TEscPositiveTests(unittest.TestCase):
    def test_t_esc_is_renamed_to_t_out(self):
        text, _ = run_fix('<t t-name="x"><span t-esc="record.name"/></t>')
        self.assertEqual(text, '<t t-name="x"><span t-out="record.name"/></t>')

    def test_several_t_esc_attributes_are_each_renamed(self):
        text, _ = run_fix('<div><p t-esc="a"/><p t-esc="b"/></div>')
        self.assertEqual(text, '<div><p t-out="a"/><p t-out="b"/></div>')

    def test_t_esc_is_reported(self):
        findings = detect(ESC, '<div>\n<p t-esc="a"/>\n</div>')
        self.assertEqual([f.line for f in findings], [2])


class TEscNegativeTests(unittest.TestCase):
    def test_t_out_is_untouched(self):
        src = '<span t-out="record.name"/>'
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_element_already_carrying_t_out_is_skipped(self):
        src = '<span t-esc="a" t-out="b"/>'
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_t_esc_in_text_content_is_untouched(self):
        src = "<p>use t-esc here</p>"
        text, _ = run_fix(src)
        self.assertEqual(text, src)

    def test_malformed_xml_yields_no_edits(self):
        src = '<span t-esc="a"></div>'
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])


class TEscIdempotenceTests(unittest.TestCase):
    def test_second_application_on_fixed_text_has_no_edits(self):
        _, second = run_fix('<span t-esc="a"/>')
        self.assertEqual(second, [])


class TRawReviewTests(unittest.TestCase):
    def test_t_raw_is_reported(self):
        findings = detect(RAW, '<div><p t-raw="html"/></div>')
        self.assertEqual([f.line for f in findings], [1])

    def test_t_out_and_t_esc_are_not_reported(self):
        self.assertEqual(detect(RAW, '<div><p t-out="a"/><p t-esc="b"/></div>'), [])

    def test_rule_is_detect_only_review_required_without_a_fixer(self):
        rule = bound(RAW)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertTrue(rule.review_required)
        self.assertIsNone(rule.fixer)
        self.assertEqual(bound(RAW).fix(Document.from_text(PATH, '<p t-raw="x"/>')), [])


class CatalogueTests(unittest.TestCase):
    def test_t_esc_binds_at_fix_enabled_and_not_review(self):
        rule = bound(ESC)
        self.assertEqual(rule.maturity, "FIX_ENABLED")
        self.assertFalse(rule.review_required)
        self.assertIsNotNone(rule.fixer)
        meta = next(r for r in load_knowledge().rules if r["id"] == ESC)
        self.assertEqual(meta["tests"], {"positive": "TST-006-022", "negative": "TST-006-022",
                                         "idempotence": "TST-006-022"})


if __name__ == "__main__":
    unittest.main()
