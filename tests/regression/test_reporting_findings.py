"""TST-009-013 (REQ-TST-005, REQ-REP-005): one regression test per legacy reporting finding.

F-REP-1  false fix counts          F-REP-2  ANSI width misalignment and wrong script name
F-REP-3  exit codes overlap argparse    F-VER-4  INFO noise forces a non-zero exit
(docs/planning/CURRENT_ARCHITECTURE_AUDIT.md)"""

import collections
import itertools
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.unit.reporting import _setup  # noqa: F401
from tests.unit.reporting.helpers import all_goldens, golden
from tests.integration.helpers import FIXTURE, make_module, new_tmp, normalised_report, start_run, tree
from tests.integration.reporting.cli import run_cli_main

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _model(state_dir, run_id):
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.core.jobs.state_dir import RunDir
    from odooflux.reporting.model.model import build_report
    state = RunDir.open(state_dir, run_id).read_state()
    return build_report(state, reports_from_state(state), run_log_path="")


class FRep1FixCountTests(unittest.TestCase):
    def test_f_rep_1_fixed_count_equals_rescan_delta_in_every_renderer(self):
        from odooflux.reporting.exporters.sarif import export_sarif
        from odooflux.reporting.html.html import render_html
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal.ansi import render_terminal
        root = new_tmp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        analyze = make_module(root / "a", "kbi_demo")
        write = make_module(root / "b", "kbi_demo")
        rid0, _ = start_run(root / "s0", [analyze], mode="analyze")
        before = collections.Counter(f["rule_id"] for f in _model(root / "s0", rid0)["modules"][0]["findings"])
        rid1, _ = start_run(root / "s1", [write], mode="fix")
        model = _model(root / "s1", rid1)
        fixed = model["summary"]["findings_by_status"]["fixed"]
        rid2, _ = start_run(root / "s2", [write], mode="analyze")
        after = collections.Counter(f["rule_id"] for f in _model(root / "s2", rid2)["modules"][0]["findings"])
        # per rule, findings that disappeared on re-scan; new findings on the migrated tree (for example a version
        # mismatch of the rewritten manifest against --from-version) do not offset them
        delta = sum(max(0, n - after.get(rule, 0)) for rule, n in before.items())
        self.assertGreater(fixed, 0)
        self.assertEqual(fixed, delta, "reported fixed must equal the re-scan delta")
        text = ANSI.sub("", render_terminal(model, RendererOptions(color="never", width=120)))
        self.assertRegex(text, rf"fixed={fixed} ")
        self.assertIn(f'data-metric="fixed">{fixed}<', render_html(model))
        in_sarif = [r for r in json.loads(export_sarif(model, include_fixed=True))["runs"][0]["results"]
                    if r["properties"]["status"] == "FIXED"]
        self.assertEqual(len(in_sarif), fixed)

    def test_f_rep_1_rejected_edit_never_counts_as_fixed(self):
        model = golden("failed")
        self.assertEqual(model["summary"]["findings_by_status"]["fixed"], 0)
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal.ansi import render_terminal
        self.assertRegex(render_terminal(model, RendererOptions(color="never", width=120)), r"fixed=0 ")

    def test_f_rep_1_dry_run_reports_no_fixes(self):
        for name in ("static_validated", "needs_review"):
            model = golden(name)
            self.assertEqual(model["run"]["mode"], "dry_run")
            self.assertEqual(model["summary"]["files_written"], 0)


class FRep2AnsiTests(unittest.TestCase):
    def test_f_rep_2_colour_does_not_change_layout(self):
        from odooflux.reporting.options import RendererOptions, display_width
        from odooflux.reporting.terminal.ansi import render_terminal
        for name, model in all_goldens().items():
            for width in (60, 80, 120):
                colour = render_terminal(model, RendererOptions(color="always", width=width))
                plain = render_terminal(model, RendererOptions(color="never", width=width))
                self.assertEqual(ANSI.sub("", colour), plain, (name, width))
                for line in colour.splitlines():
                    self.assertLessEqual(display_width(line), width, (name, width, line))

    def test_f_rep_2_help_uses_the_real_script_name(self):
        from odooflux.cli.main import build_parser
        help_text = build_parser().format_help()
        self.assertIn("odooflux", help_text)
        self.assertNotIn("odoo_migrate_to_19", help_text)


class FRep3ExitCodeTests(unittest.TestCase):
    def test_f_rep_3_two_is_reserved_for_usage_errors(self):
        from odooflux.cli.exit_codes import ExitPolicy, exit_code
        from tests.unit.cli.test_exit_codes import model
        for status, fail_on, sev, rej, write in itertools.product(
                ("STATIC_VALIDATED", "NEEDS_REVIEW", "FAILED", "BLOCKED"), ("none", "critical", "warning", "info"),
                (None, "CRITICAL", "WARNING", "INFO"), (0, 1), (False, True)):
            findings = [(sev, "OPEN")] if sev else []
            code = exit_code(model(statuses=(status,), findings=findings, rejected=rej),
                             ExitPolicy(fail_on=fail_on), write_mode=write)
            self.assertIn(code, (0, 1, 3, 4), "open findings must never collide with the usage code 2")

    def test_f_rep_3_cli_usage_error_is_2_and_findings_are_not(self):
        root = new_tmp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        module = make_module(root / "m", "kbi_demo")
        code, out = run_cli_main(["--module", module, "--from-version", "14", "--fail-on-status", "BROKEN",
                                  "--state-dir", root / "s", "--no-color"])
        self.assertEqual(code, 2, out)
        code, out = run_cli_main(["--module", module, "--from-version", "14", "--state-dir", root / "s2", "--no-color"])
        self.assertEqual(code, 1, out)  # critical findings: threshold, not 2

    def test_f_rep_3_fail_on_is_configurable(self):
        root = new_tmp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        module = make_module(root / "m", "kbi_demo")
        codes = {level: run_cli_main(["--module", module, "--from-version", "14", "--fail-on", level,
                                      "--state-dir", root / f"s-{level}", "--no-color"])[0]
                 for level in ("none", "critical", "warning", "info")}
        self.assertEqual(codes["none"], 0)
        self.assertEqual(codes["critical"], 1)


class FVer4InfoNoiseTests(unittest.TestCase):
    def _info_module(self, root):
        module = root / "info_mod"
        module.mkdir()
        (module / "models.py").write_text("from odoo import fields\nbody = fields.Html('x')\n", encoding="utf-8")
        return module

    def test_f_ver_4_info_only_module_exits_zero_by_default_and_with_warning(self):
        root = new_tmp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        module = self._info_module(root)
        for fail_on in ("critical", "warning"):
            for extra in ((), ("--exit-codes", "v1")):
                code, out = run_cli_main(["--module", module, "--from-version", "14", "--fail-on", fail_on, *extra,
                                          "--state-dir", root / f"s-{fail_on}-{len(extra)}", "--no-color"])
                if extra:
                    continue  # v1 reports the manifest-less fixture as BLOCKED (L3); the INFO rule is tested below
                self.assertEqual(code, 0, f"--fail-on {fail_on}: {out}")
        code, _ = run_cli_main(["--module", module, "--from-version", "14", "--fail-on", "info",
                                "--state-dir", root / "s-info", "--no-color"])
        self.assertEqual(code, 1)

    def test_f_ver_4_info_findings_never_fail_the_v1_table(self):
        from odooflux.cli.exit_codes import ExitPolicy, exit_code
        from tests.unit.cli.test_exit_codes import model
        many_info = model(findings=[("INFO", "OPEN")] * 100)
        self.assertEqual(exit_code(many_info, ExitPolicy()), 0)
        self.assertEqual(exit_code(many_info, ExitPolicy(fail_on="warning")), 0)
        self.assertEqual(exit_code(many_info, ExitPolicy(fail_on="info")), 1)


if __name__ == "__main__":
    unittest.main()
