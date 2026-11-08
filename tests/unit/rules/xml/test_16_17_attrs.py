"""TST-006-017 (REQ-XML-002): rules 16-17.xml.attrs-removed and 16-17.xml.states-attribute-removed (EV-109).

17.0 view validation rejects the ``attrs`` and ``states`` view attributes. Both rules are DETECT_ONLY. The feature 005
converter (``transformers.modifiers.convert_element``) has an undecided converter mode (G-R-20: the numeric-0
divergence in EV-384 is open), so no fixer is bound. Detection reports the attribute on every element that carries it.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"
PATH = "v.xml"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def detect(rule_id, text):
    return bound(rule_id).detect(Document.from_text(PATH, text))


ATTRS_VIEW = """<form>
  <field name="a" attrs="{'invisible': [('state', '=', 'done')]}"/>
  <field name="b"/>
  <button name="x" attrs="{'readonly': [('state', '!=', 'draft')]}"/>
</form>
"""

STATES_VIEW = """<form>
  <button name="confirm" states="draft,sent"/>
  <button name="other"/>
</form>
"""


class AttrsPositiveTests(unittest.TestCase):
    def test_attrs_attribute_is_reported_on_each_element(self):
        findings = detect(ATTRS, ATTRS_VIEW)
        self.assertEqual([f.line for f in findings], [2, 4])

    def test_finding_matches_the_attribute_value(self):
        findings = detect(ATTRS, ATTRS_VIEW)
        self.assertTrue(findings[0].matched.startswith("attrs="))


class AttrsNegativeTests(unittest.TestCase):
    def test_view_without_attrs_is_not_reported(self):
        self.assertEqual(detect(ATTRS, '<form><field name="b" invisible="1"/></form>'), [])

    def test_states_attribute_is_not_an_attrs_finding(self):
        self.assertEqual(detect(ATTRS, STATES_VIEW), [])

    def test_element_named_attrs_is_not_reported(self):
        self.assertEqual(detect(ATTRS, "<form><attrs/></form>"), [])

    def test_malformed_xml_yields_no_findings(self):
        self.assertEqual(detect(ATTRS, "<form><field attrs='x'></form>"), [])


class StatesPositiveTests(unittest.TestCase):
    def test_states_attribute_is_reported(self):
        findings = detect(STATES, STATES_VIEW)
        self.assertEqual([f.line for f in findings], [2])


class StatesNegativeTests(unittest.TestCase):
    def test_attrs_attribute_is_not_a_states_finding(self):
        self.assertEqual(detect(STATES, ATTRS_VIEW), [])

    def test_state_field_name_is_not_reported(self):
        self.assertEqual(detect(STATES, '<form><field name="state"/></form>'), [])


class ModifierDetectOnlyTests(unittest.TestCase):
    def test_both_rules_are_detect_only_without_a_fixer(self):
        for rule_id in (ATTRS, STATES):
            rule = bound(rule_id)
            self.assertEqual(rule.maturity, "DETECT_ONLY", rule_id)
            self.assertIsNone(rule.fixer, rule_id)
            self.assertFalse(rule.review_required, rule_id)

    def test_fix_is_a_no_op_so_the_document_is_unchanged(self):
        document = Document.from_text(PATH, ATTRS_VIEW)
        self.assertEqual(bound(ATTRS).fix(document), [])

    def test_suggestion_records_the_undecided_converter_mode(self):
        for rule_id in (ATTRS, STATES):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            self.assertIn("G-R-20", meta["suggestion"], rule_id)

    def test_catalogue_tests_are_recorded(self):
        for rule_id in (ATTRS, STATES):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            self.assertEqual(meta["tests"], {"positive": "TST-006-017", "negative": "TST-006-017"}, rule_id)


if __name__ == "__main__":
    unittest.main()
