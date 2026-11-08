"""TST-007-022 (FR-017, FR-020): the gateway never switches provider on error, block or budget exhaustion."""

import unittest

from tests.unit.ai import _helpers as h
from tests.unit.ai._gateway_support import (
    GOOD_JSON, RecordingTransport, config_for, http, make_request, ok_anthropic, ok_openai)
from odooflux.ai.escalation import Escalator
from odooflux.ai.gateway import build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.ai.usage.budgets import BudgetTree

CATALOG = load_catalog(extra=[h.test_catalog()])
ENV = {"ALPHA_KEY": "k-alpha-1234567", "BETA_KEY": "k-beta-1234567"}
TEXT = "class A:\n    def f_ok(self):\n        return old_api(1)\n"


def two_providers(selected, grants, alpha_results, kill=False, retries=1):
    alpha, beta = RecordingTransport(alpha_results), RecordingTransport([ok_anthropic(GOOD_JSON)])
    transports = {"alpha": alpha, "beta": beta, "loc": RecordingTransport([ok_openai(GOOD_JSON)])}
    model = {"alpha": "m-one", "beta": "b-one"}[selected]
    gw = build_gateway(config_for(selected, model, grants=grants, kill=kill, retries=retries), CATALOG, environ=ENV,
                       transport_for=lambda name: transports[name], sleep=lambda s: None)
    return gw, transports


class NoFallbackTests(unittest.TestCase):
    def test_provider_failure_does_not_reach_another_provider(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python"], "beta": ["source_python"]}, [http(500)])
        resp = gw.complete(make_request("alpha", "m-one"))
        self.assertEqual((resp.stop_reason, resp.error_kind), ("error", "transient"))
        self.assertEqual(len(t["alpha"].calls), 2)  # one try + the configured single retry
        self.assertEqual((t["beta"].calls, t["loc"].calls), ([], []))

    def test_auth_failure_does_not_reach_another_provider(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python"], "beta": ["source_python"]}, [http(401)])
        self.assertEqual(gw.complete(make_request("alpha", "m-one")).error_kind, "auth")
        self.assertEqual((t["beta"].calls, t["loc"].calls), ([], []))

    def test_authorization_block_does_not_redirect(self):
        gw, t = two_providers("alpha", {"beta": ["source_python"]}, [ok_openai(GOOD_JSON)])
        resp = gw.complete(make_request("alpha", "m-one"))
        self.assertEqual(resp.error_kind, "authorization_provider_mismatch")
        self.assertTrue(all(tr.calls == [] for tr in t.values()))  # not even the authorized provider

    def test_kill_switch_block_does_not_redirect_to_local(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python"]}, [ok_openai(GOOD_JSON)], kill=True)
        self.assertEqual(gw.complete(make_request("alpha", "m-one")).error_kind, "transmission_disabled")
        self.assertTrue(all(tr.calls == [] for tr in t.values()))

    def test_request_naming_another_provider_is_refused_not_rerouted(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python"], "beta": ["source_python"]}, [ok_openai(GOOD_JSON)])
        resp = gw.complete(make_request("beta", "b-one"))
        self.assertEqual(resp.stop_reason, "error")
        self.assertTrue(all(tr.calls == [] for tr in t.values()))

    def test_budget_exhaustion_does_not_switch_provider_and_finding_stays_open(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python", "evidence_excerpt"],
                                         "beta": ["source_python", "evidence_excerpt"]}, [ok_openai(GOOD_JSON)])
        esc = Escalator(gw.complete, provider="alpha", model="m-one", step="s", validate=h.python_validate,
                        rescan=h.toy_rescan, budgets=BudgetTree(job_tokens=10), sender_hooks=True)
        result = esc.escalate_file("mod", "m.py", TEXT, h.toy_findings("m.py", TEXT), h.TOY_METAS)
        self.assertEqual(result.outcomes[0].status, "OPEN")
        self.assertEqual(result.outcomes[0].outcome, "skipped:budget_job")
        self.assertTrue(all(tr.calls == [] for tr in t.values()))

    def test_error_leaves_finding_open_with_ai_error_outcome(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python", "evidence_excerpt"],
                                         "beta": ["source_python", "evidence_excerpt"]}, [http(500)], retries=0)
        esc = Escalator(gw.complete, provider="alpha", model="m-one", step="s", validate=h.python_validate,
                        rescan=h.toy_rescan, sender_hooks=True)
        result = esc.escalate_file("mod", "m.py", TEXT, h.toy_findings("m.py", TEXT), h.TOY_METAS)
        self.assertEqual((result.outcomes[0].status, result.outcomes[0].outcome), ("OPEN", "error:transient"))
        self.assertEqual(result.text, TEXT)
        self.assertEqual((t["beta"].calls, t["loc"].calls), ([], []))

    def test_only_the_selected_provider_is_ever_called_on_success(self):
        gw, t = two_providers("alpha", {"alpha": ["source_python"]}, [ok_openai(GOOD_JSON)])
        self.assertEqual(gw.complete(make_request("alpha", "m-one")).stop_reason, "complete")
        self.assertEqual((len(t["alpha"].calls), t["beta"].calls, t["loc"].calls), (1, [], []))

    def test_gateway_source_has_no_fallback_construct(self):
        import re
        body = (h.SRC / "odooflux" / "ai" / "gateway.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?i)fall_?back|secondary|alternate_provider", body.replace("no fallback", "")
                                    .replace("No fallback", "").replace("NO fallback", "")
                                    .replace("no silent fallback", "")))


if __name__ == "__main__":
    unittest.main()
