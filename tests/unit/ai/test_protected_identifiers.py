"""TST-007-008 (REQ-AI-003, FR-006, F-AI-7): protected identifiers are never changed by an AI edit."""

import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.protected import protected_changes

CLASS = '''class A(models.Model):
    _name = "kbi.a"
    _inherit = ["mail.thread"]

    name = fields.Char()
    qty = fields.Integer()

    def go(self):
        return 1
'''
IMPORTS = "from odoo.exceptions import UserError, ValidationError\nimport os\n"
XML = '<record id="view_a" model="ir.ui.view"><field name="name">n</field><field name="arch" type="xml"><form><field name="qty"/></form></field></record>'


class NegativeTests(unittest.TestCase):
    def test_renamed_field(self):
        after = CLASS.replace("qty = fields.Integer()", "quantity = fields.Integer()")
        self.assertTrue(protected_changes("a.py", CLASS, after))

    def test_changed_name(self):
        self.assertTrue(protected_changes("a.py", CLASS, CLASS.replace("kbi.a", "kbi.b")))

    def test_changed_inherit(self):
        self.assertTrue(protected_changes("a.py", CLASS, CLASS.replace("mail.thread", "mail.other")))

    def test_removed_import_name(self):
        after = "from odoo.exceptions import UserError\nimport os\n"
        self.assertTrue(protected_changes("a.py", IMPORTS, after))

    def test_changed_xml_id(self):
        self.assertTrue(protected_changes("v.xml", XML, XML.replace("view_a", "view_b")))

    def test_removed_xml_field_reference(self):
        self.assertTrue(protected_changes("v.xml", XML, XML.replace('<field name="qty"/>', "")))

    def test_unparseable_original_is_reported_not_silently_accepted(self):
        self.assertTrue(protected_changes("a.py", "def (:\n", "x = 1\n"))


class PositiveTests(unittest.TestCase):
    def test_body_change_keeping_identifiers(self):
        self.assertEqual(protected_changes("a.py", CLASS, CLASS.replace("return 1", "return 2")), [])

    def test_import_path_rewrite_keeping_names(self):
        after = IMPORTS.replace("odoo.exceptions", "odoo.errors")
        self.assertEqual(protected_changes("a.py", IMPORTS, after), [])

    def test_xml_attribute_change_keeping_ids(self):
        self.assertEqual(protected_changes("v.xml", XML, XML.replace('<form>', '<form string="x">')), [])

    def test_indented_method_region(self):
        before = "    def go(self):\n        return old()\n"
        self.assertEqual(protected_changes("a.py", before, before.replace("old", "new")), [])


if __name__ == "__main__":
    unittest.main()
