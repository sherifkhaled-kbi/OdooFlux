"""Approved partial-migration policy on the AI path: an invalid or unresolved AI edit refuses only its own file.

The other files of the module keep their valid AI edits; a refused file keeps its original bytes; refused edits are
never counted as applied. No network: the legacy call is replaced by a canned response and the escalation pass uses
the fake provider script.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.integration.ai import test_pipeline_pass as pp
from tests.unit.ai import _helpers as h
from odooflux.builtins import build_context
from odooflux.cli.migrate import make_validate_text
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import (RunOptions, new_state, reports_from_state, report_from_dict,
                                            run_pipeline)
from odooflux.core.orchestrator.status import PARTIAL_STATUS
from odooflux.discovery.modules import module_ref
from odooflux.reporting.model.model import build_report
from odooflux.ai.providers import legacy_anthropic as legacy
from odooflux.rules.shared.legacy_rules import (SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, Issue,
                                                MigrationReport)

SOURCE_A = pp.SOURCE
SOURCE_B = ("from odoo import models\n\n\nclass B(models.Model):\n    _name = 'kbi.b'\n\n"
            "    def g_ok(self):\n        return old_api(2)\n")
MARK = "# L3-BAD"


def _issue(path, line=1):
    return Issue(file=str(path), line=line, severity=SEVERITY_CRITICAL, category="legacy.manual",
                 message="needs a hand", suggestion="fix it", auto_fixable=False)


def _writer(report_sink=None):
    """A write_module stand-in that writes every edit's kept text, as the core writer does for accepted edits."""
    def write_module(module_path, edits, report) -> int:
        for edit in edits:
            Path(edit.dest).write_text(edit.fixed, encoding="utf-8")
        return len(edits)
    return write_module


class LegacyFixBundlePerFileTests(unittest.TestCase):
    """fix_bundle: an invalid AI output for one file must not block the other file of the same module."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = self.tmp / "kbi_ai"
        (self.mod / "models").mkdir(parents=True)
        (self.mod / "models" / "a.py").write_text(SOURCE_A)
        (self.mod / "models" / "b.py").write_text(SOURCE_B)
        self.run = SimpleNamespace(log_dir=self.tmp / "logs", log=SimpleNamespace(append=lambda *a, **k: None))
        self.validate = make_validate_text(build_context().registries)

    def _call(self, files):
        report = MigrationReport(module_path=str(self.mod), from_version=14, to_version=15)
        report.issues = [_issue(self.mod / "models" / "a.py"), _issue(self.mod / "models" / "b.py")]
        reply = json.dumps({"files": files, "skipped": [], "notes": ""})
        with mock.patch.object(legacy, "_call_claude_api", lambda *a, **k: reply):
            count = legacy.fix_bundle(reports=[report], module_paths=[self.mod], api_key="x", run=self.run,
                                      write_module=_writer(), validate_text=self.validate)
        return count, report

    def test_invalid_file_is_refused_and_valid_sibling_is_still_written(self):
        new_b = SOURCE_B.replace("old_api(2)", "new_api(2)")
        count, report = self._call({"kbi_ai/a.py": "def f_ok(self:\n", "kbi_ai/b.py": new_b})
        self.assertEqual((self.mod / "models" / "a.py").read_text(), SOURCE_A, "refused file keeps its bytes")
        self.assertEqual((self.mod / "models" / "b.py").read_text(), new_b, "valid sibling is written")
        self.assertEqual(count, 1, "only the written edit is counted as applied")
        refused = [i for i in report.issues if i.category == "Fix Rejected"]
        self.assertEqual([i.file for i in refused], [str(self.mod / "models" / "a.py")])
        self.assertTrue(refused[0].rejection_reason.startswith("INVALID"))
        self.assertFalse(any(i.fix_applied for i in refused))

    def test_module_is_not_rolled_back_when_every_ai_edit_is_refused(self):
        count, report = self._call({"kbi_ai/a.py": "def f_ok(self:\n", "kbi_ai/b.py": "def g(:\n"})
        self.assertEqual(count, 0)
        self.assertEqual((self.mod / "models" / "a.py").read_text(), SOURCE_A)
        self.assertEqual((self.mod / "models" / "b.py").read_text(), SOURCE_B)
        self.assertEqual(len([i for i in report.issues if i.category == "Fix Rejected"]), 2)


class EscalationLayer3PerFileTests(unittest.TestCase):
    """Escalation: a layer-3 regression caused by one file's AI edit refuses that file only."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state_dir = self.tmp / "state"
        self.script = self.tmp / "script.json"
        self.module = self.tmp / "kbi_ai"
        (self.module / "models").mkdir(parents=True)
        (self.module / "__manifest__.py").write_text(
            "{'name': 'kbi_ai', 'version': '14.0.1.0.0', 'depends': ['base']}\n")
        (self.module / "models" / "__init__.py").write_text("from . import a, b\n")
        (self.module / "models" / "a.py").write_text(SOURCE_A)
        (self.module / "models" / "b.py").write_text(SOURCE_B)
        self.script.write_text(json.dumps({"entries": [
            {"match": {"contains": "def f_ok"}, "response": {
                "replacement": "    def f_ok(self):\n        return new_api(1)\n", "notes": "", "cannot_fix": False}},
            {"match": {"contains": "def g_ok"}, "response": {
                "replacement": f"    def g_ok(self):\n        return new_api(2)  {MARK}\n", "notes": "",
                "cannot_fix": False}}]}))

    class _Layer3:
        """Regresses (a new finding) when models/b.py carries the marker; the baseline module has none."""

        def __call__(self, path, to_version):
            text = (Path(path) / "models" / "b.py").read_text()
            findings = ([SimpleNamespace(rule_id="L3.marker", path="models/b.py", message="marker present")]
                        if MARK in text else [])
            return findings, SimpleNamespace(outcome="PASS")

    def _run(self):
        ctx = build_context()
        ctx.registries.rules.register(pp.ToyRule())
        entry = ctx.registries.ai_providers.get("ai-escalation")
        entry.metadata_source = lambda: h.TOY_METAS
        entry.environ = {}
        entry.layer3 = self._Layer3()
        cfg = {"enabled": True, "provider_type": "external", "provider": "fake", "model": "fake-model",
               "consent_send_code": True, "authorizations": {}, "kill_switch": False, "endpoint": "",
               "catalog_paths": [], "budget_job_tokens": 100000, "budget_module_tokens": None,
               "budget_file_tokens": None, "budget_request_tokens": None, "budget_job_cost": None,
               "max_retries": 0, "timeout_s": 5.0, "use_cache": False, "clear_cache": False, "secrets_file": "",
               "fake_script": str(self.script)}
        refs = [module_ref(Path(self.module), 0)]
        plan = build_plan(ctx.graph(), "14.0", "15.0", refs)
        options = RunOptions(from_version=14, to_version=15, mode="fix", backup=True, ai=True,
                             module_paths=[str(self.module)])
        run = RunDir.create(self.state_dir, reversible=True, with_backup=True)
        state = new_state(run, plan, options, plan.modules)
        state["ai_config"] = cfg
        run.write_state(state)
        run_pipeline(run, state, ctx.registries, validate_text=make_validate_text(ctx.registries),
                     layer3=ctx.layer3)
        return state

    def test_layer3_regression_refuses_only_the_regressing_file(self):
        state = self._run()
        self.assertIn("new_api(1)", (self.module / "models" / "a.py").read_text(),
                      "the file whose AI edit is clean is written")
        self.assertEqual((self.module / "models" / "b.py").read_text(), SOURCE_B,
                         "the file whose AI edit regresses keeps its bytes")
        report = report_from_dict(dict(state["modules"][0]["report"]))
        refused = [i for i in report.issues if i.category == "Fix Rejected"]
        self.assertEqual([i.file for i in refused], [str(self.module / "models" / "b.py")])
        self.assertIn("layer3", refused[0].rejection_reason)
        fixed_a = [i for i in report.issues if i.category == "toy.old-api" and i.file.endswith("a.py")]
        fixed_b = [i for i in report.issues if i.category == "toy.old-api" and i.file.endswith("b.py")]
        self.assertTrue(fixed_a and all(i.fix_applied for i in fixed_a))
        self.assertTrue(fixed_b and not any(i.fix_applied for i in fixed_b), "refused edit is never counted as applied")

    def test_ai_refused_module_is_partial_in_the_report_model(self):
        state = self._run()
        entry = state["modules"][0]
        a, b = str(self.module / "models" / "a.py"), str(self.module / "models" / "b.py")
        self.assertEqual(entry["migration_status"], PARTIAL_STATUS)
        self.assertIn(b, entry["refused_files"])
        self.assertNotIn(a, entry["refused_files"])
        self.assertTrue(entry["rejections"])
        self.assertIn("new_api(1)", Path(a).read_text(), "sibling is written")
        self.assertEqual(Path(b).read_text(), SOURCE_B, "refused file is byte-identical")
        report = build_report(state, reports_from_state(state), run_log_path="")
        self.assertEqual(report["modules"][0]["status"], PARTIAL_STATUS)


class AIRefusalRecordingTests(unittest.TestCase):
    """ai_pass records only the refusals the AI pass added; a refusal already on the report is not repeated."""

    def test_refusals_already_on_the_report_are_not_recorded_again(self):
        from odooflux.core.orchestrator import ai_pass
        mod = Path(tempfile.mkdtemp()) / "kbi_ai"
        a, b = str(mod / "models" / "a.py"), str(mod / "models" / "b.py")
        report = MigrationReport(module_path=str(mod), from_version=14, to_version=15)
        report.issues.append(Issue(file=a, line=0, severity=SEVERITY_WARNING, category="Fix Rejected", message="m",
                                   suggestion="s", auto_fixable=False, rejection_reason="INVALID: earlier"))
        before = ai_pass._issue_ids([report])[0]
        report.issues.append(Issue(file=b, line=0, severity=SEVERITY_INFO, category="AI Rejected", message="m",
                                   suggestion="s", auto_fixable=False, rejection_reason="rejected:syntax_invalid"))
        entry = {"rejections": ["INVALID: earlier"], "refused_files": {a: "INVALID: earlier"}}
        ai_pass._record_refusals(entry, report, before)
        self.assertEqual(entry["rejections"], ["INVALID: earlier", "rejected:syntax_invalid"])
        self.assertEqual(entry["refused_files"], {a: "INVALID: earlier", b: "rejected:syntax_invalid"})
        self.assertEqual(entry["migration_status"], PARTIAL_STATUS)


if __name__ == "__main__":
    unittest.main()
