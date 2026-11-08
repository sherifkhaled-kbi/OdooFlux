"""T044/T045 wiring (FR-016, REQ-AI-003): the orchestrator's AI pass runs escalation through the gateway, reuses the edit
engine, the re-scan, validation, backup and promotion, and records usage."""

import json
import shutil
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from tests.unit.ai import _helpers as h
from odooflux.builtins import build_context
from odooflux.cli.migrate import make_validate_text
from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.contracts.records import Finding
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import RunOptions, new_state, report_from_dict, run_pipeline
from odooflux.discovery.modules import module_ref

SOURCE = "from odoo import models\n\n\nclass A(models.Model):\n    _name = 'kbi.a'\n\n    def f_ok(self):\n        return old_api(1)\n"
SCRIPT = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
    "replacement": "    def f_ok(self):\n        return new_api(1)\n", "notes": "", "cannot_fix": False,
    "usage": {"input": 90, "output": 12}}}]}


class ToyRule:
    key = "toy.rule"
    contract_version = CONTRACT_VERSION
    step = "*"
    depends = ()

    def __init__(self, rule_id="toy.old-api", needle="old_api("):
        self.rule_id, self.needle = rule_id, needle

    def detect(self, document):
        if not document.path.endswith(".py"):
            return []
        return [Finding(rule_id=self.rule_id, path=document.path, line=n, severity="WARNING",
                        message="old_api is gone", suggestion="use new_api")
                for n, line in enumerate(document.text.splitlines(), 1) if self.needle in line]


def make_module(root: Path, source=SOURCE) -> Path:
    mod = root / "kbi_ai"
    (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'kbi_ai', 'version': '14.0.1.0.0', 'depends': ['base']}\n")
    (mod / "models" / "__init__.py").write_text("from . import a\n")
    (mod / "models" / "a.py").write_text(source)
    return mod


class PipelineAIPassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state_dir = self.tmp / "state"
        self.script = self.tmp / "script.json"
        self.script.write_text(json.dumps(SCRIPT))
        self.catalog = self.tmp / "catalog.json"
        self.catalog.write_text(json.dumps(h.test_catalog()))

    def run_ai(self, module, cfg_overrides=None, metas=None, rule=None, environ=None):
        ctx = build_context()
        ctx.registries.rules.register(rule or ToyRule())
        entry = ctx.registries.ai_providers.get("ai-escalation")
        entry.metadata_source = lambda: (metas or h.TOY_METAS)
        entry.environ = environ if environ is not None else {}
        cfg = {"enabled": True, "provider_type": "external", "provider": "fake", "model": "fake-model",
               "consent_send_code": True, "authorizations": {}, "kill_switch": False, "endpoint": "",
               "catalog_paths": [], "budget_job_tokens": 100000, "budget_module_tokens": None,
               "budget_file_tokens": None, "budget_request_tokens": None, "budget_job_cost": None,
               "max_retries": 0, "timeout_s": 5.0, "use_cache": True, "clear_cache": False, "secrets_file": "",
               "fake_script": str(self.script)}
        cfg.update(cfg_overrides or {})
        refs = [module_ref(Path(module), 0)]
        plan = build_plan(ctx.graph(), "14.0", "15.0", refs)
        options = RunOptions(from_version=14, to_version=15, mode="fix", backup=True, ai=True,
                             module_paths=[str(module)])
        run = RunDir.create(self.state_dir, reversible=True, with_backup=True)
        state = new_state(run, plan, options, plan.modules)
        state["ai_config"] = cfg
        run.write_state(state)
        run_pipeline(run, state, ctx.registries, validate_text=make_validate_text(ctx.registries),
                     layer3=ctx.layer3)
        return state, run

    def test_accepted_edit_is_written_after_validation_and_reported_fixed(self):
        module = make_module(self.tmp)
        state, run = self.run_ai(module)
        text = (module / "models" / "a.py").read_text()
        self.assertIn("new_api(1)", text)
        self.assertNotIn("old_api", text)
        self.assertEqual(state["ai_usage"]["requests"], 1)
        self.assertEqual(state["ai_usage"]["totals"]["input_tokens"], 90)
        report = report_from_dict(dict(state["modules"][0]["report"]))
        fixed = [i for i in report.issues if i.category == "toy.old-api"]
        self.assertTrue(fixed and all(i.fix_applied for i in fixed))
        self.assertTrue(any(run.backup_dir.rglob("a.py")))  # the normal backup preceded the write
        self.assertTrue((self.state_dir / "ai-cache").is_dir())

    def test_second_run_on_unchanged_input_makes_zero_provider_calls(self):
        first = self.tmp / "one"
        first.mkdir()
        self.run_ai(make_module(first))
        second = self.tmp / "two"
        second.mkdir()
        state, _ = self.run_ai(make_module(second))
        self.assertEqual(state["ai_usage"]["provider_calls"], 0)
        self.assertEqual(state["ai_usage"]["cache_hits"], 1)
        self.assertIn("new_api", (second / "kbi_ai" / "models" / "a.py").read_text())

    def test_review_required_rule_adds_a_review_notice_that_caps_the_module(self):
        module = make_module(self.tmp, SOURCE.replace("old_api(", "legacy_call("))
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return fixed(1)\n", "notes": "", "cannot_fix": False}}]}
        self.script.write_text(json.dumps(script))
        state, _ = self.run_ai(module, rule=ToyRule("toy.review", "legacy_call("))
        report = report_from_dict(dict(state["modules"][0]["report"]))
        notices = [i for i in report.issues if i.category == "AI Review Required"]
        self.assertEqual(len(notices), 1)
        self.assertFalse(notices[0].auto_fixable or notices[0].fix_applied)

    def test_unauthorized_external_provider_sends_nothing_and_leaves_finding_open(self):
        module = make_module(self.tmp)
        calls = []

        def guard(*a, **k):
            calls.append(a)
            raise AssertionError("transport opened")
        with mock.patch.object(urllib.request, "urlopen", guard), mock.patch.object(socket.socket, "connect", guard):
            state, _ = self.run_ai(module, {"provider": "alpha", "model": "m-one", "catalog_paths": [str(self.catalog)]},
                                   environ={"ALPHA_KEY": "k-12345678901"})
        self.assertEqual(calls, [])
        self.assertEqual((module / "models" / "a.py").read_text(), SOURCE)
        report = report_from_dict(dict(state["modules"][0]["report"]))
        self.assertTrue([i for i in report.issues if i.category == "AI Error" and "authorization_missing" in i.message])
        self.assertEqual(state["ai_usage"]["provider_calls"], 0)

    def test_ineligible_findings_cause_zero_requests(self):
        module = make_module(self.tmp)
        from odooflux.ai.escalation import RuleMeta
        metas = {"toy.old-api": RuleMeta("toy.old-api", ai_eligible=True, has_fix=True, evidence=h.EVIDENCE)}
        state, _ = self.run_ai(module, metas=metas)
        self.assertEqual(state["ai_usage"]["requests"], 0)
        self.assertEqual((module / "models" / "a.py").read_text(), SOURCE)

    def test_rejected_edit_is_not_written_and_is_reported(self):
        module = make_module(self.tmp)
        script = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return new_api(1\n", "notes": "", "cannot_fix": False}}]}
        self.script.write_text(json.dumps(script))
        state, _ = self.run_ai(module)
        self.assertEqual((module / "models" / "a.py").read_text(), SOURCE)
        self.assertEqual(state["ai_usage"]["rejections"], {"syntax_invalid": 1})

    def test_usage_is_reported_in_the_report_model_and_matches_its_schema(self):
        from odooflux.core.orchestrator.run import reports_from_state
        from odooflux.reporting.model.model import build_report
        from odooflux.reporting.model import schema_check
        module = make_module(self.tmp)
        state, run = self.run_ai(module)
        report = build_report(state, reports_from_state(state), run_log_path="")
        ai = report["ai_usage"]
        self.assertTrue(ai["enabled"])
        self.assertIs(ai["consent"], True)
        self.assertEqual(ai["providers"], [{"name": "fake", "model": "fake-model", "requests": 1, "input_tokens": 90,
                                            "output_tokens": 12, "cached_tokens": 0, "cost": None}])
        self.assertTrue(all(isinstance(e, str) for e in ai["budget_events"]))
        self.assertEqual(ai["totals"]["input_tokens"], 90)
        self.assertEqual(schema_check.validate_report(report), [])

    def test_budget_events_are_reported_as_text(self):
        module = make_module(self.tmp)
        state, _ = self.run_ai(module, {"budget_job_tokens": 50})
        ai = state["ai_usage"]
        self.assertEqual(ai["budget_events"], ["budget_job: limit 50, used 0"])
        self.assertEqual(ai["budget_event_details"][0]["scope"], "job")

    def test_state_holds_no_credential(self):
        module = make_module(self.tmp)
        state, run = self.run_ai(module, environ={"ALPHA_KEY": "canary-credential-value"})
        for path in run.root.rglob("*"):
            if path.is_file():
                self.assertNotIn("canary-credential-value", path.read_text(errors="ignore"))

    def test_check_config_reports_catalog_errors_before_any_work(self):
        entry = build_context().registries.ai_providers.get("ai-escalation")
        base = {"provider": "alpha", "model": "nope", "catalog_paths": [str(self.catalog)], "authorizations": {},
                "endpoint": "", "budget_job_cost": None, "fake_script": ""}
        self.assertIn("model_not_in_catalog", entry.check_config(base))
        self.assertIn("unknown_provider", entry.check_config(dict(base, provider="nobody")))
        self.assertIsNone(entry.check_config(dict(base, model="m-one")))
        self.assertIn("forbidden_category", entry.check_config(dict(base, model="m-one", authorizations={"alpha": ["credentials"]})))
        self.assertIn("pricing", entry.check_config(dict(base, model="m-nopricing", budget_job_cost=1.0)))
        self.assertIn("catalog_invalid", entry.check_config(dict(base, catalog_paths=[str(self.tmp / "missing.json")])))
        self.assertIn("endpoint_not_https", entry.check_config(dict(base, model="m-one", endpoint="http://x.example")))


if __name__ == "__main__":
    unittest.main()
