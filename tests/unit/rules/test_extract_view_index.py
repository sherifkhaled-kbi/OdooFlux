"""TST-006-0xx (FR-021): tools/extract_view_index.py on a small synthetic source tree, offline and deterministic."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.view_index import ViewIndex

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "extract_view_index.py"
spec = importlib.util.spec_from_file_location("extract_view_index", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

SHA = "a" * 40
FILES = {
    "addons/payment/__manifest__.py": "{'name': 'P', 'data': ['views/pv.xml', 'data/d.xml', 'views/missing.xml']}\n",
    "addons/payment/views/pv.xml": """<odoo>
  <record id="provider_form" model="ir.ui.view">
    <field name="model">payment.provider</field>
    <field name="arch" type="xml"><form><field name="state"/><div id="wrap"><button name="act"/></div></form></field>
  </record>
  <record id="provider_extra" model="ir.ui.view">
    <field name="inherit_id" ref="provider_form"/>
    <field name="arch" type="xml"><xpath expr="//field[@name='state']" position="after">
      <field name="added"/><attribute name="invisible">1</attribute></xpath></field>
  </record>
</odoo>
""",
    "addons/payment/data/d.xml": """<odoo><data noupdate="1">
  <template id="checkout" inherit_id="web.layout"><div id="pay"/></template>
</data></odoo>""",
    "addons/payment/views/unlisted.xml": '<odoo><record id="ghost" model="ir.ui.view"><field name="arch"/></record></odoo>',
    "addons/payment/tests/t.xml": '<odoo><record id="in_tests" model="ir.ui.view"><field name="arch"/></record></odoo>',
    "addons/payment/static/src/x.xml": '<odoo><template id="in_static"><b/></template></odoo>',
    "addons/web/__manifest__.py": "{'name': 'W', 'data': ['views/l.xml']}\n",
    "addons/web/views/l.xml": '<odoo><template id="layout"><html id="h"/></template>'
                              '<record id="r" model="res.partner"><field name="name">x</field></record></odoo>',
    "addons/broken/__manifest__.py": "{'name': 'B', 'data': ['b.xml']}\n",
    "addons/broken/b.xml": "<odoo><record",
    "odoo/addons/base/__manifest__.py": "{'name': 'base', 'data': ['v.xml']}\n",
    "odoo/addons/base/v.xml": '<odoo><record id="view_partner_form" model="ir.ui.view">'
                              '<field name="inherit_id" eval="ref(\'web.layout\')"/><field name="arch" type="xml">'
                              '<form><field name="phone"/></form></field></record></odoo>',
}


def write(root: Path, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class ExtractViewIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.src = Path(cls._tmp.name) / "src"
        write(cls.src, FILES)
        cls.index = tool.build_index(tool.DirSource(cls.src), "16.0", "odoo/odoo", SHA, "EV-540")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_views_come_from_manifest_data_files_only(self):
        self.assertEqual(sorted(self.index["views"]["payment"]), ["checkout", "provider_extra", "provider_form"])
        self.assertNotIn("ghost", self.index["views"]["payment"])
        self.assertNotIn("in_tests", self.index["views"]["payment"])
        self.assertNotIn("in_static", self.index["views"]["payment"])

    def test_non_view_records_are_not_indexed(self):
        self.assertEqual(self.index["views"]["web"], {"layout": ""})

    def test_ids_defined_in_data_files_count(self):
        self.assertEqual(self.index["views"]["payment"]["checkout"], "web.layout")

    def test_inheritance_chain_maps_to_root_and_eval_ref_is_read(self):
        self.assertEqual(self.index["views"]["payment"]["provider_extra"], "payment.provider_form")
        self.assertEqual(self.index["views"]["base"]["view_partner_form"], "web.layout")

    def test_anchors_are_unioned_per_tree_and_exclude_attribute_edits(self):
        self.assertEqual(self.index["anchors"]["payment.provider_form"], ["act", "added", "state", "wrap"])
        self.assertEqual(self.index["anchors"]["web.layout"], ["h", "pay", "phone"])

    def test_malformed_file_is_recorded_not_fatal(self):
        self.assertTrue(any("broken/b.xml" in p for p in self.index["problems"]))

    def test_provenance(self):
        for key, value in (("version", "16.0"), ("revision", SHA), ("repository", "odoo/odoo"),
                           ("evidence", "EV-540"), ("format", 1)):
            self.assertEqual(self.index[key], value)
        self.assertEqual(self.index["counts"]["views"], 5)

    def test_output_is_deterministic_and_loadable(self):
        again = tool.build_index(tool.DirSource(self.src), "16.0", "odoo/odoo", SHA, "EV-540")
        self.assertEqual(tool.render(self.index), tool.render(again))
        loaded = ViewIndex.from_dict(json.loads(tool.render(self.index)))
        self.assertTrue(loaded.has_view("payment.provider_form"))
        self.assertIn("state", loaded.anchors_for("payment.provider_extra"))

    def test_cli_extract_is_reproducible_across_runs(self):
        outs = []
        for name in ("a.json", "b.json"):
            out = Path(self._tmp.name) / name
            subprocess.run([sys.executable, "-I", str(TOOL), "extract", "--cache", str(self.src), "--sha", SHA,
                            "--version", "16.0", "--evidence-id", "EV-540", "--index-out", str(out)],
                           check=True, capture_output=True)
            outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])

    def test_unreadable_manifest_falls_back_to_all_xml_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp), {"addons/m/__manifest__.py": "{'data': [x]}\n",
                              "addons/m/a.xml": '<odoo><template id="t"><b/></template></odoo>'})
            index = tool.build_index(tool.DirSource(Path(tmp)), "16.0", "odoo/odoo", SHA, "EV-540")
        self.assertIn("t", index["views"]["m"])
        self.assertTrue(any("manifest is not a literal dict" in p for p in index["problems"]))


if __name__ == "__main__":
    unittest.main()
