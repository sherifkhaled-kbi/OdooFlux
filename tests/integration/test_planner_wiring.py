"""T082-T084 (FR-017, FR-019, FR-020; ADR-018): run parameters and the dependency scanner reach the report
through the real CLI and pipeline, not only through ``bind_rule``/scanner unit calls."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from .helpers import REPO, new_tmp

PREFIX_RULE = "*.manifest.version-prefix"


def _cli(args):
    proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), *map(str, args)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
                          env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    return proc.returncode, proc.stdout


def _module(root: Path, name: str, version: str, depends=("base",)) -> Path:
    path = root / "addons" / name
    path.mkdir(parents=True)
    (path / "__manifest__.py").write_text(
        repr({"name": name, "version": version, "depends": list(depends)}) + "\n", encoding="utf-8")
    return path


def _findings(report_file: Path) -> list:
    data = json.loads(report_file.read_text(encoding="utf-8"))
    return [f for m in data["modules"] for f in m["findings"]]


def _analyze(root, module, frm, to, *extra):
    report = root / "report.json"
    code, out = _cli(["--module", module, "--from-version", frm, "--to-version", to, "--report-format", "json",
                      "--report", report, "--state-dir", root / "state", *extra])
    return code, out, _findings(report)


class VersionPrefixWiringTests(unittest.TestCase):
    def test_target_reaches_rule_through_cli_when_opted_in(self):
        root = new_tmp()
        module = _module(root, "m1", "17.0.1.0.0")
        code, out, found = _analyze(root, module, "17", "18", "--enable-rule", PREFIX_RULE)
        hits = [f for f in found if f["rule_id"] == PREFIX_RULE]
        self.assertEqual(len(hits), 1, out)
        self.assertEqual(hits[0]["severity"], "INFO")

    def test_matching_prefix_is_not_flagged(self):
        root = new_tmp()
        module = _module(root, "m1", "18.0.1.0.0")
        _code, _out, found = _analyze(root, module, "17", "18", "--enable-rule", PREFIX_RULE)
        self.assertEqual([f for f in found if f["rule_id"] == PREFIX_RULE], [])

    def test_opt_in_only_and_never_edits(self):
        root = new_tmp()
        module = _module(root, "m1", "17.0.1.0.0")
        _code, _out, found = _analyze(root, module, "17", "18")
        self.assertEqual([f for f in found if f["rule_id"] == PREFIX_RULE], [])
        # SC-005: opting in adds detection only; the written manifest is identical to a run without it.
        other = new_tmp()
        twin = _module(other, "m1", "17.0.1.0.0")
        base = ["--from-version", "17", "--to-version", "18", "--fix", "--no-backup"]
        _cli(["--module", module, *base, "--enable-rule", PREFIX_RULE, "--state-dir", root / "state2"])
        _cli(["--module", twin, *base, "--state-dir", other / "state2"])
        self.assertEqual((module / "__manifest__.py").read_text(), (twin / "__manifest__.py").read_text())

    def test_unknown_rule_id_is_a_usage_error(self):
        root = new_tmp()
        module = _module(root, "m1", "17.0.1.0.0")
        code, out = _cli(["--module", module, "--from-version", "17", "--to-version", "18",
                          "--enable-rule", "no.such.rule", "--state-dir", root / "state"])
        self.assertEqual(code, 2, out)


class MissingRunInputGapTests(unittest.TestCase):
    def test_missing_target_is_an_info_gap_in_the_report(self):
        from odooflux.builtins import build_context
        from odooflux.core.jobs.state_dir import RunDir
        from odooflux.core.orchestrator import run_inputs
        from odooflux.core.orchestrator.plan import build_plan
        from odooflux.core.orchestrator.run import RunOptions, new_state, run_pipeline
        from odooflux.discovery.modules import module_ref
        root = new_tmp()
        module = _module(root, "m1", "17.0.1.0.0")
        ctx = build_context()
        plan = build_plan(ctx.graph(), "17.0", "18.0", [module_ref(module, 0)])
        options = RunOptions(from_version=17, to_version=18, mode="analyze", module_paths=[str(module)],
                             enable_rules=[PREFIX_RULE])
        run = RunDir.create(root / "state", reversible=True, with_backup=False)
        state = new_state(run, plan, options, plan.modules)
        with mock.patch.object(run_inputs, "run_params_for", return_value={}):
            run_pipeline(run, state, ctx.registries, layer3=ctx.layer3)
        issues = state["modules"][0]["report"]["issues"]
        gaps = [i for i in issues if i["severity"] == "INFO" and "run input not supplied" in i["message"]]
        self.assertEqual(len(gaps), 1, issues)
        self.assertFalse([i for i in issues if i["category"] == PREFIX_RULE])


class DependencyScannerWiringTests(unittest.TestCase):
    def test_removed_module_with_successor_reaches_report(self):
        root = new_tmp()
        module = _module(root, "m1", "15.0.1.0.0", depends=("base", "payment_transfer"))
        _code, out, found = _analyze(root, module, "15", "16")
        hits = [f for f in found if f["rule_id"] == "*.deps.removed-with-successor"]
        self.assertEqual(len(hits), 1, out)
        self.assertIn("payment_custom", hits[0]["message"])
        self.assertIn("EV-520", hits[0]["message"])

    def test_unknown_dependency_reaches_report(self):
        root = new_tmp()
        module = _module(root, "m1", "15.0.1.0.0", depends=("base", "zzz_unknown_mod"))
        _code, _out, found = _analyze(root, module, "15", "16")
        hits = [f for f in found if f["rule_id"] == "*.deps.unknown-dependency"]
        self.assertEqual([h["severity"] for h in hits], ["WARNING"])

    def test_sibling_dependency_is_not_flagged(self):
        root = new_tmp()
        a = _module(root, "m_a", "15.0.1.0.0", depends=("base", "m_b"))
        _module(root, "m_b", "15.0.1.0.0")
        report = root / "report.json"
        _cli(["--modules", a, a.parent / "m_b", "--from-version", "15", "--to-version", "16",
              "--report-format", "json", "--report", report, "--state-dir", root / "state"])
        self.assertEqual([f for f in _findings(report) if f["rule_id"].startswith("*.deps.")], [])

    def test_missing_core_list_is_an_info_gap(self):
        from odooflux.dependencies.scan import scan_run_dependencies
        findings, gaps = scan_run_dependencies([], 99, 100)
        self.assertEqual(findings, {})
        self.assertTrue(gaps and gaps[0].startswith("INFO"))


if __name__ == "__main__":
    unittest.main()
