"""T0 (AD-5): the legacy XML fixer is gated by the target version.

Odoo 18+ conversions (<tree> -> <list>, view_type/view_mode tree -> list, chatter block) must not run
for a 16 -> 17 target. Targets 18 and 19 keep today's output; the <openerp> and groups_id conversions are
unchanged for every target. states= is rewritten only when the caller verifies the view's model has a state field
(D2), so it is left as written in these snippets.
"""

import unittest

from odooflux.rules.shared.legacy_rules import apply_xml_fixes

SRC = """<openerp>
  <data>
    <record id="view_form" model="ir.ui.view">
      <field name="arch" type="xml">
        <form>
          <field name="name" states="draft,open"/>
          <field name="message_ids" widget="mail_thread"/>
          <field name="note" widget="mail_thread"/>
          <div class="oe_chatter">
            <field name="message_follower_ids"/>
          </div>
        </form>
      </field>
    </record>
    <record id="view_tree" model="ir.ui.view">
      <field name="arch" type="xml">
        <tree string="Items" groups_id="base.group_user">
          <field name="name"/>
        </tree>
      </field>
    </record>
    <record id="act" model="ir.actions.act_window">
      <field name="view_mode">tree,form</field>
      <field name="view_type">tree</field>
    </record>
    <record id="act2" model="ir.actions.act_window">
      <field name="view_mode" eval="x">tree,form</field>
    </record>
    <act_window name="A" view_mode="tree,form" view_type="tree" res_model="x"/>
  </data>
</openerp>
"""

# Target 17: only the version-independent conversions apply. <tree>, view_mode, view_type, the
# chatter div and the chatter fields are left exactly as they were.
EXPECTED_17 = """<odoo>
  <data>
    <record id="view_form" model="ir.ui.view">
      <field name="arch" type="xml">
        <form>
          <field name="name" states="draft,open"/>
          <field name="message_ids" widget="mail_thread"/>
          <field name="note" widget="mail_thread"/>
          <div class="oe_chatter">
            <field name="message_follower_ids"/>
          </div>
        </form>
      </field>
    </record>
    <record id="view_tree" model="ir.ui.view">
      <field name="arch" type="xml">
        <tree string="Items" groups="base.group_user">
          <field name="name"/>
        </tree>
      </field>
    </record>
    <record id="act" model="ir.actions.act_window">
      <field name="view_mode">tree,form</field>
      <field name="view_type">tree</field>
    </record>
    <record id="act2" model="ir.actions.act_window">
      <field name="view_mode" eval="x">tree,form</field>
    </record>
    <act_window name="A" view_mode="tree,form" view_type="tree" res_model="x"/>
  </data>
</odoo>
"""

# Targets 18 and 19: captured from the fixer before the version gate existed.
EXPECTED_18_19 = (
    "<odoo>\n"
    "  <data>\n"
    "    <record id=\"view_form\" model=\"ir.ui.view\">\n"
    "      <field name=\"arch\" type=\"xml\">\n"
    "        <form>\n"
    "          <field name=\"name\" states=\"draft,open\"/>\n"
    "          \n"  # the removed message_ids field leaves its indentation behind (existing behaviour)
    "          <chatter/>\n"
    "          <chatter/>\n"
    "        </form>\n"
    "      </field>\n"
    "    </record>\n"
    "    <record id=\"view_tree\" model=\"ir.ui.view\">\n"
    "      <field name=\"arch\" type=\"xml\">\n"
    "        <list string=\"Items\" groups=\"base.group_user\">\n"
    "          <field name=\"name\"/>\n"
    "        </list>\n"
    "      </field>\n"
    "    </record>\n"
    "    <record id=\"act\" model=\"ir.actions.act_window\">\n"
    "      <field name=\"view_mode\">list,form</field>\n"
    "      <field name=\"view_type\">list</field>\n"
    "    </record>\n"
    "    <record id=\"act2\" model=\"ir.actions.act_window\">\n"
    "      <field name=\"view_mode\" eval=\"x\">list,form</field>\n"
    "    </record>\n"
    "    <act_window name=\"A\" view_mode=\"list,form\" view_type=\"list\" res_model=\"x\"/>\n"
    "  </data>\n"
    "</odoo>\n"
)


class TargetGatingTests(unittest.TestCase):

    def test_target_17_keeps_tree_view_mode_view_type_and_chatter(self):
        self.assertEqual(apply_xml_fixes(SRC, 16, to_version=17), EXPECTED_17)

    def test_target_17_has_no_list_or_chatter_constructs(self):
        out = apply_xml_fixes(SRC, 16, to_version=17)
        self.assertNotIn("<list", out)
        self.assertNotIn("</list>", out)
        self.assertNotIn("list,form", out)
        self.assertNotIn("<chatter", out)
        self.assertIn("<tree", out)
        self.assertIn("</tree>", out)

    def test_target_18_output_unchanged(self):
        self.assertEqual(apply_xml_fixes(SRC, 16, to_version=18), EXPECTED_18_19)

    def test_target_19_output_unchanged(self):
        self.assertEqual(apply_xml_fixes(SRC, 16, to_version=19), EXPECTED_18_19)

    def test_no_to_version_behaves_as_target_19(self):
        self.assertEqual(apply_xml_fixes(SRC, 16), EXPECTED_18_19)
        self.assertEqual(apply_xml_fixes(SRC, 16), apply_xml_fixes(SRC, 16, to_version=19))


class VersionIndependentConversionTests(unittest.TestCase):
    """<openerp> -> <odoo> and groups_id= -> groups= apply for every target; states= needs a verified state field (D2)."""

    def test_openerp_root_converted_for_every_target(self):
        for target in (17, 18, 19):
            out = apply_xml_fixes("<openerp><data/></openerp>\n", 16, to_version=target)
            self.assertEqual(out, "<odoo><data/></odoo>\n", target)

    def test_states_left_alone_without_a_verified_state_field_for_every_target(self):
        src = '<form><button name="x" states="draft,open"/></form>'
        for target in (17, 18, 19):
            self.assertEqual(apply_xml_fixes(src, 16, to_version=target), src, target)

    def test_states_converted_for_every_target_when_the_state_field_is_verified(self):
        src = '<form><button name="x" states="draft,open"/></form>'
        expected = "<form><button name=\"x\" invisible=\"state not in ['draft', 'open']\"/></form>"
        for target in (17, 18, 19):
            self.assertEqual(apply_xml_fixes(src, 16, to_version=target, verified_state_field=True), expected, target)

    def test_groups_id_converted_for_every_target(self):
        src = '<menuitem id="m" name="M" groups_id="base.group_user"/>'
        expected = '<menuitem id="m" name="M" groups="base.group_user"/>'
        for target in (17, 18, 19):
            self.assertEqual(apply_xml_fixes(src, 16, to_version=target), expected, target)


if __name__ == "__main__":
    unittest.main()
