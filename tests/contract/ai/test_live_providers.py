"""TST-007-015 (REQ-AI-001): opt-in live contract checks. Skipped unless ODOOFLUX_AI_TESTS=1 and credentials exist.

Set ODOOFLUX_AI_TESTS=1 plus, per provider, the key variable and ODOOFLUX_AI_<PROVIDER>_MODEL (a model id that is
in YOUR catalog; nothing here names a model). Local: ODOOFLUX_AI_LOCAL_ENDPOINT and ODOOFLUX_AI_LOCAL_MODEL.
A live run sends only a trivial synthetic prompt, never customer code, and costs a few tokens.
"""

import os
import unittest

from tests.unit.ai import _helpers as h  # noqa: F401  (puts src/ on sys.path)
from odooflux.ai.gateway import GatewayConfig, build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.ai.providers.types import AIRequest, RESPONSE_SCHEMA

LIVE = os.environ.get("ODOOFLUX_AI_TESTS") == "1"
PROVIDERS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
             "zai": "ZAI_API_KEY", "local": None}


def live_gateway(provider):
    model = os.environ.get(f"ODOOFLUX_AI_{provider.upper()}_MODEL", "")
    key = PROVIDERS[provider]
    if not model:
        raise unittest.SkipTest(f"set ODOOFLUX_AI_{provider.upper()}_MODEL")
    if key and not os.environ.get(key):
        raise unittest.SkipTest(f"set {key}")
    extra = {"schema": "odooflux.ai-catalog/1", "providers": {provider: {"models": [
        {"id": model, "context_window": 8000, "max_output": 256, "structured_output": False}]}}}
    if provider == "local":
        endpoint = os.environ.get("ODOOFLUX_AI_LOCAL_ENDPOINT", "")
        if not endpoint:
            raise unittest.SkipTest("set ODOOFLUX_AI_LOCAL_ENDPOINT")
        extra["providers"]["local"]["endpoint"] = endpoint
    cfg = GatewayConfig(provider=provider, model=model, grants={provider: ["source_python"]}, max_retries=1,
                        timeout_s=60.0)
    return build_gateway(cfg, load_catalog(extra=[extra]), environ=dict(os.environ)), model


def request(provider, model):
    return AIRequest(request_id="live-1", model=model, system="Reply with the JSON object requested.",
                     messages=[{"role": "user", "content": 'Reply exactly with {"replacement": "ok", "notes": "", "cannot_fix": false}'}],
                     response_schema=RESPONSE_SCHEMA, max_output_tokens=64, budget_ref="job", cache_key="",
                     region={"path": "x.py", "span": [0, 1], "kind": "statement"}, provider=provider,
                     data_categories=("source_python",))


def _make(provider):
    @unittest.skipUnless(LIVE, "opt-in: set ODOOFLUX_AI_TESTS=1 (calls a real provider; may cost tokens)")
    class Live(unittest.TestCase):
        def test_shared_contract_checks(self):
            gw, model = live_gateway(provider)
            resp = gw.complete(request(provider, model))
            self.assertIn(resp.stop_reason, ("complete", "max_tokens", "error"))
            self.assertEqual(resp.stop_reason, "complete", f"{resp.error_kind}: {resp.detail}")
            self.assertGreater(resp.usage.input + resp.usage.cached, 0)
            self.assertGreater(resp.usage.output, 0)
            self.assertIsInstance(gw.provider.supports(), set)

        def test_bad_credential_is_an_auth_error_not_an_exception(self):
            if PROVIDERS[provider] is None:
                self.skipTest("local endpoints need no credential")
            gw, model = live_gateway(provider)
            env = dict(os.environ, **{PROVIDERS[provider]: "invalid-key-for-contract-test"})
            bad = build_gateway(gw.config, gw.catalog, environ=env)
            resp = bad.complete(request(provider, model))
            self.assertEqual((resp.stop_reason, resp.error_kind), ("error", "auth"))
    Live.__name__ = f"Live{provider.title()}Tests"
    return Live


for _p in PROVIDERS:
    globals()[f"Live{_p.title()}Tests"] = _make(_p)

if __name__ == "__main__":
    unittest.main()
