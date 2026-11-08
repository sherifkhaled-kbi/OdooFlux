"""TST-005-009 (REQ-XML-001, REQ-TRF-003): XML edit helpers produce well-formed, idempotent output."""

import unittest
import xml.etree.ElementTree as ET

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import xml as xh

from .. import _setup  # noqa: F401  (src first on sys.path)

RULE = "test.xml-helper"


def meta(edit_id="e1"):
    return xh.EditMeta(id=edit_id, rule_id=RULE, step="fix", severity="WARNING")


def run(text, edits_for):
    """Build edits with ``edits_for(xdoc)``, apply them, and return (new_text, result)."""
    document = Document.from_text("v.xml", text)
    xdoc = xmldoc.parse(document)
    assert xdoc.parse_error is None, xdoc.parse_error
    edits = edits_for(xdoc)
    edits = [edits] if not isinstance(edits, (list, tuple)) else list(edits)
    edits = [e for e in edits if e is not None]
    result = apply_edits(document, edits, precedence=[RULE])
    return result.text, result


def find_one(xdoc, tag, position=0):
    return xmldoc.find(xdoc, tag=tag)[position]


class WellFormedOutputTests(unittest.TestCase):
    def assertWellFormed(self, text):
        ET.fromstring(text.encode("utf-8"))

    def test_set_attr_replaces_existing_value(self):
        text, result = run('<odoo><button name="a" invisible="0"/></odoo>',
                           lambda x: xh.set_attr(x, find_one(x, "button"), "invisible", "1", meta=meta()))
        self.assertEqual(text, '<odoo><button name="a" invisible="1"/></odoo>')
        self.assertTrue(result.preserved_ok)
        self.assertWellFormed(text)

    def test_set_attr_inserts_missing_attribute(self):
        text, _ = run('<odoo><button name="a"/></odoo>',
                      lambda x: xh.set_attr(x, find_one(x, "button"), "readonly", "1", meta=meta()))
        self.assertEqual(text, '<odoo><button name="a" readonly="1"/></odoo>')
        self.assertWellFormed(text)

    def test_set_attr_inserts_into_element_without_attributes(self):
        text, _ = run("<odoo><group/></odoo>",
                      lambda x: xh.set_attr(x, find_one(x, "group"), "string", "G", meta=meta()))
        self.assertEqual(text, '<odoo><group string="G"/></odoo>')

    def test_set_attr_quote_safe_escaping(self):
        value = 'a"b\'c<d>&e\nf\tg'
        text, _ = run('<odoo><field name="x"/></odoo>',
                      lambda x: xh.set_attr(x, find_one(x, "field"), "help", value, meta=meta()))
        self.assertWellFormed(text)
        self.assertEqual(xmldoc.parse(Document.from_text("v.xml", text)).elements[1].get_attr("help").value,
                         value)

    def test_set_attr_keeps_single_quote_style_and_escapes_quote(self):
        text, _ = run("<odoo><field name='x' help='y'/></odoo>",
                      lambda x: xh.set_attr(x, find_one(x, "field"), "help", "it's", meta=meta()))
        self.assertWellFormed(text)
        self.assertIn("help='it&apos;s'", text)

    def test_remove_attr_middle_and_last(self):
        src = '<odoo><button name="a" attrs="{}" string="s"/></odoo>'
        text, _ = run(src, lambda x: xh.remove_attr(x, find_one(x, "button"), "attrs", meta=meta()))
        self.assertEqual(text, '<odoo><button name="a" string="s"/></odoo>')
        text, _ = run(src, lambda x: xh.remove_attr(x, find_one(x, "button"), "string", meta=meta()))
        self.assertEqual(text, '<odoo><button name="a" attrs="{}"/></odoo>')
        self.assertWellFormed(text)

    def test_remove_first_attr(self):
        text, _ = run('<odoo><b x="1" y="2"/></odoo>',
                      lambda x: xh.remove_attr(x, find_one(x, "b"), "x", meta=meta()))
        self.assertEqual(text, '<odoo><b y="2"/></odoo>')

    def test_rename_tag_start_and_end(self):
        text, result = run("<odoo><tree a=\"1\"><field name=\"x\"/></tree></odoo>",
                           lambda x: xh.rename_tag(x, find_one(x, "tree"), "list", meta=meta()))
        self.assertEqual(text, '<odoo><list a="1"><field name="x"/></list></odoo>')
        self.assertEqual(len(result.applied), 2)
        self.assertWellFormed(text)

    def test_rename_self_closing_tag_changes_start_only(self):
        text, result = run('<odoo><tree a="1"/></odoo>',
                           lambda x: xh.rename_tag(x, find_one(x, "tree"), "list", meta=meta()))
        self.assertEqual(text, '<odoo><list a="1"/></odoo>')
        self.assertEqual(len(result.applied), 1)

    def test_replace_element(self):
        text, _ = run("<odoo><old a=\"1\">t</old></odoo>",
                      lambda x: xh.replace_element(x, find_one(x, "old"), '<new b="2"/>', meta=meta()))
        self.assertEqual(text, '<odoo><new b="2"/></odoo>')
        self.assertWellFormed(text)

    def test_replace_element_rejects_malformed_replacement(self):
        document = Document.from_text("v.xml", "<odoo><old/></odoo>")
        xdoc = xmldoc.parse(document)
        with self.assertRaises(ValueError):
            xh.replace_element(xdoc, find_one(xdoc, "old"), "<new>", meta=meta())
        with self.assertRaises(ValueError):
            xh.replace_element(xdoc, find_one(xdoc, "old"), "<a/><b/>", meta=meta())

    def test_invalid_attribute_name_rejected(self):
        document = Document.from_text("v.xml", "<odoo><old/></odoo>")
        xdoc = xmldoc.parse(document)
        with self.assertRaises(ValueError):
            xh.set_attr(xdoc, find_one(xdoc, "old"), "1bad", "x", meta=meta())


class IdempotenceTests(unittest.TestCase):
    def test_set_attr_same_value_returns_none(self):
        document = Document.from_text("v.xml", '<odoo><button invisible="1"/></odoo>')
        xdoc = xmldoc.parse(document)
        self.assertIsNone(xh.set_attr(xdoc, find_one(xdoc, "button"), "invisible", "1", meta=meta()))

    def test_remove_missing_attr_returns_none(self):
        document = Document.from_text("v.xml", "<odoo><button/></odoo>")
        xdoc = xmldoc.parse(document)
        self.assertIsNone(xh.remove_attr(xdoc, find_one(xdoc, "button"), "attrs", meta=meta()))

    def test_second_application_yields_no_edits(self):
        src = '<odoo><button name="a" invisible="0"/></odoo>'

        def make(x):
            return [xh.set_attr(x, find_one(x, "button"), "invisible", "1", meta=meta()),
                    *xh.rename_tag(x, find_one(x, "button"), "btn", meta=meta("e2"))]

        first, _ = run(src, make)
        second_document = Document.from_text("v.xml", first)
        second_xdoc = xmldoc.parse(second_document)
        self.assertIsNone(xh.set_attr(second_xdoc, find_one(second_xdoc, "btn"), "invisible", "1",
                                      meta=meta()))
        self.assertEqual(xh.rename_tag(second_xdoc, find_one(second_xdoc, "btn"), "btn", meta=meta()), ())


class EditShapeTests(unittest.TestCase):
    def test_edit_carries_required_fields(self):
        document = Document.from_text("v.xml", '<odoo><button name="a"/></odoo>')
        xdoc = xmldoc.parse(document)
        edit = xh.set_attr(xdoc, find_one(xdoc, "button"), "invisible", "1", meta=meta("ed-7"))
        self.assertEqual(edit.id, "ed-7")
        self.assertEqual(edit.rule_id, RULE)
        self.assertEqual(edit.path, "v.xml")
        self.assertEqual(edit.severity, "WARNING")
        self.assertEqual(edit.step, "fix")
        self.assertEqual(edit.before, "")


if __name__ == "__main__":
    unittest.main()
