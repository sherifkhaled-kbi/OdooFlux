"""AF-2 / AD-06: a dry run reports planned edits, never applied ones, and never claims a rollback.

The sample module has a manifest version bump (a legacy fixer edit) and a <tree> view (a finding the fixers act on).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


class _Sample:
    def __init__(self, tmp: str):
        self.root = Path(tmp)
        module = self.root / "addons" / "mod"
        (module / "views").mkdir(parents=True)
        (module / "__manifest__.py").write_text('{"name": "m", "version": "16.0.1.0.0", "depends": ["base"]}\n',
                                                encoding="utf-8")
        (module / "__init__.py").write_text("\n", encoding="utf-8")
        (module / "views" / "v.xml").write_text(
            '<odoo>\n<record id="v" model="ir.ui.view"><field name="name">v</field>'
            '<field name="model">res.partner</field><field name="arch" type="xml">'
            '<tree><field name="name"/></tree></field></record>\n</odoo>\n', encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if k not in ("ODOOFLUX_KB_HOME", "PYTHONPATH")}
        self.env.update(PYTHONPATH=str(REPO / "src"), XDG_CACHE_HOME=str(self.root / "cache"))

    def migrate(self, *extra: str, fmt: str = "json") -> subprocess.CompletedProcess:
        report = self.root / f"report.{fmt}"
        return subprocess.run(
            [sys.executable, "-m", "odooflux", "migrate", "--addons-path", str(self.root / "addons"),
             "--from-version", "16", "--to-version", "17", "--state-dir", str(self.root / "state"),
             "--report", str(report), "--report-format", fmt, "--no-color", *extra],
            cwd=str(self.root), env=self.env, capture_output=True, text=True, timeout=180)

    def dry_run(self) -> tuple:
        proc = self.migrate("--fix", "--dry-run")
        return proc, json.loads((self.root / "report.json").read_text(encoding="utf-8"))


class DryRunRecovery(unittest.TestCase):
    def test_dry_run_is_not_reversible_and_prints_no_rollback_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, report = _Sample(tmp).dry_run()
            recovery = report["recovery"]
            self.assertIs(recovery["reversible"], False)
            self.assertIsNone(recovery["rollback_cmd"])
            self.assertTrue(recovery["run_log"])  # the run log of a dry run is still recorded

    def test_dry_run_human_output_has_no_rollback_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _Sample(tmp).migrate("--fix", "--dry-run", fmt="json")
            self.assertNotIn("odooflux rollback", proc.stdout)


class DryRunCountsPlannedNotApplied(unittest.TestCase):
    def test_summary_counts_planned_edits_and_applies_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, report = _Sample(tmp).dry_run()
            edits = report["summary"]["edits"]
            self.assertEqual(edits["applied"], 0)
            self.assertGreaterEqual(edits["planned"], 1)
            self.assertEqual(edits["planned"], sum(len(m["edits"]) for m in report["modules"]))

    def test_detected_issues_are_never_counted_as_fixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, report = _Sample(tmp).dry_run()
            self.assertEqual(report["summary"]["findings_by_status"]["fixed"], 0)
            self.assertEqual(report["summary"]["files_written"], 0)
            self.assertTrue(all(f["status"] != "FIXED" for m in report["modules"] for f in m["findings"]))

    def test_human_output_says_planned_not_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _Sample(tmp).migrate("--fix", "--dry-run", fmt="json")
            self.assertNotIn("[done] ", proc.stdout)
            self.assertNotIn("fixed=", proc.stdout)
            self.assertIn("would change 1 file(s)", proc.stdout)

    def test_html_summary_labels_dry_run_edits_as_planned(self):
        with tempfile.TemporaryDirectory() as tmp:
            _Sample(tmp).migrate("--fix", "--dry-run", fmt="html")
            html = (Path(tmp) / "report.html").read_text(encoding="utf-8")
            self.assertIn("Edits planned", html)
            self.assertNotIn("Edits applied", html)


class EditsCarryFixClass(unittest.TestCase):
    def test_planned_edits_carry_fix_class_in_json_and_human_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, report = _Sample(tmp).dry_run()
            edits = [e for m in report["modules"] for e in m["edits"]]
            self.assertTrue(edits)
            self.assertTrue(all(e.get("fix_class") in ("certified", "legacy", "experimental") for e in edits))
            self.assertIn("[legacy]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
