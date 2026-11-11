"""Experimental attrs/states fixes through the real CLI (roadmap T1 and T2; AC-1 to AC-5).

Every run works on a throwaway copy of a small 16.0 module and uses the built-in knowledge (an empty
ODOOFLUX_KB_HOME), so the results do not depend on an installed knowledge release.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .helpers import REPO, new_tmp

SOURCE = """<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="v_form" model="ir.ui.view">
        <field name="name">v.form</field>
        <field name="model">kbi.exp</field>
        <field name="arch" type="xml">
            <form>
                <field name="name" attrs="{'invisible': [('state', '=', 'done')]}"/>
                <field name="amount" attrs="{'readonly': [('amount', '=', 0)]}"/>
                <button name="go" states="draft,sent" type="object" string="Go"/>
            </form>
        </field>
    </record>
</odoo>
"""
MANIFEST = '{\n    "name": "KBI Experimental",\n    "version": "16.0.1.0.0",\n    "depends": ["base"],\n' \
           '    "data": ["views/v.xml"],\n}\n'
VIEW = "views/v.xml"
ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"


def _env():
    kb = new_tmp() / "empty-kb"  # an empty release home means the built-in knowledge
    kb.mkdir(parents=True, exist_ok=True)
    return {**os.environ, "PYTHONPATH": str(REPO / "src"), "ODOOFLUX_KB_HOME": str(kb),
            "XDG_CACHE_HOME": str(new_tmp() / "cache")}


def _cli(args):
    proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), *map(str, args)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600, env=_env())
    return proc.returncode, proc.stdout


def _copy(root: Path) -> Path:
    """A fresh copy of the source module under ``root``; the state directory sits inside the same root."""
    module = root / "addons" / "kbi_exp"
    (module / "views").mkdir(parents=True)
    (module / "__manifest__.py").write_text(MANIFEST, encoding="utf-8")
    (module / "__init__.py").write_text("", encoding="utf-8")
    (module / VIEW).write_text(SOURCE, encoding="utf-8")
    return module


def _migrate(root: Path, module: Path, *extra):
    report = root / "report.json"
    code, out = _cli(["migrate", "--addons-path", root / "addons", "--from-version", "16", "--to-version", "17",
                      "--report", report, "--report-format", "json", "--state-dir", root / "state", *extra])
    data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    return code, out, data


def _normalised(data: dict, root: Path) -> str:
    text = json.dumps(data, indent=2, sort_keys=True)
    return text.replace(data["run"]["run_id"], "<RUN>").replace(str(root), "<ROOT>")


def _keys_anywhere(obj, key) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_keys_anywhere(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(_keys_anywhere(v, key) for v in obj)
    return False


class FlagValidationTests(unittest.TestCase):
    def test_experimental_flag_without_fix_is_rejected_with_a_clear_message(self):
        root = new_tmp()
        module = _copy(root)
        code, out, data = _migrate(root, module, "--experimental-fixes")
        self.assertNotEqual(code, 0)
        self.assertIn("--experimental-fixes requires --fix", out)
        self.assertIsNone(data)
        self.assertEqual((module / VIEW).read_text(encoding="utf-8"), SOURCE)

    def test_experimental_flag_with_dry_run_only_is_accepted_and_writes_nothing(self):
        root = new_tmp()
        module = _copy(root)
        code, out, data = _migrate(root, module, "--fix", "--dry-run", "--experimental-fixes")
        self.assertNotIn("requires --fix", out)
        self.assertEqual((module / VIEW).read_text(encoding="utf-8"), SOURCE)
        self.assertIsNotNone(data)


class PlainFixTests(unittest.TestCase):
    def test_plain_fix_runs_are_deterministic_and_add_no_experimental_keys(self):
        first, second = new_tmp(), new_tmp()
        module_a, module_b = _copy(first), _copy(second)
        _ca, _oa, data_a = _migrate(first, module_a, "--fix")
        _cb, _ob, data_b = _migrate(second, module_b, "--fix")
        self.assertEqual(_normalised(data_a, first), _normalised(data_b, second))
        self.assertTrue(_keys_anywhere(data_a, "fix_class"))  # AD-01: plain --fix runs the registry fixers and says so

    def test_plain_fix_converts_the_supported_attrs_attribute(self):
        root = new_tmp()
        module = _copy(root)
        _migrate(root, module, "--fix")
        text = (module / VIEW).read_text(encoding="utf-8")
        self.assertIn("""invisible="state == 'done'\"""", text)  # AD-01: converted without --experimental-fixes
        self.assertIn("""attrs="{'readonly': [('amount', '=', 0)]}\"""", text)  # falsy literal: refused, left alone


class StatesSingleEditTests(unittest.TestCase):
    """The legacy layer no longer rewrites states= without a verified state field (D2), so the experimental fixer is
    the only editor of that element: one conversion, and a second pass changes nothing."""

    def test_states_element_is_converted_once_and_a_second_pass_is_a_no_op(self):
        root = new_tmp()
        module = _copy(root)
        _migrate(root, module, "--fix", "--experimental-fixes")
        first = (module / VIEW).read_text(encoding="utf-8")
        self.assertEqual(first.count('name="go"'), 1)
        self.assertEqual(first.count("state not in ['draft','sent']"), 1)
        _migrate(root, module, "--fix", "--experimental-fixes")
        self.assertEqual((module / VIEW).read_text(encoding="utf-8"), first)


class FlagOnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = new_tmp()
        cls.module = _copy(cls.root)
        cls.code, cls.out, cls.data = _migrate(cls.root, cls.module, "--fix", "--experimental-fixes")
        cls.text = (cls.module / VIEW).read_text(encoding="utf-8")

    def test_supported_attrs_element_is_converted_without_attrs(self):
        self.assertIn("""<field name="name" invisible="state == 'done'"/>""", self.text)
        self.assertNotIn("""<field name="name" attrs=""", self.text)

    def test_falsy_literal_element_is_refused_and_left_untouched(self):
        self.assertIn("""<field name="amount" attrs="{'readonly': [('amount', '=', 0)]}"/>""", self.text)

    def test_converted_output_has_no_attrs_or_states_on_the_converted_element(self):
        self.assertNotIn("""name="go" states=""", self.text)
        self.assertIn("""<button name="go" type="object" string="Go" invisible=""", self.text)

    def test_summary_reports_rules_applied_and_refused_with_reasons(self):
        block = self.data["summary"]["experimental"]
        self.assertEqual(block["rules_enabled"], sorted([ATTRS, STATES]))
        applied = [a for a in block["applied"] if a["rule_id"] == ATTRS]
        self.assertEqual(len(applied), 1)
        self.assertIn("attrs=", applied[0]["before"])
        self.assertIn("invisible=", applied[0]["after"])
        refused = [r for r in block["refused"] if r["rule_id"] == ATTRS]
        self.assertEqual([(r["line"], r["reason"]) for r in refused], [(9, "falsy-literal")])

    def test_converted_finding_carries_fix_class_experimental_and_is_fixed(self):
        findings = [f for m in self.data["modules"] for f in m["findings"] if f["rule_id"] == ATTRS]
        by_line = {f["line"]: f for f in findings}
        self.assertEqual(by_line[8]["fix_class"], "experimental")
        self.assertEqual(by_line[8]["status"], "FIXED")
        self.assertEqual(by_line[9]["fix_class"], "experimental")
        self.assertEqual(by_line[9]["status"], "NEEDS_REVIEW")  # refused: for the developer, not auto-fixable
        self.assertFalse(by_line[9]["auto_fixable"])

    def test_edits_are_classified_by_fix_class(self):
        edits = [e for m in self.data["modules"] for e in m["edits"]]
        self.assertTrue(edits)
        self.assertTrue(all("fix_class" in e for e in edits))
        self.assertIn("experimental", {e["fix_class"] for e in edits})
        manifest = [e for e in edits if e["path"].endswith("__manifest__.py")]
        self.assertEqual([e["fix_class"] for e in manifest], ["legacy"])

    def test_second_run_applies_no_edits_and_leaves_the_tree_byte_identical(self):
        before = self.text
        _code, _out, data = _migrate(self.root, self.module, "--fix", "--experimental-fixes")
        self.assertEqual((self.module / VIEW).read_text(encoding="utf-8"), before)
        self.assertEqual(data["summary"]["edits"]["applied"], 0)
        applied = [a for a in data["summary"]["experimental"]["applied"] if a["rule_id"] == ATTRS]
        self.assertEqual(applied, [])


class DryRunTests(unittest.TestCase):
    def test_dry_run_plans_the_experimental_edit_and_writes_nothing(self):
        root = new_tmp()
        module = _copy(root)
        _code, _out, data = _migrate(root, module, "--fix", "--dry-run", "--experimental-fixes")
        self.assertEqual((module / VIEW).read_text(encoding="utf-8"), SOURCE)
        applied = [a for a in data["summary"]["experimental"]["applied"] if a["rule_id"] == ATTRS]
        self.assertEqual(len(applied), 1)


class EndToEndShapeTests(unittest.TestCase):
    def test_shipped_fixture_is_refused_for_its_zero_literal(self):
        root = new_tmp()
        module = root / "addons" / "kbi_demo"
        (module / "views").mkdir(parents=True)
        (module / "__manifest__.py").write_text(MANIFEST, encoding="utf-8")
        (module / "__init__.py").write_text("", encoding="utf-8")
        (module / VIEW).write_text(
            '<?xml version="1.0"?>\n<odoo><record id="x" model="ir.ui.view"><field name="arch" type="xml">'
            "<form><field name=\"name\" attrs=\"{'invisible': [('amount', '=', 0)]}\"/></form>"
            "</field></record></odoo>\n", encoding="utf-8")
        _code, _out, data = _migrate(root, module, "--fix", "--experimental-fixes")
        refused = data["summary"]["experimental"]["refused"]
        self.assertEqual([r["reason"] for r in refused], ["falsy-literal"])
        self.assertIn("attrs=", (module / VIEW).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
