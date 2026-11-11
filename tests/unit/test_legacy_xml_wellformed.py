"""D6: the legacy XML fixer must never emit text that is not well-formed XML.

Each case reproduces a malformation that the regex rewrites produced on small inputs. The fixer either produces the
correct, well-formed rewrite, or returns the original text unchanged. Running it twice changes nothing more.
"""

import unittest
import xml.etree.ElementTree as ET

from odooflux.rules.shared.legacy_rules import apply_xml_fixes


def _well_formed(text: str) -> bool:
    try:
        ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return False
    return True


class ChatterBlockWellFormed(unittest.TestCase):
    """The <div class="oe_chatter"> replacement (v18+ targets) must balance its own <div> tags."""

    def test_nested_div_with_a_div_prefixed_tag_is_replaced_cleanly(self):
        src = '<form><sheet/><div class="oe_chatter"><div class="x"><divider/></div></div></form>'
        out = apply_xml_fixes(src, 16, 18)
        self.assertTrue(_well_formed(out), out)
        self.assertEqual(out, "<form><sheet/><chatter/></form>")

    def test_self_closing_chatter_div_does_not_swallow_following_elements(self):
        src = '<form><div class="oe_chatter"/><div><span/></div></form>'
        out = apply_xml_fixes(src, 16, 18)
        self.assertTrue(_well_formed(out), out)
        self.assertEqual(out, "<form><chatter/><div><span/></div></form>")

    def test_plain_nested_chatter_block_is_still_replaced(self):
        src = '<form><sheet/><div class="oe_chatter"><div class="x"><span/></div></div></form>'
        self.assertEqual(apply_xml_fixes(src, 16, 18), "<form><sheet/><chatter/></form>")


class StatesRewriteWellFormed(unittest.TestCase):
    """The states= rewrite (verified state field only) must keep attribute values intact."""

    def test_gt_inside_a_quoted_attribute_value_keeps_the_tag_well_formed(self):
        src = '<form><button name="a" states="draft" string="a > b"/></form>'
        out = apply_xml_fixes(src, 16, 17, verified_state_field=True)
        self.assertTrue(_well_formed(out), out)
        self.assertEqual(out, '<form><button name="a" string="a > b" invisible="state not in [\'draft\']"/></form>')

    def test_element_with_attrs_is_left_for_the_experimental_fixer(self):
        src = ('<form><field name="x" states="draft" '
               "attrs=\"{'readonly': [('a', '>', 1)]}\"/></form>")
        out = apply_xml_fixes(src, 16, 17, verified_state_field=True)
        self.assertEqual(out, src)

    def test_states_rewrite_is_not_applied_to_a_similarly_named_attribute(self):
        src = '<form><field name="x" string="states=\'a\'"/></form>'
        self.assertEqual(apply_xml_fixes(src, 16, 17, verified_state_field=True), src)


class TreeTagWellFormed(unittest.TestCase):
    def test_closing_tag_with_whitespace_before_the_bracket_is_renamed(self):
        src = '<odoo><tree><field name="a"/></tree ></odoo>'
        out = apply_xml_fixes(src, 16, 18)
        self.assertTrue(_well_formed(out), out)
        self.assertEqual(out, '<odoo><list><field name="a"/></list ></odoo>')


class FieldRemovalWellFormed(unittest.TestCase):
    """Removal of message_ids / mail_thread fields (v18+) must not eat sibling elements."""

    def test_self_closing_field_with_a_slash_in_an_attribute_does_not_eat_siblings(self):
        src = '<form><field name="message_ids" context="{\'a\': \'/\'}"/><field name="b"><group/></field></form>'
        out = apply_xml_fixes(src, 16, 18)
        self.assertTrue(_well_formed(out), out)
        self.assertEqual(out, '<form><field name="b"><group/></field></form>')

    def test_mail_thread_self_closing_field_with_a_slash_does_not_eat_siblings(self):
        src = '<form><field name="x" widget="mail_thread" context="{\'a\': \'/\'}"/><field name="b"><group/></field></form>'
        out = apply_xml_fixes(src, 16, 18)
        self.assertTrue(_well_formed(out), out)
        self.assertIn('<field name="b"><group/></field>', out)


class OutputGuard(unittest.TestCase):
    """Whenever the output would not be well-formed, the original text is returned."""

    def test_malformed_input_whose_rewrite_stays_malformed_is_returned_unchanged(self):
        src = "<form><tree>x</form>"  # the <tree> rename changes the text, but the document was never well-formed
        self.assertEqual(apply_xml_fixes(src, 16, 18), src)

    def test_well_formed_input_never_comes_back_malformed(self):
        samples = [
            '<form><sheet/><div class="oe_chatter"><div class="x"><divider/></div></div></form>',
            '<form><button name="a" states="draft" string="a > b"/></form>',
            '<odoo><tree><field name="a"/></tree ></odoo>',
            '<form><field name="message_ids" context="{\'a\': \'/\'}"/><field name="b"><group/></field></form>',
        ]
        for src in samples:
            for target in (17, 18, 19):
                out = apply_xml_fixes(src, 16, target, verified_state_field=True)
                self.assertTrue(_well_formed(out), (target, out))


class Idempotence(unittest.TestCase):
    def test_second_pass_changes_nothing(self):
        samples = [
            '<form><sheet/><div class="oe_chatter"><div class="x"><divider/></div></div></form>',
            '<form><div class="oe_chatter"/><div><span/></div></form>',
            '<form><button name="a" states="draft" string="a > b"/></form>',
            '<odoo><tree><field name="a"/></tree ></odoo>',
            '<form><field name="message_ids" context="{\'a\': \'/\'}"/><field name="b"><group/></field></form>',
            "<form><tree>x</form>",
        ]
        for src in samples:
            for target in (17, 18, 19):
                once = apply_xml_fixes(src, 16, target, verified_state_field=True)
                self.assertEqual(apply_xml_fixes(once, 16, target, verified_state_field=True), once, (target, src))


if __name__ == "__main__":
    unittest.main()
