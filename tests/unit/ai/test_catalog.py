"""TST-007-018 (FR-018): the model catalog is configuration; unknown models fail; nothing is hardcoded."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from . import _helpers as h
from odooflux.ai.providers.catalog import CatalogError, load_catalog

SRC_AI = h.SRC / "odooflux" / "ai"
MODEL_NAMES = re.compile(r"(?i)\b(gpt-?\d\w*|claude-[\w.\-]+|deepseek-[a-z]\w*|glm-?\d[\w.\-]*|gemini-\d\S*|llama-?\d\S*|o[134]-mini)\b")
PRICE_LITERAL = re.compile(r"(?i)(\$\s?\d|per_mtok\"?\s*[:=]\s*\d)")
LEGACY = {"providers/legacy_anthropic.py"}  # the frozen P0 integration; replaced by this feature, not extended


class CatalogTests(unittest.TestCase):
    def test_packaged_catalog_lists_the_first_class_providers_without_models_or_prices(self):
        cat = load_catalog()
        for name in ("anthropic", "openai", "deepseek", "zai"):
            entry = cat.provider(name)
            self.assertEqual(entry.type, "external", name)
            self.assertEqual(entry.models, {}, name)  # model ids and prices are the owner's configuration
            self.assertTrue(entry.endpoint.startswith("https://"), name)
        self.assertEqual(cat.provider("anthropic").adapter, "anthropic")
        for name in ("openai", "deepseek", "zai"):
            self.assertEqual(cat.provider(name).adapter, "openai_compatible")
        self.assertEqual(cat.provider("local").type, "local")

    def test_user_catalog_adds_models_with_capabilities(self):
        cat = load_catalog(extra=[h.test_catalog()])
        entry, model = cat.resolve("alpha", "m-one")
        self.assertEqual((model.provider, model.id, model.context_window, model.max_output), ("alpha", "m-one", 8000, 1000))
        self.assertTrue(model.structured_output)
        self.assertFalse(model.tool_calling)
        self.assertEqual(model.pricing, {"input_per_mtok": 1.0, "output_per_mtok": 2.0})
        _, nopricing = cat.resolve("alpha", "m-nopricing")
        self.assertIsNone(nopricing.pricing)  # absent -> cost null
        self.assertFalse(nopricing.structured_output)  # capabilities are per model

    def test_uncatalogued_model_fails_with_code(self):
        cat = load_catalog(extra=[h.test_catalog()])
        with self.assertRaises(CatalogError) as cm:
            cat.resolve("alpha", "not-a-model")
        self.assertEqual(cm.exception.code, "model_not_in_catalog")
        with self.assertRaises(CatalogError) as cm:
            cat.resolve("openai", "anything")  # packaged provider with no models configured
        self.assertEqual(cm.exception.code, "model_not_in_catalog")

    def test_unknown_provider(self):
        with self.assertRaises(CatalogError) as cm:
            load_catalog().resolve("nope", "x")
        self.assertEqual(cm.exception.code, "unknown_provider")

    def test_file_catalog_overrides_and_merges_models(self):
        tmp = Path(tempfile.mkdtemp()) / "c.json"
        tmp.write_text(json.dumps({"schema": "odooflux.ai-catalog/1", "providers": {
            "openai": {"models": [{"id": "x-1", "context_window": 10, "max_output": 5}]}}}))
        cat = load_catalog(paths=[tmp])
        self.assertIn("x-1", cat.provider("openai").models)
        self.assertEqual(cat.provider("openai").adapter, "openai_compatible")  # untouched fields remain

    def test_endpoint_override_for_external_must_be_https(self):
        cat = load_catalog(extra=[h.test_catalog()])
        with self.assertRaises(CatalogError) as cm:
            cat.resolve("alpha", "m-one", endpoint="http://insecure.example/v1")
        self.assertEqual(cm.exception.code, "endpoint_not_https")
        entry, _ = cat.resolve("alpha", "m-one", endpoint="https://proxy.example/v1")
        self.assertEqual(entry.endpoint, "https://proxy.example/v1")

    def test_local_endpoint_may_be_http_but_must_be_configured(self):
        cat = load_catalog(extra=[h.test_catalog()])
        entry, _ = cat.resolve("loc", "l-one")
        self.assertTrue(entry.endpoint.startswith("http://"))
        with self.assertRaises(CatalogError) as cm:
            load_catalog().resolve("local", "x", endpoint="")
        self.assertIn(cm.exception.code, ("endpoint_required", "model_not_in_catalog"))

    def test_invalid_catalogs_are_reported(self):
        bad = [{"schema": "other/1", "providers": {}},
               {"schema": "odooflux.ai-catalog/1", "providers": {"p": {"type": "weird"}}},
               {"schema": "odooflux.ai-catalog/1", "providers": {"p": {"type": "external", "adapter": "openai_compatible",
                                                                       "models": [{"id": "m", "context_window": "big"}]}}},
               {"schema": "odooflux.ai-catalog/1", "providers": {"p": {"type": "external", "adapter": "nope"}}}]
        for doc in bad:
            with self.assertRaises(CatalogError) as cm:
                load_catalog(extra=[doc])
            self.assertEqual(cm.exception.code, "catalog_invalid", doc)

    def test_no_model_names_or_prices_in_source(self):
        offenders = []
        for file in sorted(SRC_AI.rglob("*")):
            if not file.is_file() or file.suffix not in (".py", ".json", ".txt"):
                continue
            rel = file.relative_to(SRC_AI).as_posix()
            if rel in LEGACY:
                continue
            body = file.read_text(encoding="utf-8")
            for pattern in (MODEL_NAMES, PRICE_LITERAL):
                for m in pattern.finditer(body):
                    offenders.append(f"{rel}: {m.group(0)}")
        self.assertEqual(offenders, [])

    def test_source_scan_pattern_detects_a_planted_name(self):
        self.assertTrue(MODEL_NAMES.search('MODEL = "gpt-4o"'))
        self.assertTrue(MODEL_NAMES.search("claude-sonnet"))
        self.assertTrue(PRICE_LITERAL.search("cost = '$3 per mtok'"))


if __name__ == "__main__":
    unittest.main()
