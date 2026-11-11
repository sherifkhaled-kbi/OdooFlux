"""Same-document target resolution for inherited views (PA-4).

An inherited view's xpath whose expression does not name a ``form`` is converted only when its target is proven inside
the same document: a bare ``inherit_id`` ref to one base ``ir.ui.view`` record whose arch is a single ``<form>``, and an
expression ``//field[@name='x']`` naming a field found exactly once, directly in that form. Every other case stays
byte-identical and refused. Unit layer: no file is read, no CLI is run.
"""

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
FORM_ARCH = '<form><sheet><group><field name="a"/></group></sheet></form>'
FIELD_EXPR = "//field[@name='a']"
HIDE = "{'invisible': [('x', '=', 1)]}"


def ctx(rule_id):
    return RuleContext(rule_id=rule_id, severity="CRITICAL", step="16-17")


def base_record(arch, view_id="base_form", extra=""):
    return (f'<record id="{view_id}" model="ir.ui.view"><field name="name">base</field>'
            f'<field name="model">kbi.exp</field>{extra}<field name="arch" type="xml">{arch}</field></record>')


def inheriting(xpath, ref="base_form", view_id="v_inh"):
    return (f'<record id="{view_id}" model="ir.ui.view"><field name="name">inh</field>'
            f'<field name="model">kbi.exp</field><field name="inherit_id" ref="{ref}"/>'
            f'<field name="arch" type="xml">{xpath}</field></record>')


def document(*records):
    return "<odoo>" + "".join(records) + "</odoo>"


def xpath(expr, position, inner):
    return f'<xpath expr="{expr}" position="{position}">{inner}</xpath>'


def attrs_xpath(expr, dict_text=HIDE):
    return xpath(expr, "attributes", f'<attribute name="attrs">{dict_text}</attribute>')


def convert(text, rule_id=ATTRS):
    document_ = Document.from_text(PATH, text)
    fn = xm.plan_attrs if rule_id == ATTRS else xm.plan_states
    result = fn(document_, ctx(rule_id))
    if not result.edits:
        return text, result
    return apply_edits(document_, result.edits, precedence=[rule_id]).text, result


def refusals(text, rule_id=ATTRS):
    fn = xm.plan_attrs if rule_id == ATTRS else xm.plan_states
    return [r.reason for r in fn(Document.from_text(PATH, text)).refused]


# ---- converted: target proven in this document --------------------------------------------------------------------

POSITIVE = {
    "attributes-field-in-sheet": (
        document(base_record(FORM_ARCH), inheriting(attrs_xpath(FIELD_EXPR))),
        document(base_record(FORM_ARCH),
                 inheriting(xpath(FIELD_EXPR, "attributes", '<attribute name="invisible">x == 1</attribute>')))),
    "inside-plain-field-in-notebook-page": (
        document(base_record('<form><notebook><page string="p"><field name="a"/></page></notebook></form>'),
                 inheriting(xpath(FIELD_EXPR, "after", f'<field name="b" attrs="{HIDE}"/>'))),
        document(base_record('<form><notebook><page string="p"><field name="a"/></page></notebook></form>'),
                 inheriting(xpath(FIELD_EXPR, "after", '<field name="b" invisible="x == 1"/>')))),
    "replace-plain-field": (
        document(base_record(FORM_ARCH), inheriting(xpath(FIELD_EXPR, "replace", f'<field name="c" attrs="{HIDE}"/>'))),
        document(base_record(FORM_ARCH),
                 inheriting(xpath(FIELD_EXPR, "replace", '<field name="c" invisible="x == 1"/>')))),
}


class PositiveTargetTests(unittest.TestCase):
    def test_resolvable_form_target_converts_to_the_expected_bytes(self):
        for name, (before, after) in POSITIVE.items():
            with self.subTest(case=name):
                text, result = convert(before)
                self.assertEqual(text, after)
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)

    def test_states_inside_resolvable_target_converts_to_invisible(self):
        before = document(base_record(FORM_ARCH),
                          inheriting(xpath(FIELD_EXPR, "after", '<button name="go" states="draft,sent"/>')))
        text, result = convert(before, STATES)
        self.assertEqual(text, document(base_record(FORM_ARCH), inheriting(
            xpath(FIELD_EXPR, "after", '<button name="go" invisible="state not in [\'draft\',\'sent\']"/>'))))
        self.assertEqual(result.refused, ())

    def test_attributes_form_escapes_markup_in_the_expression(self):
        before = document(base_record(FORM_ARCH),
                          inheriting(attrs_xpath(FIELD_EXPR, "{'invisible': [('x', '=', 'a&lt;b')]}")))
        text, result = convert(before)
        self.assertEqual(result.refused, ())
        self.assertEqual(len(result.converted), 1)
        attr = ET.fromstring(text).find(".//attribute[@name='invisible']")
        self.assertEqual(attr.text, "x == 'a<b'")


# ---- refused: every unresolved or unsafe target stays byte-identical with a reason ------------------------------

NEGATIVE = [
    ("target-list-view", document(base_record("<tree><field name=\"a\"/></tree>"),
                                  inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("target-missing", document(base_record(FORM_ARCH, view_id="other_form"),
                                inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("target-ambiguous", document(base_record(FORM_ARCH), base_record(FORM_ARCH),
                                  inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("target-qualified-ref", document(base_record(FORM_ARCH),
                                      inheriting(attrs_xpath(FIELD_EXPR), ref="base.base_form")),
     "inherited-target-not-form"),
    ("target-is-extension", document(base_record(FORM_ARCH, extra='<field name="inherit_id" ref="x.y"/>'),
                                     inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("target-arch-wrapped", document(base_record(f"<data>{FORM_ARCH}</data>"),
                                     inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("target-arch-two-roots", document(base_record(FORM_ARCH + FORM_ARCH),
                                       inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-not-form"),
    ("field-not-in-target", document(base_record(FORM_ARCH),
                                     inheriting(attrs_xpath("//field[@name='zz']"))),
     "inherited-target-field-not-found"),
    ("field-twice-in-target", document(base_record('<form><field name="a"/><group><field name="a"/></group></form>'),
                                       inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-field-ambiguous"),
    ("field-only-in-nested-tree", document(
        base_record('<form><field name="l"><tree><field name="a"/></tree></field></form>'),
        inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-field-nested"),
    ("field-only-in-embedded-form", document(
        base_record('<form><field name="l"><form><field name="a"/></form></field></form>'),
        inheriting(attrs_xpath(FIELD_EXPR))), "inherited-target-field-nested"),
    ("expr-not-a-field", document(base_record(FORM_ARCH),
                                  inheriting(attrs_xpath("//group[@name='g']"))),
     "inherited-target-expr-unverified"),
    ("expr-field-with-double-predicate", document(base_record(FORM_ARCH),
                                                  inheriting(attrs_xpath("//field[@name='a'][1]"))),
     "inherited-target-expr-unverified"),
    ("expr-nested-view", document(base_record(FORM_ARCH),
                                  inheriting(attrs_xpath("//tree//field[@name='a']"))), "nested-view"),
]


class NegativeTargetTests(unittest.TestCase):
    def test_each_unresolved_target_is_untouched_and_refused_with_its_reason(self):
        for name, text, reason in NEGATIVE:
            with self.subTest(case=name):
                new_text, result = convert(text)
                self.assertEqual(new_text, text)
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], [reason])


# ---- idempotence, well-formedness, no leftover modifiers --------------------------------------------------------

class SafeIdempotenceTests(unittest.TestCase):
    def test_second_pass_over_every_positive_and_negative_case_is_a_no_op(self):
        texts = [before for before, _ in POSITIVE.values()] + [text for _, text, _ in NEGATIVE]
        for index, text in enumerate(texts):
            with self.subTest(case=index):
                once, _ = convert(text)
                twice, result = convert(once)
                self.assertEqual(result.edits, ())
                self.assertEqual(twice, once)


class SafeOutputShapeTests(unittest.TestCase):
    def test_converted_output_is_well_formed_and_keeps_no_attrs_or_states(self):
        text = document(base_record(FORM_ARCH), inheriting(
            attrs_xpath(FIELD_EXPR) + xpath(FIELD_EXPR, "after", f'<field name="b" attrs="{HIDE}"/>')
            + xpath(FIELD_EXPR, "after", '<button name="go" states="draft"/>')))
        once, _ = convert(text)
        twice, _ = convert(once, STATES)
        root = ET.fromstring(twice)  # stdlib parse: the output is well-formed XML
        self.assertEqual(root.findall(".//*[@attrs]"), [])
        self.assertEqual(root.findall(".//*[@states]"), [])
        self.assertEqual([el for el in root.iter("attribute") if el.get("name") == "attrs"], [])

    def test_refused_target_keeps_the_xml_well_formed_and_unchanged(self):
        text = document(base_record("<tree><field name=\"a\"/></tree>"), inheriting(attrs_xpath(FIELD_EXPR)))
        new_text, _ = convert(text)
        self.assertEqual(new_text, text)
        ET.fromstring(new_text)


# ---- FC-2: a bare //field[@name='x'] target must name a field occurring exactly once in the proven form -----------

TWICE_IN_FORM = '<form><sheet><group><field name="a"/><field name="a"/></group></sheet></form>'
ABSENT_FROM_FORM = '<form><sheet><group><field name="b"/></group></sheet></form>'
UNSUPPORTED_EXPRS = [
    "//sheet",
    "//group",
    "//group[@name='g']",
    "//button[@name='b']",
    "//field",
    "//field[@string='a']",
    "//field[@name=a]",
    "//field[@name='a' and @invisible]",
    "//field[@name='a']/..",
    "//field[@name='a'][1]",
]


class TargetFieldOccurrenceTests(unittest.TestCase):
    def test_target_field_must_occur_exactly_once(self):
        for name, arch, reason in [
            ("field-twice-in-form", TWICE_IN_FORM, "inherited-target-field-ambiguous"),
            ("field-absent-from-form", ABSENT_FROM_FORM, "inherited-target-field-not-found"),
        ]:
            with self.subTest(case=name):
                before = document(base_record(arch), inheriting(attrs_xpath(FIELD_EXPR)))
                text, result = convert(before)
                self.assertEqual(text, before)
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], [reason])
                ET.fromstring(text)
        with self.subTest(case="field-once-in-form-converts"):
            before = document(base_record(FORM_ARCH), inheriting(attrs_xpath(FIELD_EXPR)))
            text, result = convert(before)
            self.assertEqual(text, POSITIVE["attributes-field-in-sheet"][1])
            self.assertEqual(result.refused, ())


class UnsupportedXpathTests(unittest.TestCase):
    def test_unsupported_xpath_expressions_are_refused(self):
        for expr in UNSUPPORTED_EXPRS:
            with self.subTest(expr=expr):
                before = document(base_record(FORM_ARCH), inheriting(attrs_xpath(expr)))
                text, result = convert(before)
                self.assertEqual(text, before)
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], ["inherited-target-expr-unverified"])
                ET.fromstring(text)
        with self.subTest(expr="control-field-predicate"):
            before = document(base_record(FORM_ARCH), inheriting(attrs_xpath(FIELD_EXPR)))
            text, result = convert(before)
            self.assertEqual(text, POSITIVE["attributes-field-in-sheet"][1])
            self.assertEqual(result.refused, ())


# ---- form-rooted expressions: the word 'form' is not proof, only an anchored form path or a checked field is ---------

FORM_FIELD_EXPRS = ["/form/field[@name='a']", "//form/field[@name='a']"]
DUPLICATE_FORM = '<form><field name="a"/><group><field name="a"/></group></form>'
NESTED_NOTEBOOK_FORM = '<form><notebook><page string="p"><field name="l"><form><field name="a"/></form></field></page></notebook></form>'
NESTED_NOTEBOOK_LIST = '<form><notebook><page string="p"><field name="l"><list><field name="a"/></list></field></page></notebook></form>'


class FormRootedPositiveTests(unittest.TestCase):
    def test_form_field_shapes_convert_when_the_field_occurs_once_in_the_form(self):
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                before = document(base_record(FORM_ARCH), inheriting(attrs_xpath(expr)))
                after = document(base_record(FORM_ARCH), inheriting(
                    xpath(expr, "attributes", '<attribute name="invisible">x == 1</attribute>')))
                text, result = convert(before)
                self.assertEqual(text, after)
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)

    def test_form_path_with_child_steps_is_accepted_without_a_field_check(self):
        for expr in ["//form/sheet/group", "//form//sheet", "/form/sheet/group[@name='g']"]:
            with self.subTest(expr=expr):
                before = document(base_record(FORM_ARCH), inheriting(attrs_xpath(expr)))
                _, result = convert(before)
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)

    def test_form_field_shape_with_core_ref_is_accepted_as_before(self):
        # The target is not in this document and no module context is given: it cannot be read, so the shape stands.
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                before = document(inheriting(attrs_xpath(expr), ref="base.base_form"))
                _, result = convert(before)
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)


class FormRootedNegativeTests(unittest.TestCase):
    def assert_untouched(self, text, reason):
        new_text, result = convert(text)
        self.assertEqual(new_text, text)
        self.assertEqual(result.edits, ())
        self.assertEqual([r.reason for r in result.refused], [reason])

    def test_ancestor_form_axis_is_refused_as_unverified(self):
        self.assert_untouched(document(base_record(FORM_ARCH),
                                       inheriting(attrs_xpath("//field[@name='a']/ancestor::form"))),
                              "inherited-target-expr-unverified")

    def test_form_word_inside_another_step_is_refused_as_unverified(self):
        for expr in ["//div[@class='form']/field[@name='a']", "//form[@string='x']/field[@name='a']",
                     "//form/field[@name='a']/..", "//form/field[@name='a']/following::field"]:
            with self.subTest(expr=expr):
                self.assert_untouched(document(base_record(FORM_ARCH), inheriting(attrs_xpath(expr))),
                                      "inherited-target-expr-unverified")

    def test_form_field_shape_on_a_list_target_is_refused_as_not_form(self):
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                self.assert_untouched(document(base_record('<tree><field name="a"/></tree>'),
                                               inheriting(attrs_xpath(expr))), "inherited-target-not-form")

    def test_form_field_shape_with_duplicate_field_is_ambiguous(self):
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                self.assert_untouched(document(base_record(DUPLICATE_FORM), inheriting(attrs_xpath(expr))),
                                      "inherited-target-field-ambiguous")

    def test_form_field_shape_with_field_only_in_notebook_embedded_form_is_nested(self):
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                self.assert_untouched(document(base_record(NESTED_NOTEBOOK_FORM), inheriting(attrs_xpath(expr))),
                                      "inherited-target-field-nested")

    def test_form_field_shape_with_field_only_in_notebook_list_is_nested(self):
        for expr in FORM_FIELD_EXPRS:
            with self.subTest(expr=expr):
                self.assert_untouched(document(base_record(NESTED_NOTEBOOK_LIST), inheriting(attrs_xpath(expr))),
                                      "inherited-target-field-nested")

    def test_form_field_shape_with_nested_list_expression_is_refused_as_nested_view(self):
        self.assert_untouched(document(base_record(FORM_ARCH), inheriting(attrs_xpath("//form//tree/field[@name='a']"))),
                              "nested-view")


if __name__ == "__main__":
    unittest.main()
