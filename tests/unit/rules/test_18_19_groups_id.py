"""TST-006-014 (REQ-PY-003, REQ-ACL-001): rule 18-19.any.res-users-groups-id, detect-only review (EV-114).

``res.users.groups_id`` (18.0) is ``group_ids`` in 19.0. The detector covers the three file kinds where the field is
referenced: Python (attribute access and string values), XML (``<field name="groups_id">`` and the domain/eval text
of views and records) and CSV data (a header column ``groups_id`` or ``groups_id:id``). It never edits.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.security import field_refs
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from .. import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "18-19.any.res-users-groups-id"
CTX = RuleContext(rule_id=RULE_ID, severity="WARNING", step="18-19", message="renamed", suggestion="review")
PARAMS = {"field": "groups_id"}


def detect(text, path):
    return field_refs.flag_field_reference(Document.from_text(path, text), CTX, **PARAMS)


class PythonTests(unittest.TestCase):
    def test_attribute_access_is_reported(self):
        findings = detect("uids = self.env.user.groups_id.ids\n", "m.py")
        self.assertEqual([f.matched for f in findings], ["self.env.user.groups_id"])

    def test_string_field_name_in_domain_is_reported(self):
        self.assertEqual(len(detect("users = self.search([('groups_id', 'in', [g.id])])\n", "m.py")), 1)

    def test_dict_key_is_reported(self):
        self.assertEqual(len(detect("user.write({'groups_id': [(4, group.id)]})\n", "m.py")), 1)

    def test_group_ids_is_not_reported(self):
        self.assertEqual(detect("user.write({'group_ids': [(4, group.id)]})\nx = user.group_ids\n", "m.py"), [])

    def test_docstring_and_comment_are_not_reported(self):
        self.assertEqual(detect('"""groups_id is renamed."""\n# groups_id here\n', "m.py"), [])

    def test_partial_string_is_not_reported(self):
        self.assertEqual(detect("x = 'groups_ids'\n", "m.py"), [])


class XmlTests(unittest.TestCase):
    def test_field_element_is_reported(self):
        findings = detect('<record model="ir.ui.view" id="v"><field name="groups_id" eval="[(4, ref(\'base.group_user\'))]"/></record>',
                          "v.xml")
        self.assertEqual([f.matched for f in findings], ['name="groups_id"'])

    def test_domain_attribute_token_is_reported(self):
        findings = detect("<field name=\"domain\" eval=\"[('groups_id', 'in', [ref('base.group_user')])]\"/>", "v.xml")
        self.assertEqual(len(findings), 1)

    def test_domain_force_element_text_is_reported(self):
        findings = detect("<record model='ir.rule' id='r'><field name='domain_force'>[('groups_id', 'in', [1])]</field></record>",
                          "r.xml")
        self.assertEqual(len(findings), 1)

    def test_other_fields_are_not_reported(self):
        self.assertEqual(detect('<record model="ir.ui.view" id="v"><field name="group_ids"/></record>', "v.xml"), [])

    def test_longer_token_in_eval_is_not_reported(self):
        self.assertEqual(detect("<field name=\"eval\" eval=\"user.groups_idx\"/>", "v.xml"), [])

    def test_malformed_xml_yields_no_findings(self):
        self.assertEqual(detect('<field name="groups_id">', "v.xml"), [])


class CsvTests(unittest.TestCase):
    def test_header_column_is_reported_once(self):
        findings = detect("id,name,groups_id:id\nu1,Ann,base.group_user\n", "res.users.csv")
        self.assertEqual([f.line for f in findings], [1])
        self.assertEqual(findings[0].matched, "groups_id:id")

    def test_plain_header_column_is_reported(self):
        self.assertEqual(len(detect("id,groups_id\nu1,base.group_user\n", "users.csv")), 1)

    def test_access_csv_group_id_column_is_not_reported(self):
        self.assertEqual(detect("id,name,model_id:id,group_id:id\nacc,a,m,g\n", "ir.model.access.csv"), [])

    def test_data_rows_are_not_reported(self):
        self.assertEqual(detect("id,name\nu1,groups_id\n", "users.csv"), [])


class CatalogueTests(unittest.TestCase):
    def test_entry_is_detect_only_review_without_fixer(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.review_required)
        self.assertIsNone(bound.fixer)
        self.assertEqual(sorted(meta["file_kinds"]), ["csv", "python", "xml"])
        document = Document.from_text("m.py", "x = u.groups_id\n")
        self.assertEqual(bound.fix(document), [])
        self.assertEqual(len(bound.detect(document)), 1)


if __name__ == "__main__":
    unittest.main()
