"""TST-007-001 (REQ-AI-001): provider registry, contract-version check, shared provider checks."""

import unittest

from tests.unit.ai import _helpers as h
from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.ai.providers.fake import FakeProvider
from odooflux.ai.providers.registry import ProviderContractError, ProviderRegistry
from odooflux.ai.providers.types import (
    AIRequest, AIResponse, ERROR_KINDS, ModelDescriptor, RESPONSE_SCHEMA, Usage, UsageRecord)


class _OldProvider:
    name = "old"
    contract_version = CONTRACT_VERSION + 1

    def models(self): return []
    def complete(self, req): return AIResponse()
    def count_tokens(self, text, model): return (0, True)
    def supports(self): return set()


def fake() -> FakeProvider:
    return FakeProvider(h.script("mixed"), models=[ModelDescriptor(provider="fake", id="fake-model",
                                                                    context_window=1000, max_output=100)])


def request(text="hello") -> AIRequest:
    return AIRequest(request_id="r1", model="fake-model", system="sys", messages=[{"role": "user", "content": text}],
                     response_schema=RESPONSE_SCHEMA, max_output_tokens=100, budget_ref="job", cache_key="k",
                     region={"path": "a.py", "span": [0, 1], "kind": "function"}, provider="fake")


class RegistryTests(unittest.TestCase):
    def test_load_success(self):
        reg = ProviderRegistry()
        reg.register(fake())
        self.assertIs(reg.get("fake").name, "fake")
        self.assertEqual(reg.names(), ["fake"])

    def test_contract_version_mismatch_has_specific_code(self):
        reg = ProviderRegistry()
        with self.assertRaises(ProviderContractError) as cm:
            reg.register(_OldProvider())
        self.assertEqual(cm.exception.code, "contract_version_mismatch")
        self.assertEqual(reg.names(), [])

    def test_mismatch_is_reported_and_run_continues_without_ai(self):
        reg = ProviderRegistry()
        self.assertEqual(reg.try_register(_OldProvider()), "contract_version_mismatch")
        self.assertIsNone(reg.try_register(fake()))

    def test_unknown_and_duplicate(self):
        reg = ProviderRegistry()
        reg.register(fake())
        with self.assertRaises(ProviderContractError) as cm:
            reg.register(fake())
        self.assertEqual(cm.exception.code, "duplicate_provider")
        with self.assertRaises(ProviderContractError) as cm:
            reg.get("nope")
        self.assertEqual(cm.exception.code, "unknown_provider")


class TypeTests(unittest.TestCase):
    def test_request_response_usage_fields(self):
        req = request()
        for f in ("request_id", "model", "system", "messages", "response_schema", "max_output_tokens",
                  "budget_ref", "cache_key", "region", "provider", "data_categories"):
            self.assertTrue(hasattr(req, f), f)
        resp = AIResponse()
        for f in ("text", "parsed", "usage", "stop_reason", "error_kind", "cost"):
            self.assertTrue(hasattr(resp, f), f)
        self.assertEqual((resp.usage.input, resp.usage.output, resp.usage.cached, resp.usage.estimated),
                         (0, 0, 0, False))
        self.assertEqual(sorted(RESPONSE_SCHEMA["properties"]), ["cannot_fix", "notes", "replacement"])
        self.assertIn("auth", ERROR_KINDS)
        self.assertIn("authorization_missing", ERROR_KINDS)

    def test_usage_record_fields(self):
        rec = UsageRecord(request_id="r", provider="p", model="m", input_tokens=1, output_tokens=2,
                          cached_tokens=0, estimated=False, cost=None, outcome="accepted")
        self.assertEqual(rec.finding_ids, ())


class SharedProviderChecks(unittest.TestCase):
    """The same checks run against every shipped adapter in test_gateway_providers."""

    def test_fake_provider_conforms(self):
        p = fake()
        self.assertEqual(p.contract_version, CONTRACT_VERSION)
        self.assertEqual([m.id for m in p.models()], ["fake-model"])
        self.assertIsInstance(p.supports(), set)
        n, estimated = p.count_tokens("abcdefgh", "fake-model")
        self.assertEqual((n, estimated), (2, True))
        resp = p.complete(request("nothing matches this"))
        self.assertEqual(resp.stop_reason, "error")  # never raises
        self.assertIn(resp.error_kind, ERROR_KINDS)


if __name__ == "__main__":
    unittest.main()
