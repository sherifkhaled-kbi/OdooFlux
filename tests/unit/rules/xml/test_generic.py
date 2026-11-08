"""TST-006-004 (REQ-XML-003, REQ-XML-005): generic XML and QWeb detectors and fixers.

Fixers must keep the output well-formed, touch only the requested constructs, and produce no edits on a
second application. Detectors report findings and never edit. Malformed input yields nothing.
"""

import unittest
import xml.etree.ElementTree as ET

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.rules.qweb import generic as qg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.xml import generic as xg
from odooflux.rules.xml import view_mode as vm

from ... import _setup  # noqa: F401  (src first on sys.path)

CTX = RuleContext(rule_id="test.xml-generic", severity="WARNING", step="17-18",
                  message="xml message", suggestion="xml suggestion")
PATH = "v.xml"


def fix(fixer, text, **params):
    """Apply a fixer once, return (result, second-pass edits)."""
    document = Document.from_text(PATH, text)
    result = apply_edits(document, fixer(document, CTX, **params), precedence=[CTX.rule_id])
    second = fixer(Document.from_text(PATH, result.text), CTX, **params)
    return result, second


def detect(detector, text, **params):
    return detector(Document.from_text(PATH, text), CTX, **params)


def assert_well_formed(test, text):
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:  # pragma: no cover - failure path
        test.fail(f"output is not well-formed: {exc}")


class RenameTagTests(unittest.TestCase):
    def assertRenamed(self, text, expected, **params):
        result, second = fix(xg.rename_tag, text, **params)
        self.assertEqual(result.rejected, ())
        self.assertTrue(result.preserved_ok)
        self.assertEqual(result.text, expected)
        assert_well_formed(self, result.text)
        self.assertEqual(second, [])

    def test_start_and_end_tags_are_renamed(self):
        self.assertRenamed("<v><tree string='x'><field name='a'/></tree></v>",
                           "<v><list string='x'><field name='a'/></list></v>", tag="tree", new_tag="list")

    def test_self_closing_element_is_renamed(self):
        self.assertRenamed("<v><tree/></v>", "<v><list/></v>", tag="tree", new_tag="list")

    def test_every_matching_element_is_renamed(self):
        self.assertRenamed("<v><tree/><group><tree>x</tree></group></v>",
                           "<v><list/><group><list>x</list></group></v>", tag="tree", new_tag="list")

    def test_similar_names_are_not_renamed(self):
        text = "<v><treeview/><tree-x/></v>"
        self.assertRenamed(text, text, tag="tree", new_tag="list")

    def test_crlf_and_non_ascii_are_preserved(self):
        self.assertRenamed("<v>\r\n<!-- café -->\r\n<tree/>\r\n</v>\r\n",
                           "<v>\r\n<!-- café -->\r\n<list/>\r\n</v>\r\n", tag="tree", new_tag="list")

    def test_malformed_xml_yields_no_edits(self):
        self.assertEqual(fix(xg.rename_tag, "<v><tree></v>", tag="tree", new_tag="list")[0].text, "<v><tree></v>")

    def test_flag_element_reports_each_match(self):
        findings = detect(xg.flag_element, "<v>\n<tree/>\n<tree>x</tree>\n<form/>\n</v>", tag="tree")
        self.assertEqual([f.line for f in findings], [2, 3])
        self.assertEqual(findings[0].message, "xml message")
        self.assertEqual(findings[0].rule_id, CTX.rule_id)

    def test_flag_element_on_absent_tag_is_empty(self):
        self.assertEqual(detect(xg.flag_element, "<v><form/></v>", tag="tree"), [])


class RemoveAttributeTests(unittest.TestCase):
    def test_attribute_removed_with_its_separator(self):
        result, second = fix(xg.remove_attribute, "<v><field name='x' groups='base.group_user'/></v>",
                             tag="field", attribute="groups")
        self.assertEqual(result.text, "<v><field name='x'/></v>")
        self.assertEqual(second, [])

    def test_attribute_removed_from_any_element_without_tag_filter(self):
        result, _ = fix(xg.remove_attribute, "<v><a attrs='{}'/><b attrs='{}'/></v>", attribute="attrs")
        self.assertEqual(result.text, "<v><a/><b/></v>")

    def test_tag_filter_limits_removal(self):
        text = "<v><a groups='g'/><b groups='g'/></v>"
        result, _ = fix(xg.remove_attribute, text, tag="a", attribute="groups")
        self.assertEqual(result.text, "<v><a/><b groups='g'/></v>")

    def test_absent_attribute_yields_no_edits(self):
        text = "<v><field name='x'/></v>"
        self.assertEqual(fix(xg.remove_attribute, text, tag="field", attribute="groups")[0].text, text)

    def test_flag_attribute_reports_each_element(self):
        findings = detect(xg.flag_attribute, "<v>\n<a attrs='{}'/>\n<b/>\n<c attrs='x'/>\n</v>", attribute="attrs")
        self.assertEqual([f.line for f in findings], [2, 4])

    def test_flag_attribute_respects_tag_filter(self):
        text = "<v><a attrs='1'/><b attrs='1'/></v>"
        self.assertEqual(len(detect(xg.flag_attribute, text, tag="b", attribute="attrs")), 1)


class QwebDirectiveTests(unittest.TestCase):
    def test_directive_renamed(self):
        result, second = fix(qg.rename_directive, "<t t-name='x'><p t-esc='a'/></t>\n",
                             old="t-esc", new="t-out")
        self.assertEqual(result.text, "<t t-name='x'><p t-out='a'/></t>\n")
        assert_well_formed(self, result.text)
        self.assertEqual(second, [])

    def test_every_occurrence_is_renamed(self):
        result, _ = fix(qg.rename_directive, "<t><p t-esc='a'/><span t-esc='b'>c</span></t>",
                        old="t-esc", new="t-out")
        self.assertEqual(result.text, "<t><p t-out='a'/><span t-out='b'>c</span></t>")

    def test_text_content_is_not_renamed(self):
        text = "<t><p>t-esc</p></t>"
        self.assertEqual(fix(qg.rename_directive, text, old="t-esc", new="t-out")[0].text, text)

    def test_element_already_carrying_new_name_is_skipped(self):
        text = "<t><p t-esc='a' t-out='b'/></t>"
        result, _ = fix(qg.rename_directive, text, old="t-esc", new="t-out")
        self.assertEqual(result.text, text)

    def test_invalid_new_name_raises(self):
        with self.assertRaises(ValueError):
            qg.rename_directive(Document.from_text(PATH, "<t t-esc='a'/>"), CTX, old="t-esc", new="t out")

    def test_flag_attribute_detects_raw_directive(self):
        findings = detect(xg.flag_attribute, "<t>\n<p t-raw='a'/>\n</t>", attribute="t-raw")
        self.assertEqual([f.line for f in findings], [2])


class ViewModeTests(unittest.TestCase):
    def test_field_text_token_is_rewritten(self):
        result, second = fix(vm.rewrite_view_mode, "<field name=\"view_mode\">tree,form</field>",
                             from_mode="tree", to_mode="list")
        self.assertEqual(result.text, "<field name=\"view_mode\">list,form</field>")
        self.assertEqual(second, [])

    def test_whitespace_around_tokens_is_kept(self):
        result, _ = fix(vm.rewrite_view_mode, "<field name=\"view_mode\">form, tree</field>",
                        from_mode="tree", to_mode="list")
        self.assertEqual(result.text, "<field name=\"view_mode\">form, list</field>")

    def test_only_whole_tokens_are_rewritten(self):
        result, _ = fix(vm.rewrite_view_mode, "<field name=\"view_mode\">treeview,tree</field>",
                        from_mode="tree", to_mode="list")
        self.assertEqual(result.text, "<field name=\"view_mode\">treeview,list</field>")

    def test_view_mode_attribute_is_rewritten(self):
        result, second = fix(vm.rewrite_view_mode, "<act_window view_mode='form,tree' name='x'/>",
                             from_mode="tree", to_mode="list")
        self.assertEqual(result.text, "<act_window view_mode='form,list' name='x'/>")
        self.assertEqual(second, [])

    def test_other_fields_are_not_touched(self):
        text = "<field name=\"name\">tree</field>"
        self.assertEqual(fix(vm.rewrite_view_mode, text, from_mode="tree", to_mode="list")[0].text, text)

    def test_already_converted_yields_no_edits(self):
        text = "<field name=\"view_mode\">list,form</field>"
        self.assertEqual(fix(vm.rewrite_view_mode, text, from_mode="tree", to_mode="list")[0].text, text)

    def test_flag_view_mode_reports_both_forms(self):
        text = "<v>\n<field name=\"view_mode\">tree,form</field>\n<act_window view_mode='tree'/>\n" \
               "<field name=\"view_mode\">form</field>\n</v>"
        findings = detect(vm.flag_view_mode, text, from_mode="tree")
        self.assertEqual([f.line for f in findings], [2, 3])


if __name__ == "__main__":
    unittest.main()
