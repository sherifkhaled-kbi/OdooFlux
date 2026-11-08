"""TST-008-003 (REQ-VAL-006, REQ-BIZ-003, FR-009): a static-only run never reports a runtime-verified status and
lists L4 and L5 under verification_scope.layers_unavailable with reasons."""

import json
import unittest

from ..helpers import new_tmp, run_cli_main


class StaticOnlyTests(unittest.TestCase):
    def test_static_run_lists_l4_and_l5_as_unavailable_with_reasons(self):
        root = new_tmp()
        module = root / "kbi_static"
        module.mkdir()
        (module / "__manifest__.py").write_text("{'name': 'kbi_static', 'version': '18.0.1.0.0', 'depends': ['base']}\n",
                                                encoding="utf-8")
        (module / "models.py").write_text("x = 1\n", encoding="utf-8")
        report = root / "r.json"
        code, _ = run_cli_main(["--module", module, "--from-version", "18", "--to-version", "19", "--no-color",
                                "--report-format", "json", "--report", report, "--state-dir", root / "state"])
        self.assertEqual(code, 0)
        data = json.loads(report.read_text(encoding="utf-8"))
        scope = data["verification_scope"]
        self.assertEqual(scope["layers_unavailable"], [4, 5])
        for key in ("L4", "L5"):
            self.assertTrue(scope["reasons"][key], key)
        self.assertTrue(scope["limits"])
        module_result = data["modules"][0]
        self.assertIn(module_result["status"], ("STATIC_VALIDATED", "NEEDS_REVIEW"))
        self.assertNotIn(module_result["status"], ("INSTALL_VERIFIED", "VERIFIED_SUCCESS"))
        self.assertEqual(module_result["layers"]["L4"]["outcome"], "SKIPPED")
        self.assertEqual(module_result["layers"]["L3"]["outcome"], "PASS")


if __name__ == "__main__":
    unittest.main()
