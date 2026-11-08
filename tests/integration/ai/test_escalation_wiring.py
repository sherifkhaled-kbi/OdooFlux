"""WS-C wiring (REQ-AI-002, FR-019, FR-020): an eligible review_required finding reaches the gateway only when the
data categories it needs are authorized, the kill switch and an ineligible rule each keep it away from the provider.

Eligibility is driven by test-only rule metadata (``tests.unit.ai._helpers.TOY_METAS``); no knowledge-base rule is
marked ai_eligible here.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.integration.ai.test_pipeline_pass import SOURCE, ToyRule, make_module
from tests.unit.ai import _helpers as h
from tests.unit.ai._gateway_support import RecordingTransport, ok_openai
from odooflux.ai.escalation import RuleMeta
from odooflux.ai.gateway import Gateway
from odooflux.builtins import build_context
from odooflux.cli.migrate import make_validate_text
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.plan import build_plan
from odooflux.core.orchestrator.run import RunOptions, new_state, report_from_dict, run_pipeline
from odooflux.discovery.modules import module_ref

LEGACY_SOURCE = SOURCE.replace("old_api(", "legacy_call(")
REVIEW_REPLACEMENT = "    def f_ok(self):\n        return fixed(1)\n"
REVIEW_RESPONSE = json.dumps({"replacement": REVIEW_REPLACEMENT, "notes": "", "cannot_fix": False})
ENV = {"ALPHA_KEY": "k-alpha-1234567"}
EVIDENCE_META = RuleMeta("toy.review", ai_eligible=True, has_fix=False, evidence=h.EVIDENCE, review_required=True)


class EligibleReviewWiringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.catalog = self.tmp / "catalog.json"
        self.catalog.write_text(json.dumps(h.test_catalog()))
        self.transport = RecordingTransport([ok_openai(REVIEW_RESPONSE)])
        self.gateway_calls = []

    def run_pass(self, *, authorizations, kill=False, metas=None):
        module = make_module(self.tmp, LEGACY_SOURCE)
        ctx = build_context()
        ctx.registries.rules.register(ToyRule("toy.review", "legacy_call("))
        entry = ctx.registries.ai_providers.get("ai-escalation")
        entry.metadata_source = lambda: (metas or {"toy.review": EVIDENCE_META})
        entry.environ = dict(ENV)
        entry.transport_for = lambda name: self.transport
        cfg = {"enabled": True, "provider_type": "external", "provider": "alpha", "model": "m-one",
               "consent_send_code": True, "authorizations": authorizations, "kill_switch": kill, "endpoint": "",
               "catalog_paths": [str(self.catalog)], "budget_job_tokens": 100000, "budget_module_tokens": None,
               "budget_file_tokens": None, "budget_request_tokens": None, "budget_job_cost": None,
               "max_retries": 0, "timeout_s": 5.0, "use_cache": False, "clear_cache": False, "secrets_file": "",
               "fake_script": ""}
        state_dir = self.tmp / "state"
        plan = build_plan(ctx.graph(), "14.0", "15.0", [module_ref(Path(module), 0)])
        options = RunOptions(from_version=14, to_version=15, mode="fix", backup=True, ai=True,
                             module_paths=[str(module)])
        run = RunDir.create(state_dir, reversible=True, with_backup=True)
        state = new_state(run, plan, options, plan.modules)
        state["ai_config"] = cfg
        run.write_state(state)

        original = Gateway.complete

        def spy(gw, req, **kwargs):
            self.gateway_calls.append(req)
            return original(gw, req, **kwargs)

        with mock.patch.object(Gateway, "complete", spy):
            run_pipeline(run, state, ctx.registries, validate_text=make_validate_text(ctx.registries),
                         layer3=ctx.layer3)
        report = report_from_dict(dict(state["modules"][0]["report"]))
        return state, report, module

    def test_authorized_categories_reach_the_gateway_once(self):
        state, report, module = self.run_pass(authorizations={"alpha": ["evidence_excerpt", "source_python"]})
        self.assertEqual(len(self.gateway_calls), 1)
        self.assertEqual(self.gateway_calls[0].data_categories, ("source_python", "evidence_excerpt"))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertEqual(state["ai_usage"]["provider_calls"], 1)
        self.assertIn("fixed(1)", (module / "models" / "a.py").read_text())
        self.assertTrue([i for i in report.issues if i.category == "AI Review Required"])

    def test_no_authorization_sends_nothing(self):
        state, report, module = self.run_pass(authorizations={})
        self.assertEqual(len(self.gateway_calls), 1)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(state["ai_usage"]["provider_calls"], 0)
        self.assertEqual((module / "models" / "a.py").read_text(), LEGACY_SOURCE)
        self.assertTrue([i for i in report.issues if i.category == "AI Error" and "authorization_missing" in i.message])

    def test_partial_authorization_missing_evidence_category_sends_nothing(self):
        # An eligible rule always carries evidence_excerpt; a grant without it must block the request.
        state, _report, module = self.run_pass(authorizations={"alpha": ["source_python"]})
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(state["ai_usage"]["provider_calls"], 0)
        self.assertEqual((module / "models" / "a.py").read_text(), LEGACY_SOURCE)

    def test_kill_switch_sends_nothing_even_when_authorized(self):
        state, _report, module = self.run_pass(authorizations={"alpha": ["evidence_excerpt", "source_python"]},
                                               kill=True)
        self.assertEqual(len(self.gateway_calls), 1)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(state["ai_usage"]["provider_calls"], 0)
        self.assertEqual((module / "models" / "a.py").read_text(), LEGACY_SOURCE)

    def test_ineligible_rule_makes_no_gateway_call(self):
        metas = {"toy.review": RuleMeta("toy.review", ai_eligible=False, has_fix=False, evidence=h.EVIDENCE,
                                        review_required=True)}
        state, _report, module = self.run_pass(authorizations={"alpha": ["evidence_excerpt", "source_python"]},
                                               metas=metas)
        self.assertEqual(self.gateway_calls, [])
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(state["ai_usage"]["requests"], 0)
        self.assertEqual((module / "models" / "a.py").read_text(), LEGACY_SOURCE)


if __name__ == "__main__":
    unittest.main()
