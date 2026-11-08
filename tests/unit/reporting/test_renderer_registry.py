"""T006 (REQ-REP-001, REQ-ARC-006): renderer registry with contract version."""

import json
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import golden


class _Sample:
    key = "sample-csv"
    contract_version = 1

    def render(self, report, **options):
        return "\n".join(m["name"] for m in report["modules"]) + "\n"


class _Old:
    key = "old"
    contract_version = 0

    def render(self, report, **options):
        return ""


class RegistryTests(unittest.TestCase):
    def _registries(self):
        from odooflux.core.contracts.plugins import Registries
        from odooflux.reporting import register_default_renderers
        r = Registries()
        register_default_renderers(r)
        return r

    def test_default_formats_registered(self):
        r = self._registries()
        for key in ("json", "terminal", "html", "sarif", "diff", "diff-index", "legacy-json"):
            self.assertIn(key, r.renderers, key)
            self.assertEqual(r.renderers.get(key).contract_version, 1)

    def test_sample_renderer_registers_without_core_edits(self):
        r = self._registries()
        r.renderers.register(_Sample(), plugin="sample")
        self.assertEqual(r.renderers.get("sample-csv").render(golden("mixed")).splitlines()[0], "kbi_sale_approval")

    def test_mismatched_contract_version_rejected(self):
        from odooflux.core.contracts import PluginContractError
        with self.assertRaises(PluginContractError):
            self._registries().renderers.register(_Old(), plugin="old")

    def test_duplicate_key_rejected(self):
        from odooflux.core.contracts import DuplicateRegistrationError
        r = self._registries()
        with self.assertRaises(DuplicateRegistrationError):
            r.renderers.register(_Sample())
            r.renderers.register(_Sample())

    def test_registered_renderers_render_from_the_model_only(self):
        r = self._registries()
        model = golden("mixed")
        before = json.dumps(model, sort_keys=True)
        for key in ("json", "terminal", "html", "sarif", "legacy-json"):
            out = r.renderers.get(key).render(model)
            self.assertIsInstance(out, str, key)
            self.assertTrue(out, key)
        self.assertEqual(json.dumps(model, sort_keys=True), before, "renderers must not mutate the model")

    def test_core_does_not_import_reporting_adapters(self):
        import odooflux.core.contracts.plugins as plugins
        self.assertNotIn("odooflux.reporting", __import__("pathlib").Path(plugins.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
