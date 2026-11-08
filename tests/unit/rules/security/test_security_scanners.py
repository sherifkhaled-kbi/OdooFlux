"""TST-006-028 (REQ-ACL-001): ACL CSV and record rule scanners."""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.security import acl_csv, record_rules
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

HEADER = "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"


def ctx(rid):
    return RuleContext(rule_id=rid, severity="WARNING", step="*", message="m", suggestion="s")


def csv_doc(text):
    return Document.from_text("security/ir.model.access.csv", text)


def xml_doc(text):
    return Document.from_text("security/rules.xml", text)


class AclCsvScanTests(unittest.TestCase):
    def test_rows_are_parsed_with_lines(self):
        rows = acl_csv.parse_acl(csv_doc(HEADER + "a1,A,model_x,base.group_user,1,0,0,0\n"))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].line, rows[0].values["id"], rows[0].values["group_id:id"]),
                         (2, "a1", "base.group_user"))

    def test_clean_file_has_no_findings(self):
        text = HEADER + "a1,A,model_x,base.group_user,1,0,0,0\na2,B,model_y,,1,1,1,1\n"
        self.assertEqual(acl_csv.flag_acl_issues(csv_doc(text), ctx("*.security.acl-csv")), [])

    def test_missing_required_column_is_reported(self):
        text = "id,name,model_id:id,perm_read\na1,A,model_x,1\n"
        findings = acl_csv.flag_acl_issues(csv_doc(text), ctx("*.security.acl-csv"))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line, 1)

    def test_short_row_is_reported(self):
        findings = acl_csv.flag_acl_issues(csv_doc(HEADER + "a1,A,model_x\n"), ctx("*.security.acl-csv"))
        self.assertEqual([f.line for f in findings], [2])

    def test_non_boolean_permission_is_reported(self):
        findings = acl_csv.flag_acl_issues(csv_doc(HEADER + "a1,A,model_x,,yes,0,0,0\n"), ctx("*.security.acl-csv"))
        self.assertEqual([f.line for f in findings], [2])

    def test_duplicate_id_is_reported_on_second_row(self):
        text = HEADER + "a1,A,model_x,,1,0,0,0\na1,B,model_y,,1,0,0,0\n"
        findings = acl_csv.flag_acl_issues(csv_doc(text), ctx("*.security.acl-csv"))
        self.assertEqual([f.line for f in findings], [3])

    def test_model_id_not_model_xid_is_reported(self):
        findings = acl_csv.flag_acl_issues(csv_doc(HEADER + "a1,A,res.partner,,1,0,0,0\n"), ctx("*.security.acl-csv"))
        self.assertEqual([f.line for f in findings], [2])

    def test_empty_file_has_no_findings(self):
        self.assertEqual(acl_csv.flag_acl_issues(csv_doc(""), ctx("*.security.acl-csv")), [])


RULES = """<odoo>
  <record id="r_global" model="ir.rule">
    <field name="name">all</field>
    <field name="model_id" ref="model_x"/>
    <field name="domain_force">[(1, '=', 1)]</field>
  </record>
  <record id="r_group" model="ir.rule">
    <field name="name">own</field>
    <field name="model_id" ref="model_x"/>
    <field name="domain_force">[('user_id', '=', user.id)]</field>
    <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    <field name="perm_unlink" eval="False"/>
  </record>
  <record id="other" model="res.partner"><field name="name">n</field></record>
</odoo>
"""


class RecordRuleScanTests(unittest.TestCase):
    def test_scan_extracts_rules_only(self):
        rules = record_rules.scan_record_rules(xml_doc(RULES))
        self.assertEqual([r.xml_id for r in rules], ["r_global", "r_group"])
        self.assertEqual(rules[0].model_ref, "model_x")
        self.assertEqual(rules[0].domain, "[(1, '=', 1)]")
        self.assertEqual(rules[1].group_refs, ("base.group_user",))
        self.assertFalse(rules[1].perms["perm_unlink"])
        self.assertTrue(rules[1].perms["perm_read"])

    def test_unrestricted_global_rule_is_reported(self):
        findings = record_rules.flag_unrestricted_global_rules(xml_doc(RULES), ctx("*.security.record-rule"))
        self.assertEqual([f.line for f in findings], [2])

    def test_restricted_and_grouped_rules_are_not_reported(self):
        text = RULES.replace("[(1, '=', 1)]", "[('company_id', 'in', company_ids)]")
        self.assertEqual(record_rules.flag_unrestricted_global_rules(xml_doc(text), ctx("*.security.record-rule")), [])

    def test_empty_domain_without_groups_is_reported(self):
        text = RULES.replace("[(1, '=', 1)]", "[]")
        self.assertEqual(len(record_rules.flag_unrestricted_global_rules(xml_doc(text), ctx("x.x.x"))), 1)

    def test_malformed_xml_yields_nothing(self):
        self.assertEqual(record_rules.scan_record_rules(xml_doc("<odoo><record>")), [])


class CatalogueTests(unittest.TestCase):
    def test_rules_registered_and_bind(self):
        rules = {r["id"]: r for r in load_knowledge().rules}
        for rid in ("*.security.acl-csv", "*.security.unrestricted-record-rule"):
            self.assertIn(rid, rules)
            bound = bind_rule(rules[rid], BINDABLE_MODULES)
            self.assertIsNone(bound.fixer)


if __name__ == "__main__":
    unittest.main()
