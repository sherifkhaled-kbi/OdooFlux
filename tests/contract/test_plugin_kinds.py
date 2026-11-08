"""TST-003-024 (REQ-ARC-002): one sample per registry kind loads with --plugin; effects are visible."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.builtins import build_context
from odooflux.cli.plugins import load_plugins

from ..integration.helpers import make_module, new_tmp, run_cli_main

SPEC = "contract.samples.sample_plugins:PLUGIN"


def _module_with_marker(root: Path) -> Path:
    module = root / "marked"
    module.mkdir()
    (module / "models.py").write_text("# SAMPLE_TODO\nx = 1\n", encoding="utf-8")
    return module


class PluginKindsTests(unittest.TestCase):
    def test_every_kind_registers(self):
        ctx = build_context()
        failures = load_plugins([SPEC], ctx.registries)
        self.assertEqual(failures, [])
        r = ctx.registries
        self.assertIn("sample.todo", r.rules)
        self.assertIn("sample.reject", r.validators)
        self.assertIn("sample", r.parsers)
        self.assertIn("sample-runtime", r.runtimes)
        self.assertIn("sample-ai", r.ai_providers)
        self.assertIn("sample-text", r.renderers)
        self.assertIn("20.0", r.versions)

    def test_rule_effect_appears_in_the_report(self):
        root = new_tmp()
        module = _module_with_marker(root)
        out = root / "r.json"
        code, _ = run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--plugin", SPEC,
                                "--report-format", "json", "--report", out, "--state-dir", root / "s"])
        rules = [f["rule_id"] for m in json.loads(out.read_text())["modules"] for f in m["findings"]]
        self.assertIn("SAMPLE_RULE", rules)

    def test_validator_effect_rejects_the_edit(self):
        root = new_tmp()
        module = root / "rejected"
        module.mkdir()
        (module / "models.py").write_text("x = 1  # REJECT_ME\n", encoding="utf-8")
        code, out = run_cli_main(["--module", module, "--from-version", "14", "--fix", "--no-color",
                                  "--plugin", SPEC, "--state-dir", root / "s"])
        self.assertEqual(code, 3, out)
        self.assertIn("sample validator rejects", out)

    def test_renderer_effect_writes_the_format(self):
        root = new_tmp()
        module = _module_with_marker(root)
        out = root / "sample.txt"
        run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--plugin", SPEC,
                      "--report-format", "sample-text", "--report", out, "--state-dir", root / "s"])
        self.assertEqual(out.read_text(encoding="utf-8"), "SAMPLE analyze\n")


if __name__ == "__main__":
    unittest.main()
