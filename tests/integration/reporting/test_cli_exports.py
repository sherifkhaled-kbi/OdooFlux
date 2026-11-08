"""Quickstart scenarios 2, 4, 5 (REQ-REP-001..005): the CLI writes JSON/SARIF/HTML/diff outside the module, honours
NO_COLOR and --ui, and exits per the table."""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.unit.reporting import _setup  # noqa: F401
from tests.unit.reporting.schema_validator import Validator, load, sarif_validator
from tests.integration.helpers import REPO, make_module, new_tmp, tree
from tests.integration.reporting.cli import run_cli_main

ANSI = "\x1b["


class CliExportTests(unittest.TestCase):
    def setUp(self):
        self.root = new_tmp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.module = make_module(self.root / "addons", "kbi_demo")
        self.out = self.root / "out"
        self.out.mkdir()

    def _run(self, *extra, module=None):
        return run_cli_main(["--module", module or self.module, "--from-version", "14", "--state-dir", self.root / "s",
                             *extra])

    def test_all_exports_written_and_valid(self):
        from odooflux.reporting.model.schema_check import SCHEMA_FILE
        before = tree(self.root / "addons")
        code, out = self._run("--report", self.out / "r.json", "--report-format", "json", "--sarif", self.out / "r.sarif",
                              "--html", self.out / "r.html", "--no-color")
        self.assertEqual(code, 1, out)  # legacy criticals remain in an analyze run
        self.assertEqual(tree(self.root / "addons"), before)
        report = json.loads((self.out / "r.json").read_text(encoding="utf-8"))
        self.assertEqual(Validator(load(SCHEMA_FILE)).errors(report), [])
        sarif = json.loads((self.out / "r.sarif").read_text(encoding="utf-8"))
        self.assertEqual(sarif_validator().errors(sarif), [])
        self.assertEqual(sarif["runs"][0]["invocations"][0]["exitCode"], code)
        html = (self.out / "r.html").read_text(encoding="utf-8")
        self.assertIn('id="scope"', html)
        self.assertNotIn("<script", html)
        # counts agree across the three files
        n_open = sum(report["summary"]["open_findings"].values())
        levels = [r for r in sarif["runs"][0]["results"] if r["properties"]["status"] in ("OPEN", "NEEDS_REVIEW")]
        self.assertEqual(len(levels), n_open)
        self.assertIn(f'data-metric="open">{n_open}<', html)

    def test_legacy_json_alias_prints_deprecation(self):
        code, out = self._run("--report", self.out / "l.json", "--report-format", "legacy-json", "--no-color")
        self.assertIn("deprecated", out)
        data = json.loads((self.out / "l.json").read_text(encoding="utf-8"))
        self.assertIn("issues", data)

    def test_no_color_env_and_flag_give_no_ansi(self):
        env = dict(os.environ, NO_COLOR="1")
        proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), "--module", str(self.module),
                               "--from-version", "14", "--state-dir", str(self.root / "s"), "--ui", "ansi"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, timeout=300)
        self.assertNotIn(ANSI, proc.stdout)
        self.assertIn("MODULE RESULTS", proc.stdout)

    def test_ui_ansi_prints_model_report_with_scope_and_totals(self):
        code, out = self._run("--ui", "ansi", "--no-color", "--max-findings-per-file", "2")
        self.assertIn("VERIFICATION SCOPE", out)
        self.assertIn("TOTALS modules=1", out)
        self.assertNotIn(ANSI, out)

    def test_ui_rich_falls_back_without_rich(self):
        code, out = self._run("--ui", "rich", "--no-color")
        self.assertIn("MODULE RESULTS", out)

    def test_default_output_unchanged_without_ui(self):
        code, out = self._run("--no-color")
        self.assertNotIn("VERIFICATION SCOPE", out)

    def test_fail_on_matrix_through_cli(self):
        code, _ = self._run("--fail-on", "none", "--no-color")
        self.assertEqual(code, 0)
        code, _ = self._run("--fail-on", "critical", "--no-color")
        self.assertEqual(code, 1)
        code, _ = self._run("--fail-on", "none", "--fail-on-status", "FAILED", "--no-color")
        self.assertEqual(code, 1)

    def test_bad_fail_on_status_is_usage_error_2_before_processing(self):
        code, out = self._run("--fail-on-status", "BROKEN", "--no-color")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.root / "s").exists())

    def test_diff_export_in_write_mode_applies_with_patch(self):
        if shutil.which("patch") is None:
            self.skipTest("patch(1) not available")
        pristine = self.root / "pristine"
        make_module(pristine, "kbi_demo")
        code, out = self._run("--fix", "--diff", self.out / "c.patch", "--no-color", "--fail-on", "none")
        self.assertIn(code, (0, 3, 4), out)
        self.assertTrue((self.out / "c.patch").exists())
        index = json.loads((self.out / "c.patch.index.json").read_text(encoding="utf-8"))
        self.assertTrue(index["files"])
        proc = subprocess.run(["patch", "-p1", "-d", str(pristine), "-i", str(self.out / "c.patch"),
                               "--no-backup-if-mismatch"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(tree(pristine), tree(self.root / "addons"))

    def test_diff_with_no_backup_in_write_mode_is_refused(self):
        code, out = self._run("--fix", "--no-backup", "--diff", self.out / "c.patch", "--no-color")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.out / "c.patch").exists())

    def test_exit_codes_option_default_is_legacy_compatible_and_v1_is_opt_in(self):
        """D-10: for this release the default keeps the characterised mapping (a module without a manifest cannot run L3,
        which the v1 table reports as BLOCKED = 4)."""
        bare = self.root / "bare"
        bare.mkdir()
        (bare / "models.py").write_text("from odoo import fields\nname = fields.Char(size=64)\n", encoding="utf-8")
        code, out = self._run("--fail-on", "critical", "--no-color", module=bare)
        self.assertEqual(code, 0, out)
        code, out = self._run("--fail-on", "critical", "--exit-codes", "v1", "--no-color", module=bare)
        self.assertEqual(code, 4, out)
        code, out = self._run("--exit-codes", "legacy", "--fail-on", "warning", "--no-color", module=bare)
        self.assertEqual(code, 1, out)

    def test_exit_code_in_sarif_matches_process(self):
        code, _ = self._run("--sarif", self.out / "z.sarif", "--fail-on", "none", "--no-color")
        sarif = json.loads((self.out / "z.sarif").read_text(encoding="utf-8"))
        self.assertEqual(sarif["runs"][0]["invocations"][0]["exitCode"], code)


if __name__ == "__main__":
    unittest.main()
