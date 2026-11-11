"""Experimental attrs/states fixer inside inherited views (AF-6, roadmap section 3 strict subset).

Inherited view records (``<field name="arch">`` of a record that has ``inherit_id``) carry their changes in ``<xpath>``
elements. Two forms are converted, only for the strict subset of the plain-form fixer:

* ``<xpath position="attributes"><attribute name="attrs">{...}</attribute></xpath>`` becomes one
  ``<attribute name="<key>">expression</attribute>`` per key;
* an element added by an ``inside|after|before|replace`` xpath that carries ``attrs=``/``states=`` is converted as in a
  plain form.

An xpath is trusted only when its expression names a ``form`` (the target view cannot be known from one module). Every
other shape is left byte-identical and refused with a reason. Unit layer: no file is read, no CLI is run.
"""

import ast
import unittest
import xml.etree.ElementTree as ET

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.rules.experimental import xml_modifiers as xm
from odooflux.rules.shared.emit import RuleContext
from tests.unit.test_experimental_xml_modifiers import odoo_domain_holds, python_expression_holds, records

ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"
PATH = "v.xml"
FORM_FIELD = "//form//field[@name='a']"


def ctx(rule_id):
    return RuleContext(rule_id=rule_id, severity="CRITICAL", step="16-17")


def convert(text, rule_id=ATTRS):
    document = Document.from_text(PATH, text)
    fn = xm.plan_attrs if rule_id == ATTRS else xm.plan_states
    result = fn(document, ctx(rule_id))
    if not result.edits:
        return text, result
    return apply_edits(document, result.edits, precedence=[rule_id]).text, result


def refusals(text, rule_id=ATTRS):
    fn = xm.plan_attrs if rule_id == ATTRS else xm.plan_states
    return [r.reason for r in fn(Document.from_text(PATH, text)).refused]


def inherited(inner, inherit=True):
    """A view record. With ``inherit`` it has an ``inherit_id`` and its arch is an inherited view."""
    inherit_field = '<field name="inherit_id" ref="base.view_x"/>' if inherit else ""
    return (f'<odoo><record id="v_inh" model="ir.ui.view"><field name="name">v.inh</field>'
            f'<field name="model">kbi.exp</field>{inherit_field}'
            f'<field name="arch" type="xml">{inner}</field></record></odoo>')


def xpath(expr, position, inner):
    return f'<xpath expr="{expr}" position="{position}">{inner}</xpath>'


def attrs_xpath(expr, dict_text):
    """An ``attributes`` xpath whose ``<attribute name="attrs">`` text is ``dict_text`` (XML-escaped by the caller)."""
    return xpath(expr, "attributes", f'<attribute name="attrs">{dict_text}</attribute>')


FORM_EXPR = "//form//field[@name='a']"

# ---- supported cases ---------------------------------------------------------------------------------------------

SUPPORTED = {
    "attributes-single-key": (
        attrs_xpath(FORM_EXPR, "{'invisible': [('state', '=', 'done')]}"),
        xpath(FORM_EXPR, "attributes", '<attribute name="invisible">state == \'done\'</attribute>')),
    "attributes-two-keys": (
        attrs_xpath(FORM_EXPR, "{'invisible': [('x', '=', 1)], 'readonly': [('y', 'in', ['a', 'b'])]}"),
        xpath(FORM_EXPR, "attributes", '<attribute name="invisible">x == 1</attribute>\n'
                                       '<attribute name="readonly">y in [\'a\', \'b\']</attribute>')),
    "attributes-or-not": (
        attrs_xpath("//form//button[@name='go']", "{'required': ['!', ('a', '=', 1)]}"),
        xpath("//form//button[@name='go']", "attributes",
              '<attribute name="required">not (a == 1)</attribute>')),
    "inside-plain-field": (
        xpath("//form//sheet", "inside", '<field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
        xpath("//form//sheet", "inside", '<field name="a" invisible="x == 1"/>')),
    "after-plain-field": (
        xpath("//form//group", "after", '<field name="a" attrs="{\'readonly\': [(\'x\', \'!=\', 2)]}"/>'),
        xpath("//form//group", "after", '<field name="a" readonly="x != 2"/>')),
    "before-plain-field": (
        xpath("//form//group", "before", '<field name="a" attrs="{\'required\': [(\'x\', \'in\', [1, 2])]}"/>'),
        xpath("//form//group", "before", '<field name="a" required="x in [1, 2]"/>')),
    "replace-plain-field": (
        xpath("//form//field[@name='b']", "replace", '<field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
        xpath("//form//field[@name='b']", "replace", '<field name="a" invisible="x == 1"/>')),
}


class SupportedInheritedTests(unittest.TestCase):
    def test_each_supported_case_converts_to_the_expected_xml(self):
        for name, (before, after) in SUPPORTED.items():
            with self.subTest(case=name):
                text, result = convert(inherited(before))
                self.assertEqual(text, inherited(after))
                self.assertEqual(result.refused, ())

    def test_attributes_form_records_one_conversion_per_element(self):
        _, result = convert(inherited(SUPPORTED["attributes-two-keys"][0]))
        self.assertEqual(len(result.converted), 1)
        record = result.converted[0]
        self.assertEqual(record.rule_id, ATTRS)
        self.assertEqual(record.element, "attribute")
        self.assertIn("attrs", record.before)
        self.assertIn('name="invisible"', record.after)
        self.assertIn('name="readonly"', record.after)

    def test_states_inside_a_form_xpath_becomes_invisible(self):
        before = xpath(FORM_EXPR, "inside", '<button name="go" states="draft,sent"/>')
        text, result = convert(inherited(before), STATES)
        self.assertEqual(text, inherited(xpath(FORM_EXPR, "inside",
                                               '<button name="go" invisible="state not in [\'draft\',\'sent\']"/>')))
        self.assertEqual(result.refused, ())

    def test_only_the_converted_xpath_changes(self):
        other = xpath("//form//field[@name='c']", "after", '<field name="c"/>')
        before = other + SUPPORTED["inside-plain-field"][0]
        text, _ = convert(inherited(before))
        self.assertEqual(text, inherited(other + SUPPORTED["inside-plain-field"][1]))


# ---- refusals: every excluded shape stays byte-identical and carries a reason ------------------------------------

REFUSED = [
    ("attributes-falsy-literal", attrs_xpath(FORM_EXPR, "{'invisible': [('amount', '=', 0)]}"), "falsy-literal"),
    ("attributes-dotted-field", attrs_xpath(FORM_EXPR, "{'invisible': [('parent.state', '=', 'x')]}"),
     "dotted-field"),
    ("attributes-context-name", attrs_xpath(FORM_EXPR, "{'invisible': [('x', '=', uid)]}"), "context-name"),
    ("attributes-unsupported-key", attrs_xpath(FORM_EXPR, "{'column_invisible': [('x', '=', 1)]}"),
     "unsupported-key:column_invisible"),
    ("attributes-malformed", attrs_xpath(FORM_EXPR, "[('x', '=', 1)]"), "malformed-attrs"),
    ("attributes-empty", attrs_xpath(FORM_EXPR, "{}"), "empty-attrs"),
    ("attributes-self-closing", xpath(FORM_EXPR, "attributes", '<attribute name="attrs"/>'), "malformed-attrs"),
    ("attributes-extra-attr", xpath(FORM_EXPR, "attributes",
                                    '<attribute name="attrs" add="x">{\'invisible\': [(\'x\', \'=\', 1)]}</attribute>'),
     "malformed-attribute"),
    ("attributes-existing-modifier", xpath(FORM_EXPR, "attributes",
                                           '<attribute name="invisible">1</attribute>'
                                           '<attribute name="attrs">{\'invisible\': [(\'x\', \'=\', 1)]}</attribute>'),
     "same-modifier-exists:invisible"),
    ("attributes-target-not-form", attrs_xpath("//field[@name='a']", "{'invisible': [('x', '=', 1)]}"),
     "inherited-target-not-form"),
    ("attributes-target-tree", attrs_xpath("//tree//field[@name='a']", "{'invisible': [('x', '=', 1)]}"),
     "nested-view"),
    ("attributes-under-inside-xpath", xpath(FORM_EXPR, "inside",
                                            '<attribute name="attrs">{\'invisible\': [(\'x\', \'=\', 1)]}</attribute>'),
     "unsupported-position"),
    ("plain-falsy-literal", xpath(FORM_EXPR, "inside",
                                  '<field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 0)]}"/>'),
     "falsy-literal"),
    ("plain-dotted-field", xpath(FORM_EXPR, "inside",
                                 '<field name="a" attrs="{\'invisible\': [(\'parent.x\', \'=\', 1)]}"/>'),
     "dotted-field"),
    ("plain-context-name", xpath(FORM_EXPR, "inside",
                                 '<field name="a" attrs="{\'invisible\': [(\'x\', \'=\', context.get(\'k\'))]}"/>'),
     "context-name"),
    ("plain-existing-modifier", xpath(FORM_EXPR, "inside",
                                      '<field name="a" invisible="1" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
     "same-modifier-exists:invisible"),
    ("plain-nested-tree", xpath("//form//field[@name='a']", "inside",
                                '<tree><field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/></tree>'),
     "nested-view"),
    ("plain-nested-kanban", xpath("//form//field[@name='a']", "inside",
                                  '<kanban><field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/></kanban>'),
     "nested-view"),
    ("plain-target-not-form", xpath("//field[@name='a']", "after",
                                    '<field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
     "inherited-target-not-form"),
    ("plain-target-list-view", xpath("//tree", "inside",
                                     '<field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
     "nested-view"),
    ("plain-unsupported-position", xpath(FORM_EXPR, "move",
                                         '<field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
     "unsupported-position"),
    ("plain-element-with-position", xpath(FORM_EXPR, "inside",
                                          '<field name="b" position="after" '
                                          'attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'),
     "position-element"),
]


class RefusedInheritedTests(unittest.TestCase):
    def test_each_excluded_shape_is_untouched_and_refused_with_reason(self):
        for name, inner, reason in REFUSED:
            with self.subTest(case=name):
                text = inherited(inner)
                new_text, result = convert(text)
                self.assertEqual(new_text, text)
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], [reason])

    def test_refusal_records_have_the_same_shape_as_the_plain_form(self):
        text = inherited(attrs_xpath(FORM_EXPR, "{'invisible': [('x', '=', 0)]}"))
        (refusal,) = xm.plan_attrs(Document.from_text(PATH, text)).refused
        self.assertEqual(refusal.rule_id, ATTRS)
        self.assertEqual(refusal.reason, "falsy-literal")
        self.assertEqual(refusal.element, "attribute")
        self.assertEqual(refusal.line, 1)

    def test_attributes_outside_an_inherited_view_is_refused(self):
        text = inherited(attrs_xpath(FORM_EXPR, "{'invisible': [('x', '=', 1)]}"), inherit=False)
        self.assertEqual(refusals(text), ["not-inherited-view"])
        self.assertEqual(convert(text)[0], text)

    def test_plain_element_outside_form_and_xpath_keeps_the_plain_reason(self):
        text = inherited('<div><field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/></div>',
                         inherit=False)
        self.assertEqual(refusals(text), ["not-in-form"])
        self.assertEqual(convert(text)[0], text)

    def test_states_in_an_inherited_xpath_with_states_attr_on_same_element_is_refused(self):
        button = '<button name="go" states="draft" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'
        before = xpath(FORM_EXPR, "inside", button)
        self.assertEqual(refusals(inherited(before), STATES), ["states-with-attrs"])
        self.assertEqual(convert(inherited(before), STATES)[0], inherited(before))


# ---- idempotence, output shape, differential ---------------------------------------------------------------------

class InheritedIdempotenceTests(unittest.TestCase):
    def test_second_application_yields_no_edits_and_identical_bytes(self):
        for name, (before, _after) in SUPPORTED.items():
            with self.subTest(case=name):
                once, _ = convert(inherited(before))
                twice, result = convert(once)
                self.assertEqual(result.edits, ())
                self.assertEqual(twice, once)

    def test_refused_shapes_are_not_edited_on_a_second_pass(self):
        for name, inner, _reason in REFUSED:
            with self.subTest(case=name):
                once, _ = convert(inherited(inner))
                twice, result = convert(once)
                self.assertEqual(result.edits, ())
                self.assertEqual(twice, once)


class InheritedOutputShapeTests(unittest.TestCase):
    def test_converted_output_is_well_formed_and_has_no_attrs_or_states(self):
        before = "".join(value for value, _ in SUPPORTED.values())
        text = inherited(before + xpath(FORM_EXPR, "inside", '<button name="go" states="draft,sent"/>'))
        after_attrs, _ = convert(text)
        new_text, _ = convert(after_attrs, STATES)
        root = ET.fromstring(new_text)  # stdlib parse: the output is well-formed XML
        self.assertEqual(root.findall(".//*[@attrs]"), [])
        self.assertEqual(root.findall(".//*[@states]"), [])
        self.assertEqual([el for el in root.iter("attribute") if el.get("name") == "attrs"], [])


class InheritedDifferentialTests(unittest.TestCase):
    def test_attributes_expression_agrees_with_the_old_domain_on_every_record(self):
        cases = {
            "eq-in": "{'invisible': ['|', ('state', '=', 'a'), ('amount', 'in', [1, 'b'])]}",
            "not-equal": "{'readonly': [('state', '!=', 'draft'), ('flag', '=', True)]}",
        }
        checked, mismatches = 0, []
        for name, attrs in cases.items():
            new_text, result = convert(inherited(attrs_xpath(FORM_EXPR, attrs)))
            self.assertEqual(result.refused, (), name)
            root = ET.fromstring(new_text)
            key = next(iter(ast.literal_eval(attrs)))
            expression = next(el.text for el in root.iter("attribute") if el.get("name") == key)
            domain = ast.literal_eval(attrs)[key]
            for record in records(("state", "amount", "flag")):
                checked += 1
                if odoo_domain_holds(domain, record) != python_expression_holds(expression, record):
                    mismatches.append((name, record))
        self.assertGreater(checked, 1000)
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
