"""TST-011-049 (REQ-KAP-011): XML view, security and data extractors on `parsers/xml`.

Golden cases use the synthetic 16.0 and 17.0 trees (`tests/fixtures/kap/make_synth_repo.py`): the view arch gains a
field (BEHAVIOUR_CHANGED) and the security CSV gains the manager access row (ADDED). Record rules and groups are
checked with an inline security XML file.
"""

import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract.domains import security, xml_views
from tests.fixtures.kap import make_synth_repo as synth
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

RULES_16 = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="rule_sale_demo_order_company" model="ir.rule">
        <field name="name">Sale demo order company</field>
        <field name="model_id" ref="model_sale_demo_order"/>
        <field name="domain_force">[('company_id', '=', user.company_id.id)]</field>
    </record>
</odoo>
'''
RULES_17 = RULES_16.replace("user.company_id.id", "user.company_ids.ids").replace(
    "</odoo>",
    '    <record id="group_sale_demo_manager" model="res.groups">\n'
    '        <field name="name">Sale demo manager</field>\n'
    '    </record>\n</odoo>',
)


class XmlCase(unittest.TestCase):
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
            target.write_text(text, encoding="utf-8")
        return build_snapshot(root, "synth", name, self.store, created_at="2026-01-01T00:00:00Z")

    def pair(self, before_files, after_files, registry):
        before = self.snapshot("16", before_files)
        after = self.snapshot("17", after_files)
        return d.extract_pair(before, after, None, registry, store=self.store, step="16-17", toolkit=TOOLKIT)


class XmlViews(XmlCase):
    def test_view_arch_diff_golden(self):
        result = self.pair(synth._TREE_16, synth._TREE_17, xml_views.EXTRACTORS)
        drafts = [c for c in result.drafts if c["domain"] == "xml_view"]
        self.assertEqual([(c["class"], c["subject_key"], c["kind"]) for c in drafts],
                         [("BEHAVIOUR_CHANGED", "view_sale_demo_form", "view")])
        self.assertEqual(drafts[0]["detail"]["basis"], "body_digest")
        self.assertEqual(drafts[0]["locations"][0]["path"], "addons/sale_demo/views/sale_views.xml")

    def test_view_model_change_is_signature(self):
        before = {"views/views.xml": synth._VIEW_16}
        after = {"views/views.xml": synth._VIEW_16.replace('<field name="model">sale.demo.order',
                                                       '<field name="model">sale.demo.other')}
        result = self.pair(before, after, xml_views.EXTRACTORS)
        self.assertEqual([c["class"] for c in result.drafts], ["SIGNATURE_CHANGED"])

    def test_malformed_xml_is_failed(self):
        before = {"views/views.xml": synth._VIEW_16}
        after = {"views/views.xml": "<odoo><record id='x'"}
        result = self.pair(before, after, xml_views.EXTRACTORS)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))

    def test_unknown_record_model_is_unsupported_not_dropped(self):
        before = {"views/views.xml": synth._VIEW_16}
        after = {"views/views.xml": synth._VIEW_16.replace(
            "</odoo>", '<record id="act_x" model="ir.actions.act_window"/>\n</odoo>')}
        result = self.pair(before, after, xml_views.EXTRACTORS)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("UNSUPPORTED", "NO_PARSER"))
        self.assertEqual([c["class"] for c in result.drafts], ["UNKNOWN"])


class SecurityRows(XmlCase):
    def test_access_rows_golden(self):
        result = self.pair(synth._TREE_16, synth._TREE_17, security.EXTRACTORS)
        drafts = [c for c in result.drafts if c["domain"] == "security"]
        self.assertEqual([(c["class"], c["subject_key"], c["kind"]) for c in drafts],
                         [("ADDED", "access_sale_demo_order_manager", "access")])

    def test_access_permission_change_is_behaviour(self):
        before = {"security/ir.model.access.csv": synth._ACL_HEADER + synth._ACL_USER}
        after = {"security/ir.model.access.csv": synth._ACL_HEADER + synth._ACL_USER.replace(",1,0,0,0", ",1,1,0,0")}
        result = self.pair(before, after, security.EXTRACTORS)
        self.assertEqual([c["class"] for c in result.drafts], ["BEHAVIOUR_CHANGED"])

    def test_record_rules_golden(self):
        result = self.pair({"security/rules.xml": RULES_16}, {"security/rules.xml": RULES_17}, security.EXTRACTORS)
        changes = {(c["class"], c["subject_key"], c["kind"]) for c in result.drafts}
        self.assertEqual(changes, {
            ("BEHAVIOUR_CHANGED", "rule_sale_demo_order_company", "rule"),
            ("ADDED", "group_sale_demo_manager", "group"),
        })

    def test_malformed_csv_row_is_failed(self):
        before = {"security/ir.model.access.csv": synth._ACL_HEADER + synth._ACL_USER}
        after = {"security/ir.model.access.csv": synth._ACL_HEADER + "broken,row\n"}
        result = self.pair(before, after, security.EXTRACTORS)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))


if __name__ == "__main__":
    unittest.main()
