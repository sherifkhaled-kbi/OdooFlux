"""TST-007-024 (FR-015, FR-016): shared adapter checks (timeouts, bounded retries, error mapping, usage) for
Anthropic, OpenAI, DeepSeek, Z.ai and a local endpoint, against recorded responses. Live variants are opt-in."""

import json
import unittest

from tests.unit.ai import _helpers as h
from tests.unit.ai._gateway_support import (
    GOOD_JSON, RecordingTransport, config_for, http, make_request, ok_anthropic, ok_openai)
from odooflux.ai.gateway import build_gateway
from odooflux.ai.providers.catalog import load_catalog
from odooflux.ai.providers.transport import TransportResult

KEY = "k-contract-canary-123456"
MODEL_DOC = {"context_window": 8000, "max_output": 500, "structured_output": True,
             "pricing": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}
USER_CATALOG = {"schema": "odooflux.ai-catalog/1", "providers": {
    "anthropic": {"models": [dict(MODEL_DOC, id="t-model")]},
    "openai": {"models": [dict(MODEL_DOC, id="t-model")]},
    "deepseek": {"models": [dict(MODEL_DOC, id="t-model")]},
    "zai": {"models": [dict(MODEL_DOC, id="t-model")]},
    "local": {"endpoint": "http://127.0.0.1:9/v1", "models": [dict(MODEL_DOC, id="t-model", pricing=None)]},
}}
CATALOG = load_catalog(extra=[USER_CATALOG])
ENVS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
        "zai": "ZAI_API_KEY", "local": None}
CASES = ("anthropic", "openai", "deepseek", "zai", "local")
GRANT = ["source_python"]


def ok(provider, content, **kw):
    return (ok_anthropic if provider == "anthropic" else ok_openai)(content, **{
        k: v for k, v in kw.items()})


def build(provider, results, *, retries=2, raises=None, timeout=7.0, sleeps=None):
    transport = RecordingTransport(results, raises=raises)
    env = {ENVS[provider]: KEY} if ENVS[provider] else {}
    gw = build_gateway(config_for(provider, "t-model", grants={provider: GRANT}, retries=retries, timeout=timeout),
                       CATALOG, environ=env, transport_for=lambda n: transport,
                       sleep=(sleeps.append if sleeps is not None else (lambda s: None)))
    return gw, transport


class SharedAdapterChecks:
    """Mixed into one TestCase per provider so each failure names the provider."""

    provider = ""

    def req(self):
        return make_request(self.provider, "t-model", text="x = old()")

    def test_success_maps_text_parsed_and_usage(self):
        usage = ({"inp": 111, "out": 22} if self.provider == "anthropic" else {"prompt": 111, "completion": 22})
        gw, t = build(self.provider, [ok(self.provider, GOOD_JSON, **usage)])
        resp = gw.complete(self.req())
        self.assertEqual((resp.stop_reason, resp.error_kind), ("complete", None))
        self.assertEqual(resp.parsed, {"replacement": "x = 1\n", "notes": "", "cannot_fix": False})
        self.assertEqual((resp.usage.input, resp.usage.output), (111, 22))
        self.assertFalse(resp.usage.estimated)
        self.assertEqual(len(t.calls), 1)

    def test_request_shape_and_timeout(self):
        gw, t = build(self.provider, [ok(self.provider, GOOD_JSON)], timeout=7.0)
        gw.complete(self.req())
        call = t.calls[0]
        self.assertEqual(call["timeout"], 7.0)
        body = json.loads(call["body"])
        self.assertEqual(body["model"], "t-model")
        sent = json.dumps(body)
        self.assertIn("x = old()", sent)
        self.assertIn("system text", sent)
        self.assertNotIn(KEY, sent)
        self.assertNotIn(KEY, call["url"])
        if self.provider == "anthropic":
            self.assertIn("x-api-key", {k.lower() for k in call["headers"]})
            self.assertEqual(body["max_tokens"], 100)
            self.assertEqual(body["system"], "system text")
        elif self.provider != "local":
            self.assertEqual(call["headers"]["Authorization"], f"Bearer {KEY}")
            self.assertEqual(body["messages"][0], {"role": "system", "content": "system text"})
        else:
            self.assertNotIn("Authorization", call["headers"])  # a local endpoint needs no credential
        self.assertEqual(call["headers"]["Content-Type"], "application/json")

    def test_truncation_is_reported_as_max_tokens(self):
        kw = {"stop": "max_tokens"} if self.provider == "anthropic" else {"finish": "length"}
        gw, _ = build(self.provider, [ok(self.provider, '{"replacement": "x', **kw)])
        resp = gw.complete(self.req())
        self.assertEqual(resp.stop_reason, "max_tokens")

    def test_error_mapping_without_retry(self):
        for status, kind in ((401, "auth"), (403, "auth"), (400, "invalid_request"), (404, "invalid_request")):
            gw, t = build(self.provider, [http(status)], retries=3)
            resp = gw.complete(self.req())
            self.assertEqual((resp.stop_reason, resp.error_kind), ("error", kind), status)
            self.assertEqual(len(t.calls), 1, status)  # never retried

    def test_retries_are_bounded_and_backed_off(self):
        sleeps = []
        gw, t = build(self.provider, [http(429)], retries=2, sleeps=sleeps)
        resp = gw.complete(self.req())
        self.assertEqual(resp.error_kind, "rate_limit")
        self.assertEqual(len(t.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(resp.attempts, 3)

    def test_transient_then_success(self):
        gw, t = build(self.provider, [http(503), ok(self.provider, GOOD_JSON)], retries=2)
        resp = gw.complete(self.req())
        self.assertEqual(resp.stop_reason, "complete")
        self.assertEqual(len(t.calls), 2)

    def test_timeout_and_connection_failures_are_transient(self):
        for error in ("timeout", "connection"):
            gw, t = build(self.provider, [TransportResult(0, b"", error)], retries=1)
            resp = gw.complete(self.req())
            self.assertEqual(resp.error_kind, "transient", error)
            self.assertEqual(len(t.calls), 2)

    def test_malformed_body_is_an_error_not_an_exception(self):
        gw, _ = build(self.provider, [TransportResult(200, b"<html>not json</html>")], retries=0)
        resp = gw.complete(self.req())
        self.assertEqual((resp.stop_reason, resp.error_kind), ("error", "unknown"))

    def test_non_json_model_text_has_no_parsed_payload(self):
        gw, _ = build(self.provider, [ok(self.provider, "I cannot help with that.")])
        resp = gw.complete(self.req())
        self.assertEqual(resp.stop_reason, "complete")
        self.assertIsNone(resp.parsed)

    def test_fenced_json_is_accepted(self):
        gw, _ = build(self.provider, [ok(self.provider, "```json\n" + GOOD_JSON + "\n```")])
        self.assertIsNotNone(gw.complete(self.req()).parsed)

    def test_provider_exception_is_contained(self):
        gw, _ = build(self.provider, [], raises=RuntimeError("socket exploded"), retries=0)
        resp = gw.complete(self.req())
        self.assertEqual((resp.stop_reason, resp.error_kind), ("error", "unknown"))

    def test_count_tokens_uses_the_documented_heuristic(self):
        gw, _ = build(self.provider, [ok(self.provider, GOOD_JSON)])
        n, estimated = gw.provider.count_tokens("abcdefgh", "t-model")
        self.assertEqual((n, estimated), (2, True))
        self.assertIsInstance(gw.provider.supports(), set)
        self.assertEqual([m.id for m in gw.provider.models()], ["t-model"])


def _make(provider):
    return type(f"{provider.title()}AdapterTests", (SharedAdapterChecks, unittest.TestCase), {"provider": provider})


for _p in CASES:
    globals()[f"{_p.title()}AdapterTests"] = _make(_p)


class AdapterSpecificTests(unittest.TestCase):
    def test_cached_tokens_are_separate_from_input(self):
        gw, _ = build("openai", [ok_openai(GOOD_JSON, prompt=300, completion=10, cached=200)])
        resp = gw.complete(make_request("openai", "t-model"))
        self.assertEqual((resp.usage.input, resp.usage.cached, resp.usage.output), (100, 200, 10))
        gw, _ = build("anthropic", [ok_anthropic(GOOD_JSON, inp=100, out=10, cache_read=50)])
        resp = gw.complete(make_request("anthropic", "t-model"))
        self.assertEqual((resp.usage.input, resp.usage.cached), (100, 50))

    def test_deepseek_cache_hit_tokens_are_mapped(self):
        body = {"choices": [{"message": {"content": GOOD_JSON}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 10, "prompt_cache_hit_tokens": 120}}
        gw, _ = build("deepseek", [TransportResult(200, json.dumps(body).encode())])
        resp = gw.complete(make_request("deepseek", "t-model"))
        self.assertEqual((resp.usage.input, resp.usage.cached), (180, 120))

    def test_usage_missing_from_the_body_is_estimated_and_flagged(self):
        body = {"choices": [{"message": {"content": GOOD_JSON}, "finish_reason": "stop"}]}
        gw, _ = build("local", [TransportResult(200, json.dumps(body).encode())])
        resp = gw.complete(make_request("local", "t-model"))
        self.assertTrue(resp.usage.estimated)
        self.assertGreater(resp.usage.input, 0)

    def test_endpoints_come_from_configuration(self):
        for provider in ("openai", "deepseek", "zai", "local"):
            gw, t = build(provider, [ok_openai(GOOD_JSON)])
            gw.complete(make_request(provider, "t-model"))
            expected = CATALOG.provider(provider).endpoint.rstrip("/")
            self.assertTrue(t.calls[0]["url"].startswith(expected), provider)
            self.assertTrue(t.calls[0]["url"].endswith("/chat/completions"), provider)
        gw, t = build("anthropic", [ok_anthropic(GOOD_JSON)])
        gw.complete(make_request("anthropic", "t-model"))
        self.assertEqual(t.calls[0]["url"], CATALOG.provider("anthropic").endpoint)

    def test_structured_output_mode_only_when_the_model_declares_it(self):
        cat = load_catalog(extra=[h.test_catalog()])
        for model, expect in (("m-one", True), ("m-nopricing", False)):
            t = RecordingTransport([ok_openai(GOOD_JSON)])
            gw = build_gateway(config_for("alpha", model, grants={"alpha": GRANT}), cat, environ={"ALPHA_KEY": KEY},
                               transport_for=lambda n: t)
            gw.complete(make_request("alpha", model))
            self.assertEqual("response_format" in json.loads(t.calls[0]["body"]), expect, model)

    def test_every_first_class_provider_resolves_to_an_adapter(self):
        for provider in ("anthropic", "openai", "deepseek", "zai", "local"):
            gw, _ = build(provider, [ok(provider, GOOD_JSON)])
            self.assertEqual(gw.provider_name, provider)
            self.assertEqual(gw.provider.contract_version, 1)

    def test_missing_credential_for_an_external_provider_is_an_auth_error_without_a_call(self):
        t = RecordingTransport([ok_openai(GOOD_JSON)])
        gw = build_gateway(config_for("openai", "t-model", grants={"openai": GRANT}), CATALOG, environ={},
                           transport_for=lambda n: t)
        resp = gw.complete(make_request("openai", "t-model"))
        self.assertEqual((resp.error_kind, resp.detail), ("auth", "credential_missing"))
        self.assertEqual(t.calls, [])


if __name__ == "__main__":
    unittest.main()
