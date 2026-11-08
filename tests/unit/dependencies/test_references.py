"""TST-006-027 (REQ-DEP-003, REQ-VAL-003): ``*.refs.dangling-reference``."""

import tempfile
import unittest
from pathlib import Path

from odooflux.dependencies import references as refs

from .. import _setup  # noqa: F401

MODELS = "from odoo import fields, models\n\n\nclass Thing(models.Model):\n    _name = 'kbi.thing'\n\n    name = fields.Char()\n"
CLEAN_VIEW = """<odoo>
  <record id="v1" model="ir.ui.view">
    <field name="name">t</field><field name="model">kbi.thing</field>
    <field name="arch" type="xml"><form><field name="name"/></form></field>
  </record>
</odoo>
"""


def build(root: Path, files: dict, data):
    module = root / "kbi"
    module.mkdir()
    (module / "__manifest__.py").write_text(
        repr({"name": "k", "depends": ["base"], "data": list(data)}), encoding="utf-8")
    for rel, text in files.items():
        path = module / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return module


class DanglingReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def scan(self, files, data):
        return refs.scan_references([build(self.root, files, data)])

    def test_clean_module_has_no_findings(self):
        report = self.scan({"models/m.py": MODELS, "views/v.xml": CLEAN_VIEW}, ["views/v.xml"])
        self.assertEqual(report.findings, [])

    def test_dangling_xml_id_unknown_field_unknown_model_yield_three_findings(self):
        view = CLEAN_VIEW.replace('<field name="name"/></form>', '<field name="ghost"/></form>')
        extra = ('<odoo><record id="v2" model="ir.ui.view"><field name="inherit_id" ref="kbi.view_missing"/>'
                 '</record></odoo>')
        py = MODELS + "\n\ndef f(env):\n    return env['kbi.phantom']\n"
        report = self.scan({"models/m.py": py, "views/v.xml": view, "views/x.xml": extra},
                           ["views/v.xml", "views/x.xml"])
        self.assertEqual(len(report.findings), 3)
        self.assertEqual({f.rule_id for f in report.findings}, {"*.refs.dangling-reference"})
        self.assertEqual({f.matched for f in report.findings}, {"ghost", "kbi.view_missing", "kbi.phantom"})
        self.assertTrue(all(f.severity == "CRITICAL" for f in report.findings))

    def test_core_references_are_reported_unverified(self):
        extra = ('<odoo><record id="v2" model="ir.ui.view"><field name="inherit_id" ref="base.view_partner_form"/>'
                 '</record></odoo>')
        report = self.scan({"models/m.py": MODELS, "views/x.xml": extra}, ["views/x.xml"])
        self.assertEqual(report.findings, [])
        self.assertTrue(report.unverified)
        self.assertTrue(all(line.startswith("unverified (core): ") for line in report.unverified))

    def test_group_reference_is_dangling_too(self):
        extra = '<odoo><menuitem id="m" name="M" groups="kbi.group_missing"/></odoo>'
        report = self.scan({"models/m.py": MODELS, "views/x.xml": extra}, ["views/x.xml"])
        self.assertEqual([f.matched for f in report.findings], ["kbi.group_missing"])


if __name__ == "__main__":
    unittest.main()
