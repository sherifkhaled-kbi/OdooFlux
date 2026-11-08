"""TST-011-052 (REQ-KAP-011): reports, controllers (QWeb) and migration-script extractors.

Route, report-action and migration facts come from small in-memory trees built with the real `build_snapshot` and
`BlobStore`, then run through `extract/driver.extract_pair`. Migration scripts are parsed with `ast` only. An
unparsable file is FAILED with a reason, never skipped.
"""

import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract.domains import migration_scripts, reports_controllers
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

ADDON = "addons/sale_demo"
CONTROLLER = f"{ADDON}/controllers/main.py"
REPORT = f"{ADDON}/report/sale_report.xml"
MIGRATION = f"{ADDON}/migrations/17.0.1.0.0/post-migrate.py"

CONTROLLER_16 = '''from odoo import http


class SaleDemoController(http.Controller):
    @http.route('/sale_demo/order', type='http', auth='user', methods=['GET'])
    def order(self):
        return "ok"
'''
CONTROLLER_17 = CONTROLLER_16.replace("'/sale_demo/order'", "'/sale_demo/order/v2'")

REPORT_16 = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_report_sale_demo" model="ir.actions.report">
        <field name="name">Sale Demo</field>
        <field name="model">sale.demo.order</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">sale_demo.report_order</field>
        <field name="binding_model_id" ref="model_sale_demo_order"/>
    </record>
    <template id="report_order">
        <t t-call="web.external_layout">
            <p t-esc="doc.name"/>
        </t>
    </template>
</odoo>
'''
REPORT_17 = (REPORT_16.replace("sale_demo.report_order", "sale_demo.report_order_v17")
             .replace('<p t-esc="doc.name"/>', '<p t-esc="doc.display_name"/>'))

MIGRATE_17 = '''from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sale.demo.order'].search([]).write({'priority': 0})
    cr.execute("UPDATE sale_demo_order SET priority = 0 WHERE priority IS NULL")
'''


class ReportCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "objects")

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, name, files):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        return build_snapshot(root, "src", "r1", self.store, created_at="2026-01-01T00:00:00Z")

    def run_pair(self, before, after, registry=None):
        return d.extract_pair(before, after, None, registry or reports_controllers.EXTRACTORS + (
            migration_scripts.EXTRACTORS), store=self.store, step="01-02", toolkit=TOOLKIT)


class TestRouteDiff(ReportCase):
    def test_route_diff_golden(self):
        before = self.snapshot("a", {CONTROLLER: CONTROLLER_16})
        after = self.snapshot("b", {CONTROLLER: CONTROLLER_17})
        result = self.run_pair(before, after)
        routes = [(c["subject_key"], c["class"], c["detail"]["changed"]) for c in result.drafts
                  if c["domain"] == "report_controller"]
        self.assertEqual(routes, [("sale_demo.SaleDemoController.order", "SIGNATURE_CHANGED", ["path"])])

    def test_route_facts_carry_route_keys(self):
        facts = reports_controllers.ReportControllerExtractor().facts(CONTROLLER_16, CONTROLLER, TOOLKIT)
        self.assertEqual(len(facts), 1)
        attrs = facts[0]["attrs"]
        self.assertEqual((facts[0]["kind"], attrs["path"], attrs["type"], attrs["auth"], attrs["methods"]),
                         ("route", "/sale_demo/order", "http", "user", ["GET"]))


class TestReportAction(ReportCase):
    def test_report_action_golden(self):
        before = self.snapshot("a", {REPORT: REPORT_16})
        after = self.snapshot("b", {REPORT: REPORT_17})
        result = self.run_pair(before, after)
        found = sorted((c["subject_key"], c["class"]) for c in result.drafts if c["domain"] == "report_controller")
        # a changed report_name is an attribute of the action (signature); a changed QWeb body is behaviour
        self.assertEqual(found, [("action_report_sale_demo", "SIGNATURE_CHANGED"),
                                 ("report_order", "BEHAVIOUR_CHANGED")])

    def test_report_action_attrs(self):
        facts = reports_controllers.ReportControllerExtractor().facts(REPORT_16, REPORT, TOOLKIT)
        actions = {f["subject_key"]: f["attrs"] for f in facts if f["kind"] == "report"}
        self.assertEqual(actions["action_report_sale_demo"]["report_name"], "sale_demo.report_order")
        self.assertEqual(actions["action_report_sale_demo"]["model"], "sale.demo.order")

    def test_unmodelled_top_level_element_is_unsupported(self):
        text = '<?xml version="1.0"?>\n<odoo>\n    <menuitem id="m1" name="x"/>\n</odoo>\n'
        before = self.snapshot("a", {})
        after = self.snapshot("b", {REPORT: text})
        result = self.run_pair(before, after)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("UNSUPPORTED", "NO_PARSER"))


class TestMigrationScripts(ReportCase):
    def test_migration_refs_golden(self):
        facts = migration_scripts.MigrationScriptExtractor().facts(MIGRATE_17, MIGRATION, TOOLKIT)
        self.assertEqual(len(facts), 1)
        fact = facts[0]
        self.assertEqual(fact["subject_key"], "sale_demo::17.0.1.0.0::post-migrate.py")
        self.assertEqual(fact["kind"], "script")
        self.assertEqual(fact["attrs"], {"stage": "post", "version": "17.0.1.0.0",
                                         "models": ["sale.demo.order"], "tables": ["sale_demo_order"],
                                         "functions": ["migrate"]})

    def test_added_migration_is_added(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {MIGRATION: MIGRATE_17})
        result = self.run_pair(before, after)
        added = [c["subject_key"] for c in result.drafts if c["domain"] == "migration_script"]
        self.assertEqual(added, ["sale_demo::17.0.1.0.0::post-migrate.py"])

    def test_default_registry_runs_migration_extraction(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {MIGRATION: MIGRATE_17})
        result = d.extract_pair(before, after, None, d.default_registry(), store=self.store, step="01-02", toolkit=TOOLKIT)
        added = [c["subject_key"] for c in result.drafts if c["domain"] == "migration_script"]
        self.assertEqual(added, ["sale_demo::17.0.1.0.0::post-migrate.py"])

    def test_unparsable_migration_is_failed(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {MIGRATION: "def migrate(cr, version:\n    pass\n"})
        result = self.run_pair(before, after)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))
        unknown = [c for c in result.drafts if c["class"] == "UNKNOWN"]
        self.assertEqual([c["subject_key"] for c in unknown], [MIGRATION])

    def test_handles_only_migration_scripts_and_reports(self):
        migrate = migration_scripts.MigrationScriptExtractor()
        self.assertTrue(migrate.handles(MIGRATION, TOOLKIT))
        self.assertFalse(migrate.handles(f"{ADDON}/models/sale_order.py", TOOLKIT))
        self.assertTrue(reports_controllers.ReportControllerExtractor().handles(REPORT, TOOLKIT))
        self.assertFalse(reports_controllers.ReportControllerExtractor().handles(f"{ADDON}/views/v.xml", TOOLKIT))


if __name__ == "__main__":
    unittest.main()
