"""TST-006-007 (REQ-XML-003): rule 17-18.xml.tree-to-list.

17.0 accepts ``tree`` as a view type (arch root, ``view_mode`` entry, action dict entry); 18.0 has ``list`` and no
``tree`` (EV-300..303). The fixer must rewrite whole view-type entries only, never string literals that are not
view_mode values, keep the output well-formed (XML) or compilable (Python), and be idempotent.
"""

import unittest
import xml.etree.ElementTree as ET

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule
from odooflux.rules.xml import view_types as vt

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "17-18.xml.tree-to-list"
CTX = RuleContext(rule_id=RULE_ID, severity="CRITICAL", step="17-18",
                  message="tree view type removed", suggestion="use list")
PARAMS = {"from_type": "tree", "to_type": "list"}


def fix(text, path="v.xml"):
    """Apply the fixer once; return (result, second-pass edits)."""
    document = Document.from_text(path, text)
    result = apply_edits(document, vt.migrate_view_type(document, CTX, **PARAMS), precedence=[RULE_ID])
    second = vt.migrate_view_type(Document.from_text(path, result.text), CTX, **PARAMS)
    return result, second


def detect(text, path="v.xml"):
    return vt.flag_view_type(Document.from_text(path, text), CTX, from_type=PARAMS["from_type"])


def assert_well_formed(test, text):
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:  # pragma: no cover - failure path
        test.fail(f"output is not well-formed: {exc}")


class XmlPositiveTests(unittest.TestCase):
    def assertFixed(self, text, expected, path="v.xml"):
        result, second = fix(text, path)
        self.assertEqual(result.rejected, ())
        self.assertTrue(result.preserved_ok)
        self.assertEqual(result.text, expected)
        self.assertEqual(second, [])
        return result

    def test_arch_root_tree_is_renamed_with_end_tag(self):
        result = self.assertFixed("<tree string='Partners'><field name='name'/></tree>\n",
                                  "<list string='Partners'><field name='name'/></list>\n")
        assert_well_formed(self, result.text)

    def test_nested_tree_inside_field_is_renamed(self):
        self.assertFixed("<form><field name='line_ids'><tree><field name='x'/></tree></field></form>",
                         "<form><field name='line_ids'><list><field name='x'/></list></field></form>")

    def test_view_mode_field_text_is_rewritten(self):
        self.assertFixed("<field name=\"view_mode\">tree,form</field>",
                         "<field name=\"view_mode\">list,form</field>")

    def test_view_mode_field_keeps_whitespace_around_entries(self):
        self.assertFixed("<field name=\"view_mode\">form, tree</field>",
                         "<field name=\"view_mode\">form, list</field>")

    def test_view_mode_attribute_on_act_window_is_rewritten(self):
        self.assertFixed("<act_window id='a' view_mode='form,tree' name='x'/>",
                         "<act_window id='a' view_mode='form,list' name='x'/>")

    def test_python_action_dict_view_mode_is_rewritten(self):
        src = ("class A(models.Model):\n"
               "    def action(self):\n"
               "        return {'type': 'ir.actions.act_window', 'view_mode': 'tree,form', 'res_model': 'x'}\n")
        result, second = fix(src, path="m.py")
        self.assertEqual(result.text, src.replace("'tree,form'", "'list,form'"))
        self.assertEqual(second, [])

    def test_python_double_quoted_view_mode_keeps_quote_style(self):
        result, _ = fix("d = {\"view_mode\": \"tree\"}\n", path="m.py")
        self.assertEqual(result.text, "d = {\"view_mode\": \"list\"}\n")

    def test_python_view_mode_keyword_argument_is_rewritten(self):
        result, _ = fix("act = dict(view_mode=\"tree,kanban\", res_model='x')\n", path="m.py")
        self.assertEqual(result.text, "act = dict(view_mode=\"list,kanban\", res_model='x')\n")


class NegativeTests(unittest.TestCase):
    def assertUnchanged(self, text, path="v.xml"):
        result, second = fix(text, path)
        self.assertEqual(result.text, text)
        self.assertEqual(second, [])

    def test_treeview_element_is_not_renamed(self):
        self.assertUnchanged("<treeview name='x'/>")

    def test_list_element_is_untouched(self):
        self.assertUnchanged("<list string='x'><field name='a'/></list>")

    def test_treeview_entry_in_view_mode_is_not_renamed(self):
        self.assertUnchanged("<field name=\"view_mode\">treeview,list</field>")

    def test_tree_in_non_view_mode_field_text_is_untouched(self):
        self.assertUnchanged("<field name=\"description\">tree</field>")

    def test_tree_in_attribute_other_than_view_mode_is_untouched(self):
        self.assertUnchanged("<field name='x' string='tree' widget='tree'/>")

    def test_python_string_literals_are_not_touched(self):
        src = ("kind = 'tree'\n"
               "msg = 'tree,form'\n"
               "d = {'view_mode': 'treeview,form', 'label': 'tree'}\n")
        self.assertUnchanged(src, path="m.py")

    def test_malformed_xml_yields_no_edits(self):
        self.assertUnchanged("<tree><field></tree>")

    def test_malformed_python_yields_no_edits(self):
        self.assertUnchanged("d = {'view_mode': 'tree'\n", path="m.py")


class IdempotenceTests(unittest.TestCase):
    def test_second_pass_has_no_edits_on_mixed_document(self):
        text = "<odoo><tree/><field name='view_mode'>tree,form</field></odoo>"
        result, second = fix(text)
        self.assertEqual(result.text, "<odoo><list/><field name='view_mode'>list,form</field></odoo>")
        self.assertEqual(second, [])

    def test_list_only_document_has_no_edits(self):
        text = "<odoo><list/><field name='view_mode'>list,form</field></odoo>"
        self.assertEqual(fix(text)[0].text, text)


class DetectionTests(unittest.TestCase):
    def test_detects_arch_root_nested_tree_and_view_mode_entries(self):
        findings = detect("<tree><field name='view_mode'>tree,form</field></tree>")
        self.assertEqual([f.matched for f in findings], ["tree", "tree"])
        self.assertTrue(all(f.rule_id == RULE_ID and f.severity == "CRITICAL" for f in findings))

    def test_detects_python_view_mode_entry(self):
        findings = detect("x = {'view_mode': 'form,tree'}\n", path="m.py")
        self.assertEqual([f.matched for f in findings], ["tree"])

    def test_clean_document_has_no_findings(self):
        self.assertEqual(detect("<list/>"), [])
        self.assertEqual(detect("x = {'view_mode': 'list,form'}\n", path="m.py"), [])

    def test_detector_never_edits(self):
        document = Document.from_text("v.xml", "<tree/>")
        self.assertEqual(len(vt.flag_view_type(document, CTX, from_type="tree")), 1)
        self.assertEqual(document.text, "<tree/>")


class CatalogueBindingTests(unittest.TestCase):
    def test_catalogue_entry_binds_and_applies(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        bound = bind_rule(meta, BINDABLE_MODULES)
        document = Document.from_text("v.xml", "<tree/>")
        self.assertEqual(len(bound.detect(document)), 1)
        self.assertEqual(bound.maturity, "FIX_ENABLED")
        self.assertFalse(bound.review_required)
        self.assertEqual(bound.context.severity, "CRITICAL")


if __name__ == "__main__":
    unittest.main()
