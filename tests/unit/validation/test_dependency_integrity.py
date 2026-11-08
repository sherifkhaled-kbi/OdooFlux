"""TST-008-011 (REQ-VAL-003, REQ-DEP-003, FR-003): L3 dependency integrity. Each broken reference kind
yields exactly one finding; a clean module yields none. Fixtures are built in temporary directories."""

import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.validation.dependency.integrity import check_integrity, load_core_modules

from .._setup import SRC  # noqa: F401

CORE = {"base", "web"}
DATA_FILES = ["security/groups.xml", "security/ir.model.access.csv", "views/v.xml"]


def write_manifest(module: Path, depends, data):
    text = repr({"name": "Test", "version": "19.0.1.0.0", "depends": list(depends),
                 "data": list(data), "installable": True})
    (module / "__manifest__.py").write_text(text, encoding="utf-8")
GROUPS = """<odoo>
  <record id="group_thing" model="res.groups"><field name="name">Thing</field></record>
</odoo>
"""
ACCESS = ("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
          "access_kbi_clean_thing,access thing,model_kbi_clean_thing,kbi_clean.group_thing,1,0,0,0\n")
VIEWS = """<odoo>
  <record id="view_thing_form" model="ir.ui.view">
    <field name="name">thing form</field>
    <field name="model">kbi_clean.thing</field>
    <field name="arch" type="xml"><form><field name="name"/></form></field>
  </record>
  <menuitem id="menu_thing" name="Thing" groups="kbi_clean.group_thing"/>
</odoo>
"""
MODELS = """from odoo import fields, models


class Thing(models.Model):
    _name = 'kbi_clean.thing'

    name = fields.Char()
"""

# one defect per kind: file -> (path, text); the defect is appended to the clean module
DEFECTS = {
    "missing_module": {},
    "dangling_model": {"tools.py": "def lookup(env):\n    return env['kbi_clean.phantom'].search([])\n"},
    "dangling_field": {"views/v.xml": VIEWS.replace(
        "<field name=\"name\"/></form>", "<field name=\"ghost_field\"/></form>")},
    "dangling_xml_id": {"views/child.xml": "<odoo>\n  <record id=\"view_child\" model=\"ir.ui.view\">\n"
                                           "    <field name=\"inherit_id\" ref=\"kbi_clean.view_missing\"/>\n"
                                           "  </record>\n</odoo>\n"},
    "missing_group": {"views/v2.xml": "<odoo>\n  <menuitem id=\"menu_x\" name=\"X\" "
                                      "groups=\"kbi_clean.group_missing\"/>\n</odoo>\n"},
    "missing_python_package": {"ext.py": "import kbi_fake_pkg\n"},
}
RULE_IDS = {
    "missing_module": "integrity.missing_module",
    "dangling_model": "integrity.dangling_model",
    "dangling_field": "integrity.dangling_field",
    "dangling_xml_id": "integrity.dangling_xml_id",
    "missing_group": "integrity.missing_group",
    "missing_python_package": "integrity.missing_python_package",
}


def write_clean_module(root: Path, name="kbi_clean"):
    module = root / name
    (module / "security").mkdir(parents=True)
    (module / "views").mkdir()
    write_manifest(module, ["base"], DATA_FILES)
    (module / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (module / "models.py").write_text(MODELS, encoding="utf-8")
    (module / "security" / "groups.xml").write_text(GROUPS, encoding="utf-8")
    (module / "security" / "ir.model.access.csv").write_text(ACCESS, encoding="utf-8")
    (module / "views" / "v.xml").write_text(VIEWS, encoding="utf-8")
    return module


class DependencyIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="odooflux-l3-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_check(self, module):
        return check_integrity([module], target_version="19.0", core_modules=CORE)

    def test_clean_module_has_no_findings_and_passes(self):
        module = write_clean_module(self.tmp)
        findings, result = self.run_check(module)
        self.assertEqual([f.rule_id for f in findings], [])
        self.assertEqual(result.layer, 3)
        self.assertEqual(result.outcome, "PASS")

    def test_each_broken_reference_kind_yields_exactly_one_finding(self):
        for kind, extra_files in DEFECTS.items():
            with self.subTest(kind=kind):
                root = Path(tempfile.mkdtemp(prefix=f"odooflux-{kind}-", dir=self.tmp))
                module = write_clean_module(root)
                depends = ["base", "kbi_nowhere"] if kind == "missing_module" else ["base"]
                data = list(DATA_FILES)
                for rel, text in extra_files.items():
                    target = module / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(text, encoding="utf-8")
                    if rel.endswith(".xml") and rel not in data:
                        data.append(rel)
                write_manifest(module, depends, data)
                findings, result = self.run_check(module)
                self.assertEqual([f.rule_id for f in findings], [RULE_IDS[kind]])
                self.assertEqual(result.outcome, "FAIL")
                self.assertEqual(result.layer, 3)

    def test_undecided_references_are_named_as_limits_not_failures(self):
        # No core module list for an unknown target: dependencies cannot be decided. L3 still ran, so it is PASS
        # with the undecided kind named in the reason (carried to the verification scope), never FAIL.
        module = write_clean_module(self.tmp)
        findings, result = check_integrity([module], target_version="99.0", core_modules=None)
        self.assertEqual(findings, [])
        self.assertEqual(result.outcome, "PASS")
        self.assertIn("undecided", result.reason)

    def test_enterprise_dependency_is_info_and_names_enterprise_while_unknown_stays_warning(self):
        # T019: a dependency on a listed Enterprise module is INFO (odoo/enterprise is not accessible, D-05) and
        # does not fail L3. An unknown dependency is still a WARNING and still fails L3, as before.
        module = write_clean_module(self.tmp)
        write_manifest(module, ["base", "sale_subscription"], DATA_FILES)
        findings, result = self.run_check(module)
        missing = [f for f in findings if f.rule_id == "integrity.missing_module"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].severity, "INFO")
        self.assertIn("Enterprise", missing[0].message)
        self.assertEqual(result.outcome, "PASS")
        write_manifest(module, ["base", "kbi_nowhere"], DATA_FILES)
        findings, result = self.run_check(module)
        missing = [f for f in findings if f.rule_id == "integrity.missing_module"]
        self.assertEqual([f.severity for f in missing], ["WARNING"])
        self.assertEqual(result.outcome, "FAIL")

    def test_core_list_for_target_version_is_loaded(self):
        modules = load_core_modules("19.0")
        self.assertIn("base", modules)
        self.assertIn("web", modules)
        self.assertIsNone(load_core_modules("99.0"))


if __name__ == "__main__":
    unittest.main()
