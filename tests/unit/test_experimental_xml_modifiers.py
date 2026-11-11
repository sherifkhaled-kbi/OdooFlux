"""Experimental attrs/states fixer (roadmap T2, section 3 strict subset; AC-3, AC-4, AC-6, AC-7).

Each supported case is converted to a modifier expression; each excluded case is left untouched and refused with a
reason. A differential check evaluates the old Odoo domain against the new Python expression over a small value
universe. Unit layer: no file is read, no CLI is run.
"""

import ast
import itertools
import unittest
import xml.etree.ElementTree as ET

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.rules.experimental import xml_modifiers as xm
from odooflux.rules.shared.emit import RuleContext

ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"
PATH = "v.xml"


def ctx(rule_id):
    return RuleContext(rule_id=rule_id, severity="CRITICAL", step="16-17")


def convert(text, rule_id=ATTRS, plan=None):
    """Apply the fixer once and return (new text, plan)."""
    document = Document.from_text(PATH, text)
    fn = plan or (xm.plan_attrs if rule_id == ATTRS else xm.plan_states)
    result = fn(document, ctx(rule_id))
    if not result.edits:
        return text, result
    return apply_edits(document, result.edits, precedence=[rule_id]).text, result


def form(inner):
    return f"<form>{inner}</form>"


def refusals(text, rule_id=ATTRS):
    fn = xm.plan_attrs if rule_id == ATTRS else xm.plan_states
    return [r.reason for r in fn(Document.from_text(PATH, text)).refused]


# ---- supported cases -----------------------------------------------------------------------------------------

SUPPORTED = {
    "single-leaf-equal": ("""<field name="a" attrs="{'invisible': [('state', '=', 'done')]}"/>""",
                          """<field name="a" invisible="state == 'done'"/>"""),
    "in-list": ("""<field name="a" attrs="{'readonly': [('state', 'in', ['draft', 'sent'])]}"/>""",
                """<field name="a" readonly="state in ['draft', 'sent']"/>"""),
    "not-in-list": ("""<field name="a" attrs="{'invisible': [('state', 'not in', ['x'])]}"/>""",
                    """<field name="a" invisible="state not in ['x']"/>"""),
    "not-equal": ("""<field name="a" attrs="{'readonly': [('state', '!=', 'draft')]}"/>""",
                  """<field name="a" readonly="state != 'draft'"/>"""),
    "and-implicit": ("""<field name="a" attrs="{'invisible': [('a', '=', 1), ('b', '!=', 'z')]}"/>""",
                     """<field name="a" invisible="a == 1 and b != 'z'"/>"""),
    "or-explicit": ("""<field name="a" attrs="{'invisible': ['|', ('a', '=', 1), ('b', '=', 2)]}"/>""",
                    """<field name="a" invisible="a == 1 or b == 2"/>"""),
    "not-operator": ("""<field name="a" attrs="{'invisible': ['!', ('a', '=', 'x')]}"/>""",
                     """<field name="a" invisible="not (a == 'x')"/>"""),
    "required-key": ("""<field name="a" attrs="{'required': [('state', '=', 'draft')]}"/>""",
                     """<field name="a" required="state == 'draft'"/>"""),
    "two-keys": ("""<field name="a" attrs="{'invisible': [('x', '=', 1)], 'readonly': [('y', '=', 2)]}"/>""",
                 """<field name="a" invisible="x == 1" readonly="y == 2"/>"""),
    "boolean-true": ("""<field name="a" attrs="{'invisible': [('flag', '=', True)]}"/>""",
                     """<field name="a" invisible="flag == True"/>"""),
}


class SupportedConversionTests(unittest.TestCase):
    def test_each_supported_case_converts_to_the_expected_expression(self):
        for name, (before, after) in SUPPORTED.items():
            with self.subTest(case=name):
                text, result = convert(form(before))
                self.assertEqual(text, form(after))
                self.assertEqual(result.refused, ())

    def test_states_becomes_invisible_state_not_in(self):
        text, _ = convert(form('<button name="go" states="draft,sent"/>'), STATES)
        self.assertEqual(text, form('<button name="go" invisible="state not in [\'draft\',\'sent\']"/>'))

    def test_states_with_spaces_after_commas_is_the_same_expression(self):
        text, _ = convert(form('<button name="go" states="draft, sent"/>'), STATES)
        self.assertEqual(text, form('<button name="go" invisible="state not in [\'draft\',\'sent\']"/>'))

    def test_states_keeps_other_attributes(self):
        text, _ = convert(form('<button name="go" class="btn" states="draft"/>'), STATES)
        self.assertEqual(text, form('<button name="go" class="btn" invisible="state not in [\'draft\']"/>'))

    def test_conversion_records_before_and_after_and_rule_id(self):
        _, result = convert(form(SUPPORTED["single-leaf-equal"][0]))
        self.assertEqual(len(result.converted), 1)
        record = result.converted[0]
        self.assertEqual(record.rule_id, ATTRS)
        self.assertEqual(record.line, 1)
        self.assertIn("attrs=", record.before)
        self.assertIn("invisible=", record.after)

    def test_states_conversion_notes_the_state_field_assumption(self):
        _, result = convert(form('<button name="go" states="draft"/>'), STATES)
        self.assertIn("assumes a 'state' field", result.converted[0].note)


# ---- refusals: every excluded class stays untouched and carries a reason -----------------------------------

REFUSED = [
    ("falsy-literal-zero", "<field name='a' attrs=\"{'invisible': [('amount', '=', 0)]}\"/>", "falsy-literal"),
    ("falsy-literal-false", "<field name='a' attrs=\"{'invisible': [('x', '=', False)]}\"/>", "falsy-literal"),
    ("falsy-literal-none", "<field name='a' attrs=\"{'invisible': [('x', '=', None)]}\"/>", "falsy-literal"),
    ("falsy-literal-empty", "<field name='a' attrs=\"{'invisible': [('x', '=', '')]}\"/>", "falsy-literal"),
    ("falsy-inside-in", "<field name='a' attrs=\"{'invisible': [('x', 'in', [1, 0])]}\"/>", "falsy-literal"),
    ("dotted-field", "<field name='a' attrs=\"{'invisible': [('parent.state', '=', 'done')]}\"/>", "dotted-field"),
    ("context-value-get", "<field name='a' attrs=\"{'invisible': [('x', '=', context.get('k'))]}\"/>",
     "context-name"),
    ("context-value-name", "<field name='a' attrs=\"{'invisible': [('x', '=', uid)]}\"/>", "context-name"),
    ("unsupported-operator", "<field name='a' attrs=\"{'invisible': [('x', '&lt;', 3)]}\"/>",
     "unsupported-operator:<"),
    ("unsupported-operator-double-equal", "<field name='a' attrs=\"{'invisible': [('x', '==', 3)]}\"/>",
     "unsupported-operator:=="),
    ("malformed-not-a-dict", "<field name='a' attrs=\"[('x', '=', 1)]\"/>", "malformed-attrs"),
    ("malformed-unparseable", "<field name='a' attrs=\"{'invisible': \"/>", "malformed-attrs"),
    ("unsupported-key", "<field name='a' attrs=\"{'column_invisible': [('x', '=', 1)]}\"/>",
     "unsupported-key:column_invisible"),
    ("in-needs-a-list", "<field name='a' attrs=\"{'invisible': [('x', 'in', 3)]}\"/>", "malformed-domain"),
    ("non-literal-list-value", "<field name='a' attrs=\"{'invisible': [('x', '=', [1])]}\"/>",
     "non-literal-value"),
    ("empty-domain", "<field name='a' attrs=\"{'invisible': []}\"/>", "empty-domain"),
    ("keyword-field-name", "<field name='a' attrs=\"{'invisible': [('if', '=', 1)]}\"/>", "reserved-name"),
    ("empty-attrs", "<field name='a' attrs=\"{}\"/>", "empty-attrs"),
    ("nested-list", "<field name='a'><tree><field name='b' attrs=\"{'invisible': [('x', '=', 1)]}\"/></tree></field>",
     "nested-view"),
    ("nested-kanban", "<field name='a'><kanban><field name='b' attrs=\"{'invisible': [('x', '=', 1)]}\"/></kanban>"
                      "</field>", "nested-view"),
    ("not-in-form", "<div><field name='a' attrs=\"{'invisible': [('x', '=', 1)]}\"/></div>", "not-in-form"),
]


class RefusalTests(unittest.TestCase):
    def test_each_excluded_case_is_untouched_and_refused_with_reason(self):
        for name, inner, reason in REFUSED:
            with self.subTest(case=name):
                text = form(inner) if "not-in-form" not in name else inner
                new_text, result = convert(text)
                self.assertEqual(new_text, text)
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], [reason])

    def test_existing_modifier_of_the_same_key_is_refused(self):
        text = form("""<field name="a" invisible="1" attrs="{'invisible': [('x', '=', 1)]}"/>""")
        self.assertEqual(refusals(text), ["same-modifier-exists:invisible"])
        self.assertEqual(convert(text)[0], text)

    def test_existing_modifier_on_another_key_is_not_a_refusal(self):
        text = form("""<field name="a" readonly="1" attrs="{'invisible': [('x', '=', 1)]}"/>""")
        self.assertEqual(refusals(text), [])
        self.assertIn('invisible="x == 1"', convert(text)[0])

    def test_one_bad_key_refuses_the_whole_element(self):
        text = form("""<field name="a" attrs="{'invisible': [('x', '=', 1)], 'readonly': [('y', '=', 0)]}"/>""")
        new_text, result = convert(text)
        self.assertEqual(new_text, text)
        self.assertEqual([r.reason for r in result.refused], ["falsy-literal"])

    def test_states_with_attrs_is_refused_by_both_rules(self):
        text = form("""<button name="x" states="draft" attrs="{'invisible': [('a', '=', 1)]}"/>""")
        self.assertEqual(refusals(text, ATTRS), ["states-with-attrs"])
        self.assertEqual(refusals(text, STATES), ["states-with-attrs"])
        self.assertEqual(convert(text, STATES)[0], text)

    def test_states_with_existing_invisible_is_refused(self):
        text = form('<button name="x" states="draft" invisible="1"/>')
        self.assertEqual(refusals(text, STATES), ["same-modifier-exists:invisible"])
        self.assertEqual(convert(text, STATES)[0], text)

    def test_malformed_states_is_refused(self):
        for raw in ("", "a b", "a,,b", "a'b"):
            with self.subTest(states=raw):
                text = form(f'<button name="x" states="{raw}"/>')
                self.assertEqual(refusals(text, STATES), ["malformed-states"])
                self.assertEqual(convert(text, STATES)[0], text)

    def test_refused_element_is_still_listed_for_the_developer(self):
        text = form("""<field name="a" attrs="{'invisible': [('amount', '=', 0)]}"/>""")
        result = xm.plan_attrs(Document.from_text(PATH, text))
        self.assertEqual(result.refused[0].line, 1)
        self.assertEqual(result.refused[0].element, "field")


# ---- idempotence and output shape --------------------------------------------------------------------------

class IdempotenceTests(unittest.TestCase):
    def test_second_application_yields_no_edits_and_identical_bytes(self):
        for name, (before, _after) in SUPPORTED.items():
            with self.subTest(case=name):
                once, _ = convert(form(before))
                twice, result = convert(once)
                self.assertEqual(result.edits, ())
                self.assertEqual(twice, once)

    def test_refused_elements_are_not_edited_on_a_second_pass(self):
        text = form("""<field name="a" attrs="{'invisible': [('amount', '=', 0)]}"/>""")
        once, _ = convert(text)
        twice, result = convert(once)
        self.assertEqual(result.edits, ())
        self.assertEqual(twice, once)


class OutputShapeTests(unittest.TestCase):
    def test_converted_output_has_no_attrs_or_states_and_is_well_formed(self):
        text = form("".join(before for before, _ in SUPPORTED.values())
                    + '<button name="go" states="draft,sent"/>')
        after_attrs, first = convert(text)
        new_text, second = convert(after_attrs, STATES)
        root = ET.fromstring(new_text)  # stdlib parse: the output is well-formed XML
        self.assertEqual(root.findall(".//*[@attrs]"), [])
        self.assertEqual(root.findall(".//*[@states]"), [])
        self.assertEqual(len(first.converted) + len(second.converted), len(SUPPORTED) + 1)

    def test_only_the_converted_element_changes(self):
        text = form('<field name="a"/><field name="b" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>'
                    '<field name="c"/>')
        new_text, _ = convert(text)
        self.assertEqual(new_text, form('<field name="a"/><field name="b" invisible="x == 1"/><field name="c"/>'))


# ---- differential check: old domain semantics against the new expression -----------------------------------

FIELDS_FOR_RECORDS = ("state", "amount", "flag")
VALUE_UNIVERSE = (None, False, 0, "", "a", "b", "draft", 1, True)


def odoo_domain_holds(domain, record) -> bool:
    """Evaluate an Odoo prefix domain (implicit '&' between top-level terms) against ``record``."""
    stack = []
    for item in reversed(list(domain)):
        if item in ("&", "|"):
            first, second = stack.pop(), stack.pop()  # both operands popped (no short-circuit)
            stack.append((first and second) if item == "&" else (first or second))
        elif item == "!":
            stack.append(not stack.pop())
        else:
            field, op, value = item
            left = record.get(field)
            if op == "=":
                stack.append(left == value)
            elif op == "!=":
                stack.append(left != value)
            elif op == "in":
                stack.append(left in value)
            else:
                stack.append(left not in value)
    return all(stack)


def python_expression_holds(expression, record) -> bool:
    """Evaluate a converted modifier expression; only names and literals may appear."""
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Lambda, ast.Subscript, ast.Starred)):
            raise AssertionError(f"unexpected node in modifier: {ast.dump(node)}")
    return bool(eval(compile(tree, "<modifier>", "eval"), {"__builtins__": {}}, dict(record)))


def modifier_value(xml_text, element_name, key):
    root = ET.fromstring(xml_text)
    return next(el.get(key) for el in root.iter() if el.get("name") == element_name)


def records(fields):
    for values in itertools.product(VALUE_UNIVERSE, repeat=len(fields)):
        yield dict(zip(fields, values))


DIFFERENTIAL = {
    "single-leaf-equal": ("state", "{'invisible': [('state', '=', 'done')]}", "invisible", "a"),
    "in-list": ("state", "{'readonly': [('state', 'in', ['draft', 'sent'])]}", "readonly", "a"),
    "not-in-list": ("state", "{'invisible': [('state', 'not in', ['x', 'a'])]}", "invisible", "a"),
    "not-equal": ("state", "{'readonly': [('state', '!=', 'draft')]}", "readonly", "a"),
    "and-implicit": ("state", "{'invisible': [('state', '=', 'a'), ('amount', '!=', 1)]}", "invisible", "a"),
    "or-explicit": ("state", "{'invisible': ['|', ('state', '=', 'a'), ('amount', '=', 1)]}", "invisible", "a"),
    "not-operator": ("state", "{'invisible': ['!', ('state', '=', 'a')]}", "invisible", "a"),
    "nested-or-and": ("state", "{'invisible': ['&', '|', ('state', '=', 'a'), ('flag', '=', True), "
                               "('amount', 'not in', [1, 'b'])]}", "invisible", "a"),
    "required-key": ("state", "{'required': [('state', '=', 'draft')]}", "required", "a"),
}


class DifferentialTests(unittest.TestCase):
    def test_old_domain_and_new_expression_agree_on_every_record(self):
        mismatches, checked = [], 0
        for name, (_field, attrs, key, element) in DIFFERENTIAL.items():
            text = form(f'<field name="{element}" attrs="{attrs.replace("&", "&amp;")}"/>')  # XML escaping only
            new_text, result = convert(text)
            self.assertEqual(result.refused, (), name)
            expression = modifier_value(new_text, element, key)
            domain = ast.literal_eval(attrs)[key]
            for record in records(FIELDS_FOR_RECORDS):
                checked += 1
                if odoo_domain_holds(domain, record) != python_expression_holds(expression, record):
                    mismatches.append((name, record))
        self.assertGreater(checked, 1000)
        self.assertEqual(mismatches, [])

    def test_states_expression_matches_the_old_states_semantics(self):
        states = ["draft", "sent"]
        new_text, _ = convert(form(f'<button name="go" states="{",".join(states)}"/>'), STATES)
        expression = modifier_value(new_text, "go", "invisible")
        mismatches = []
        for state in VALUE_UNIVERSE:
            old_visible = state in states  # Odoo states: visible while the record's state is in the list
            hidden = python_expression_holds(expression, {"state": state})
            if hidden == old_visible:
                mismatches.append(state)
        self.assertEqual(mismatches, [])


if __name__ == "__main__":
    unittest.main()
