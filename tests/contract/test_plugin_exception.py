"""TST-003-026 (REQ-ARC-002): a raising rule becomes RULE_ERROR; the run continues; status NEEDS_REVIEW."""

import json
import unittest

from ..integration.helpers import new_tmp, run_cli_main

SPEC = "contract.samples.raising_plugins:PLUGIN"


MANIFEST = "{'name': 'clean', 'version': '14.0.1.0.0', 'depends': ['base'], 'license': 'LGPL-3'}\n"


def _run(plugin=True, manifest=True):
    """Run the CLI on a legacy-clean module. Without a manifest L3 is UNAVAILABLE (a genuine BLOCKED cause)."""
    root = new_tmp()
    module = root / "clean"
    module.mkdir()
    (module / "models.py").write_text("x = 1\n", encoding="utf-8")
    if manifest:
        (module / "__manifest__.py").write_text(MANIFEST, encoding="utf-8")
    out = root / "r.json"
    args = ["--module", module, "--from-version", "14", "--no-color",
            "--report-format", "json", "--report", out, "--state-dir", root / "s"]
    if plugin:
        args += ["--plugin", SPEC]
    run_cli_main(args)
    return json.loads(out.read_text(encoding="utf-8"))


class PluginExceptionTests(unittest.TestCase):
    def test_exception_with_blocking_condition_stays_blocked(self):
        module_result = _run(manifest=False)["modules"][0]
        self.assertIn("RULE_ERROR", [f["rule_id"] for f in module_result["findings"]])
        self.assertEqual(module_result["status"], "BLOCKED")

    def test_no_exception_is_not_capped_by_rule_error(self):
        module_result = _run(plugin=False)["modules"][0]
        self.assertNotIn("RULE_ERROR", [f["rule_id"] for f in module_result["findings"]])
        self.assertNotIn("open_review_findings", module_result["status_reasons"])

    def test_rule_error_is_reported_and_module_capped(self):
        data = _run()
        module_result = data["modules"][0]
        self.assertIn("RULE_ERROR", [f["rule_id"] for f in module_result["findings"]])
        self.assertEqual(module_result["status"], "NEEDS_REVIEW")
        self.assertIn("open_review_findings", module_result["status_reasons"])
        self.assertEqual(data["run"]["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
