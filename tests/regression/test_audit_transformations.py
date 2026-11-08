"""TST-005-007 (REQ-PY-001, REQ-TST-005): regressions for audit F-PY-1 and F-PY-2 using the span helpers."""

import ast
import unittest

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng
from odooflux.parsers.python import document as pydoc
from odooflux.transformers import python as pyx

RULE = "python.audit-regression"


def apply_helper(source, edits_for):
    """Run one helper over ``source`` through the edit engine; return the new text."""
    document = docs.Document.from_text("models.py", source)
    parsed = pydoc.parse_document(document)
    result = eng.apply_edits(document, edits_for(parsed), precedence=[RULE])
    assert result.rejected == (), result.rejected
    return result.text


class DecoratorRemovalF_PY_1(unittest.TestCase):
    """F-PY-1: removing a decorator must not leave doubled indentation (IndentationError)."""

    SRC = (
        "class A(models.Model):\n"
        "    _name = 'a'\n"
        "\n"
        "    @api.multi\n"
        "    # keep this comment\n"
        "    def f(self):\n"
        "        return 1\n"
        "\n"
        "    @api.returns(\n"
        "        'self',\n"
        "    )\n"
        "    def g(self):\n"
        "        return self.search([])\n"
    )

    def test_decorators_removed_and_output_compiles(self):
        out = apply_helper(self.SRC, lambda p: pyx.remove_decorator(p, "api.multi", rule_id=RULE)
                           + pyx.remove_decorator(p, "api.returns", rule_id=RULE))
        ast.parse(out)
        self.assertNotIn("@api.multi", out)
        self.assertNotIn("@api.returns", out)

    def test_indentation_and_comment_survive(self):
        out = apply_helper(self.SRC, lambda p: pyx.remove_decorator(p, "api.multi", rule_id=RULE))
        self.assertIn("    # keep this comment\n    def f(self):\n", out)
        self.assertIn("\n    def g(self):\n", out)
        self.assertNotIn("        def f", out)

    def test_second_pass_has_no_edits(self):
        out = apply_helper(self.SRC, lambda p: pyx.remove_decorator(p, "api.multi", rule_id=RULE)
                           + pyx.remove_decorator(p, "api.returns", rule_id=RULE))
        self.assertEqual(pyx.remove_decorator(pydoc.parse(out), "api.returns", rule_id=RULE), [])


class KeywordCommaF_PY_2(unittest.TestCase):
    """F-PY-2: removing ``size=`` must not leave ``fields.Char(, ...)`` or ``(,`` artefacts (SyntaxError)."""

    def test_first_argument(self):
        out = apply_helper("name = fields.Char(size=64, string='X')\n",
                           lambda p: pyx.remove_keyword(p, "fields.Char", "size", rule_id=RULE))
        self.assertEqual(out, "name = fields.Char(string='X')\n")

    def test_last_argument(self):
        out = apply_helper("name = fields.Char(string='X', size=64)\n",
                           lambda p: pyx.remove_keyword(p, "fields.Char", "size", rule_id=RULE))
        self.assertEqual(out, "name = fields.Char(string='X')\n")

    def test_continuation_line_compiles(self):
        src = "code = fields.Char(\n    string='Code',\n    size=\n    32,\n)\n"
        out = apply_helper(src, lambda p: pyx.remove_keyword(p, "fields.Char", "size", rule_id=RULE))
        ast.parse(out)
        self.assertNotIn("size", out)
        self.assertNotIn("(,", out)
        self.assertIn("string='Code'", out)


# ---- XML audit regressions F-XML-1..4 (REQ-XML-002, REQ-TST-005; TST-005-011) ----

XML_RULE = "xml.audit-regression"


def _xml_convert(source, *, mode="falsy", in_list_view=False):
    """Convert the first element carrying attrs/states; return (output text, conversion, batch result)."""
    from odooflux.core.engine.documents import Document
    from odooflux.core.engine.edits import apply_edits
    from odooflux.parsers.xml import document as xmldoc
    from odooflux.transformers import modifiers as mod
    from odooflux.transformers.xml import EditMeta

    document = Document.from_text("view.xml", source)
    xdoc = xmldoc.parse(document)
    assert xdoc.parse_error is None, xdoc.parse_error
    target = next((e for e in xdoc.elements
                   if e.get_attr("attrs") is not None or e.get_attr("states") is not None),
                  xdoc.elements[1])  # nothing left to convert: the first child must yield no edits
    meta = EditMeta(id="f-xml", rule_id=XML_RULE, step="fix", severity="WARNING")
    conversion = mod.convert_element(xdoc, target, mode=mode, in_list_view=in_list_view, meta=meta)
    result = apply_edits(document, conversion.edits, precedence=[XML_RULE])
    return result.text, conversion, result


class StatesCommentF_XML_1(unittest.TestCase):
    """F-XML-1: the states= fixer must never insert an XML comment inside a start tag."""

    def test_states_conversion_has_no_comment_and_is_well_formed(self):
        import xml.etree.ElementTree as ET

        out, _, _ = _xml_convert('<odoo><button name="a" states="draft" type="object"/></odoo>')
        self.assertNotIn("<!--", out)
        ET.fromstring(out.encode("utf-8"))
        self.assertIn("invisible=\"state not in ['draft']\"", out)

    def test_multiline_start_tag_stays_well_formed(self):
        import xml.etree.ElementTree as ET

        src = '<odoo><button name="a"\n          states="draft,done"\n          type="object"/></odoo>'
        out, _, _ = _xml_convert(src)
        self.assertNotIn("<!--", out)
        ET.fromstring(out.encode("utf-8"))


class AttrsExpressionF_XML_2(unittest.TestCase):
    """F-XML-2: attrs= is converted to Python expressions, never to domain lists."""

    def test_invisible_domain_becomes_expression(self):
        out, _, _ = _xml_convert("<odoo><button name=\"a\" attrs=\"{'invisible': [('state', '=', 'done')]}\"/></odoo>")
        self.assertIn("invisible=\"state == 'done'\"", out)
        self.assertNotIn("attrs=", out)
        self.assertNotIn("[(", out)

    def test_readonly_with_or_becomes_expression(self):
        src = ("<odoo><field name=\"f\" attrs=\"{'readonly': ['|', ('a', '=', 1), ('b', '=', 2)]}\"/></odoo>")
        out, _, _ = _xml_convert(src)
        self.assertIn("readonly=\"a == 1 or b == 2\"", out)
        self.assertNotIn("['|'", out)


class ColumnInvisibleF_XML_3(unittest.TestCase):
    """F-XML-3: column_invisible is kept in list views and reported elsewhere, never silently dropped."""

    def test_column_invisible_kept_in_list_view(self):
        src = "<odoo><tree><field name=\"f\" attrs=\"{'column_invisible': [('x', '=', 1)]}\"/></tree></odoo>"
        out, conversion, _ = _xml_convert(src, in_list_view=True)
        self.assertIn("column_invisible=\"x == 1\"", out)
        self.assertEqual(conversion.unconverted, ())

    def test_column_invisible_outside_list_is_reported_not_dropped(self):
        src = "<odoo><field name=\"f\" attrs=\"{'column_invisible': [('x', '=', 1)]}\"/></odoo>"
        out, conversion, _ = _xml_convert(src, in_list_view=False)
        self.assertIn("attrs=", out)
        self.assertEqual([(u.key, u.reason) for u in conversion.unconverted],
                         [("column_invisible", "column-invisible-outside-list")])


class IdempotentF_XML_4(unittest.TestCase):
    """F-XML-4: no duplicate invisible= attribute, and a second pass produces no edits."""

    def test_states_with_existing_invisible_does_not_duplicate(self):
        import xml.etree.ElementTree as ET

        out, _, _ = _xml_convert('<odoo><button name="a" states="draft" invisible="0"/></odoo>')
        self.assertEqual(out.count("invisible="), 1)
        self.assertIn("invisible=\"(0) or (state not in ['draft'])\"", out)
        ET.fromstring(out.encode("utf-8"))

    def test_second_pass_yields_no_edits_and_no_new_comments(self):
        first, _, _ = _xml_convert('<odoo><button name="a" states="draft" type="object"/></odoo>')
        second, conversion, _ = _xml_convert(first)
        self.assertEqual(conversion.edits, ())
        self.assertEqual(second, first)
        self.assertEqual(second.count("<!--"), 0)


if __name__ == "__main__":
    unittest.main()
