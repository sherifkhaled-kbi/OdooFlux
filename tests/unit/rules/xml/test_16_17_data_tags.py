"""TST-006-019 (REQ-XML-003): rules 16-17.xml.act-window-tag and 16-17.xml.report-tag (EV-117, EV-322, EV-323).

The ``<act_window>`` and ``<report>`` data-file tags are handled by ``tools/convert.py`` through 16.0 and are absent
in 17.0, where the loader skips them silently. Both rules are DETECT_ONLY and review-required. No fixer is bound:
the field mapping is evidenced only for the report name/string/file attributes (EV-326), and the ``<act_window>``
binding_model_id derivation is not evidenced (EV-325), so neither rewrite can be made from the evidence alone.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

ACT_WINDOW = "16-17.xml.act-window-tag"
REPORT = "16-17.xml.report-tag"
PATH = "data.xml"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def detect(rule_id, text):
    return bound(rule_id).detect(Document.from_text(PATH, text))


DATA = """<odoo>
  <act_window id="act_partner" name="Partners" res_model="res.partner"/>
  <report id="report_partner" model="res.partner" name="mod.report_partner" string="Partner" file="mod.report_partner"/>
  <record id="act_other" model="ir.actions.act_window">
    <field name="name">Other</field>
  </record>
</odoo>
"""


class ActWindowTagTests(unittest.TestCase):
    def test_act_window_tag_is_reported(self):
        findings = detect(ACT_WINDOW, DATA)
        self.assertEqual([f.line for f in findings], [2])

    def test_act_window_tag_inside_a_nested_element_is_reported(self):
        findings = detect(ACT_WINDOW, "<odoo><data><act_window id='a' name='n' res_model='m'/></data></odoo>")
        self.assertEqual(len(findings), 1)

    def test_record_with_act_window_model_is_not_reported(self):
        self.assertEqual(detect(ACT_WINDOW, '<odoo><record id="a" model="ir.actions.act_window"/></odoo>'), [])

    def test_field_named_act_window_is_not_reported(self):
        self.assertEqual(detect(ACT_WINDOW, '<odoo><field name="act_window"/></odoo>'), [])

    def test_malformed_xml_yields_no_findings(self):
        self.assertEqual(detect(ACT_WINDOW, "<odoo><act_window></odoo>"), [])


class ReportTagTests(unittest.TestCase):
    def test_report_tag_is_reported(self):
        findings = detect(REPORT, DATA)
        self.assertEqual([f.line for f in findings], [3])

    def test_record_with_report_model_is_not_reported(self):
        self.assertEqual(detect(REPORT, '<odoo><record id="r" model="ir.actions.report"/></odoo>'), [])

    def test_report_name_field_is_not_reported(self):
        self.assertEqual(detect(REPORT, '<odoo><field name="report_name">x</field></odoo>'), [])

    def test_reports_element_is_not_reported(self):
        self.assertEqual(detect(REPORT, "<odoo><reports/></odoo>"), [])


class DataTagRulesAreReviewOnlyTests(unittest.TestCase):
    def test_both_rules_are_detect_only_review_without_a_fixer(self):
        for rule_id in (ACT_WINDOW, REPORT):
            rule = bound(rule_id)
            self.assertEqual(rule.maturity, "DETECT_ONLY", rule_id)
            self.assertTrue(rule.review_required, rule_id)
            self.assertIsNone(rule.fixer, rule_id)

    def test_fix_produces_no_edits(self):
        document = Document.from_text(PATH, DATA)
        self.assertEqual(bound(ACT_WINDOW).fix(document), [])
        self.assertEqual(bound(REPORT).fix(document), [])

    def test_catalogue_tests_are_recorded(self):
        for rule_id in (ACT_WINDOW, REPORT):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            self.assertEqual(meta["tests"], {"positive": "TST-006-019", "negative": "TST-006-019"}, rule_id)


if __name__ == "__main__":
    unittest.main()
