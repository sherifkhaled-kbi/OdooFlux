"""P0 User Story 2: fix mode never writes a broken file (FR-002, FR-015, F-VAL-1)."""

import ast
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import odooflux.ai.providers.legacy_anthropic as legacy_ai
import odooflux.rules.shared.legacy_adapter as adapter
from odooflux.rules.shared.legacy_rules import apply_manifest_fixes

from tests._support.p0 import FIXTURE, make_addons, read_runlog, run_main, tree_digest


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addons = make_addons(self.tmp)
        self.module = self.addons / "kbi_demo"
        self.state = self.tmp / "state"

    def tearDown(self):
        self._tmp.cleanup()

    def _fix(self, extra=()):
        return run_main(["--module", self.module, "--from-version", "14", "--fix",
                         "--no-color", "--state-dir", self.state, *extra])


class ValidationGateTests(_Case):
    def _assert_rejected_module(self, code, out, before, category_hint):
        self.assertEqual(tree_digest(self.module), before, "a rejected module must not be written")
        self.assertEqual(code, 3, out)
        self.assertIn("Fix Rejected", out)
        self.assertIn(category_hint, out)
        events = [e["event"] for e in read_runlog(self.state)]
        self.assertIn("edit_rejected", events)
        self.assertNotIn("file_written", events)

    def test_invalid_python_not_written(self):
        """F-VAL-1 / FR-002: a Python fixer output that does not parse is not written."""
        before = tree_digest(self.module)
        with mock.patch.object(adapter, "apply_python_fixes",
                               side_effect=lambda content, *a, **k: "def broken(:\n"):
            code, out = self._fix()
        self._assert_rejected_module(code, out, before, "SyntaxError")

    def test_invalid_xml_not_written(self):
        """F-VAL-1 / FR-002: an XML fixer output that is not well-formed is not written."""
        before = tree_digest(self.module)
        with mock.patch.object(adapter, "apply_xml_fixes",
                               side_effect=lambda content, *a, **k: "<odoo><form></odoo>"):
            code, out = self._fix()
        self._assert_rejected_module(code, out, before, "XML")

    def test_invalid_manifest_not_written(self):
        """F-VAL-1 / FR-002: a manifest that is not a literal dict is not written."""
        before = tree_digest(self.module)
        with mock.patch.object(adapter, "apply_manifest_fixes",
                               side_effect=lambda content, *a, **k: "{'version': 1 +}\n"):
            code, out = self._fix()
        self._assert_rejected_module(code, out, before, "Manifest")


class AiOutputGateTests(_Case):
    AI_JSON_BROKEN = json.dumps({"files": {"kbi_demo/demo.py": "def broken(:\n"},
                                 "skipped": [], "notes": ""})

    def test_ai_invalid_output_not_written(self):
        """TST-001-010 (REQ-SAF-002): AI output that fails the gate leaves the module as the
        regex-only run left it, and no draft is written into the module."""
        ref_dir = self.tmp / "ref"
        ref_addons = make_addons(ref_dir)
        run_main(["--module", ref_addons / "kbi_demo", "--from-version", "14", "--fix",
                  "--no-color", "--state-dir", self.tmp / "ref_state"])
        expected = tree_digest(ref_addons / "kbi_demo")

        with mock.patch.object(legacy_ai, "_call_claude_api", return_value=self.AI_JSON_BROKEN):
            code, out = self._fix(["--ai-fix", "--api-key", "test-key"])
        self.assertEqual(tree_digest(self.module), expected)
        self.assertEqual(code, 3, out)
        self.assertFalse(list(self.module.rglob("*.ai_draft")))


class FixtureOutputValidityTests(_Case):
    def test_fixture_fix_outputs_valid(self):
        """TST-001-016 / SC-001 / TST-001-015: every written file is valid for its type on the
        Appendix A fixture, and JS files are byte-identical after --fix."""
        code, out = self._fix()
        self.assertIn(code, (0, 1), out)
        for py in self.module.rglob("*.py"):
            compile(py.read_text(encoding="utf-8"), str(py), "exec")
        for xml in self.module.rglob("*.xml"):
            ET.parse(xml)
        manifest = self.module / "__manifest__.py"
        self.assertTrue(manifest.exists())
        ast.literal_eval(manifest.read_text(encoding="utf-8"))
        self.assertFalse((self.module / "__openerp__.py").exists())
        js_rel = Path("static/src/js/demo.js")
        self.assertEqual((self.module / js_rel).read_bytes(), (FIXTURE / js_rel).read_bytes())


if __name__ == "__main__":
    unittest.main()
