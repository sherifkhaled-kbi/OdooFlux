"""TST-006-029 (REQ-BIZ-001): business-logic risk inventory, one positive and one negative case per class (R-7)."""

import tempfile
import unittest
from pathlib import Path

from odooflux.analyzers import risk_inventory as ri

from .. import _setup  # noqa: F401

CLASSES = ("orm-override", "computed-field", "onchange", "constraint", "multi-company", "transaction",
           "cron", "controller", "security-sensitive", "integration")


def classes_of(src, path="m.py"):
    return sorted({item.risk_class for item in ri.inventory_python(path, src)})


MODEL = "from odoo import models, fields, api\n\n\nclass A(models.Model):\n    _name = 'a'\n"


class ClassTests(unittest.TestCase):
    def test_all_ten_classes_are_known(self):
        self.assertEqual(tuple(ri.RISK_CLASSES), CLASSES)

    def test_orm_override_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    def write(self, vals):\n        return super().write(vals)\n"), ["orm-override"])
        self.assertEqual(classes_of(MODEL + "    def helper(self):\n        return 1\n"), [])
        self.assertEqual(classes_of("class Plain:\n    def write(self):\n        pass\n"), [])

    def test_computed_field_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    x = fields.Float(compute='_c')\n"), ["computed-field"])
        self.assertEqual(classes_of(MODEL + "    @api.depends('x')\n    def _c(self):\n        pass\n"), ["computed-field"])
        self.assertEqual(classes_of(MODEL + "    x = fields.Float()\n"), [])

    def test_onchange_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    @api.onchange('x')\n    def f(self):\n        pass\n"), ["onchange"])
        self.assertEqual(classes_of(MODEL + "    @api.model\n    def f(self):\n        pass\n"), [])

    def test_constraint_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    @api.constrains('x')\n    def f(self):\n        pass\n"), ["constraint"])
        self.assertEqual(classes_of(MODEL + "    _sql_constraints = [('u', 'unique(x)', 'm')]\n"), ["constraint"])
        self.assertEqual(classes_of(MODEL + "    _u = models.Constraint('unique(x)', 'm')\n"), ["constraint"])
        self.assertEqual(classes_of(MODEL + "    _description = 'x'\n"), [])

    def test_multi_company_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    company_id = fields.Many2one('res.company')\n"), ["multi-company"])
        self.assertEqual(classes_of(MODEL + "    _check_company_auto = True\n"), ["multi-company"])
        self.assertEqual(classes_of(MODEL + "    def f(self):\n        return self.with_company(1)\n"), ["multi-company"])
        self.assertEqual(classes_of(MODEL + "    partner_id = fields.Many2one('res.partner')\n"), [])

    def test_transaction_positive_and_negative(self):
        self.assertEqual(classes_of("def f(self):\n    self.env.cr.commit()\n"), ["transaction"])
        self.assertEqual(classes_of("def f(self):\n    self._cr.execute('select 1')\n"), ["transaction"])
        self.assertEqual(classes_of("def f(self):\n    with self.env.cr.savepoint():\n        pass\n"), ["transaction"])
        self.assertEqual(classes_of("def f(self):\n    return self.env['a'].search([])\n"), [])

    def test_cron_positive_and_negative(self):
        self.assertEqual(classes_of(MODEL + "    def _cron_sync(self):\n        pass\n"), ["cron"])
        xml = '<odoo><record id="c" model="ir.cron"><field name="name">n</field></record></odoo>'
        self.assertEqual([i.risk_class for i in ri.inventory_xml("d.xml", xml)], ["cron"])
        self.assertEqual(ri.inventory_xml("d.xml", '<odoo><record id="c" model="res.partner"/></odoo>'), [])
        self.assertEqual(classes_of(MODEL + "    def sync(self):\n        pass\n"), [])

    def test_controller_positive_and_negative(self):
        src = "from odoo import http\n\n\nclass C(http.Controller):\n    @http.route('/x', auth='user')\n    def f(self):\n        pass\n"
        self.assertEqual(classes_of(src), ["controller"])
        self.assertEqual(classes_of("class C:\n    def f(self):\n        pass\n"), [])

    def test_security_sensitive_positive_and_negative(self):
        self.assertEqual(classes_of("def f(self):\n    return self.sudo().x\n"), ["security-sensitive"])
        self.assertEqual(classes_of("def f(self):\n    return self.with_user(2).x\n"), ["security-sensitive"])
        route = "from odoo import http\n\n\nclass C:\n    @http.route('/x', auth='public', csrf=False)\n    def f(self):\n        pass\n"
        self.assertEqual(classes_of(route), ["controller", "security-sensitive"])
        self.assertEqual(classes_of("class C:\n    @http.route('/x', auth='user')\n    def f(self):\n        pass\n"), ["controller"])

    def test_integration_positive_and_negative(self):
        for imp in ("import requests", "from urllib.request import urlopen", "import xmlrpc.client", "import smtplib"):
            self.assertEqual(classes_of(imp + "\n"), ["integration"], imp)
        self.assertEqual(classes_of("import json\nimport os\n"), [])

    def test_items_carry_line_and_detail(self):
        items = ri.inventory_python("m.py", MODEL + "    def write(self, vals):\n        pass\n")
        self.assertEqual((items[0].line, items[0].path), (6, "m.py"))
        self.assertIn("write", items[0].detail)

    def test_unparseable_python_yields_nothing(self):
        self.assertEqual(ri.inventory_python("m.py", "def (:\n"), [])


class ModuleInventoryTests(unittest.TestCase):
    def test_module_inventory_has_every_class_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "m"
            (root / "models").mkdir(parents=True)
            (root / "data").mkdir()
            (root / "__manifest__.py").write_text("{'name': 'm', 'depends': ['base']}")
            (root / "models" / "a.py").write_text(MODEL + "    def create(self, vals):\n        pass\n")
            (root / "data" / "c.xml").write_text('<odoo><record id="c" model="ir.cron"/></odoo>')
            inv = ri.inventory_module(root)
            self.assertEqual(tuple(inv["classes"]), CLASSES)
            self.assertEqual(inv["counts"]["orm-override"], 1)
            self.assertEqual(inv["counts"]["cron"], 1)
            self.assertEqual(inv["counts"]["onchange"], 0)
            self.assertEqual(inv["classes"]["orm-override"][0]["path"], "models/a.py")
            self.assertEqual(inv["total"], 2)

    def test_inventory_is_attached_to_module_report_when_present(self):
        from odooflux.reporting.model import model as report_model
        entry = {"name": "m", "status": "DONE", "risk_inventory": {"total": 0, "counts": {}, "classes": {}}}
        self.assertEqual(report_model.attach_inventory({"name": "m"}, entry)["risk_inventory"]["total"], 0)
        self.assertNotIn("risk_inventory", report_model.attach_inventory({"name": "m"}, {"name": "m"}))


if __name__ == "__main__":
    unittest.main()
