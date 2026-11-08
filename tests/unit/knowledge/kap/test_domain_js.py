"""TST-011-051 (REQ-KAP-011, REQ-KAP-004): JS/OWL extractor with the lazy optional tree-sitter adapter.

Without the adapter every `.js` file ends UNSUPPORTED with NO_JS_ADAPTER: never silently skipped, never a crash.
The adapter is simulated absent by making its lazy imports fail (`sys.modules` entries set to None). The structural
test runs only when the optional `js` extra happens to be installed.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.extract.domains import js_owl
from odooflux.parsers.javascript import treesitter_adapter as ts
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

JS_16 = '/** @odoo-module **/\n\nexport const DemoWidget = {\n    name: "demo_widget",\n};\n'
JS_17 = JS_16 + '\nexport const DemoBadge = {\n    name: "demo_badge",\n};\n'
PATH = "addons/sale_demo/static/src/js/demo_widget.js"
HAVE_ADAPTER = ts.available()


def _adapter_absent():
    """The lazy imports of the tree-sitter packages fail, as if the js extra were not installed."""
    stack = mock.patch.dict(sys.modules, {"tree_sitter": None, "tree_sitter_javascript": None})
    cache = mock.patch.object(ts, "_parser", None)
    return _Both(stack, cache)


class _Both:
    def __init__(self, *managers):
        self._managers = managers

    def __enter__(self):
        for m in self._managers:
            m.__enter__()
        return self

    def __exit__(self, *exc):
        for m in reversed(self._managers):
            m.__exit__(*exc)
        return False


class JsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "objects")

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, name, files):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        return build_snapshot(root, "src", "r1", self.store, created_at="2026-01-01T00:00:00Z")


class TestWithoutAdapter(JsCase):
    def test_without_adapter_unsupported(self):
        before = self.snapshot("a", {})
        after = self.snapshot("b", {PATH: JS_17})
        with _adapter_absent():
            result = d.extract_pair(before, after, None, js_owl.EXTRACTORS, store=self.store, step="01-02", toolkit=TOOLKIT)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("UNSUPPORTED", "NO_JS_ADAPTER"))

    def test_disable_env_has_same_outcome(self):
        before = self.snapshot("a", {PATH: JS_16})
        after = self.snapshot("b", {PATH: JS_17})
        with mock.patch.dict(os.environ, {"ODOOFLUX_DISABLE_JS_ADAPTER": "1"}):
            result = d.extract_pair(before, after, None, js_owl.EXTRACTORS, store=self.store, step="01-02", toolkit=TOOLKIT)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("UNSUPPORTED", "NO_JS_ADAPTER"))

    def test_handles_is_false_without_adapter(self):
        with _adapter_absent():
            self.assertFalse(js_owl.JsOwlExtractor().handles(PATH, TOOLKIT))

    def test_only_js_files_are_handled(self):
        self.assertFalse(js_owl.JsOwlExtractor().handles("addons/x/models/a.py", TOOLKIT))

    def test_facts_without_adapter_are_unsupported_not_a_crash(self):
        with _adapter_absent():
            with self.assertRaises(d.Unsupported) as ctx:
                js_owl.JsOwlExtractor().facts(JS_17, PATH, TOOLKIT)
        self.assertIn("NO_JS_ADAPTER", ctx.exception.detail)

    def test_changed_js_without_adapter_has_unknown_draft(self):
        before = self.snapshot("a", {PATH: JS_16})
        after = self.snapshot("b", {PATH: JS_17})
        with _adapter_absent():
            result = d.extract_pair(before, after, None, d.default_registry(), store=self.store, step="01-02", toolkit=TOOLKIT)
        unknown = [c for c in result.drafts if c["class"] == "UNKNOWN"]
        self.assertEqual([c["subject_key"] for c in unknown], [PATH])
        self.assertEqual(unknown[0]["domain"], "js_owl")
        self.assertIn("NO_JS_ADAPTER", unknown[0]["detail"]["detail"])
        self.assertIn("changed on: from,to", unknown[0]["detail"]["detail"])

    def test_unchanged_js_without_adapter_has_no_record(self):
        before = self.snapshot("a", {PATH: JS_17})
        after = self.snapshot("b", {PATH: JS_17, "addons/sale_demo/models/a.py": "x = 1\n"})
        with _adapter_absent():
            result = d.extract_pair(before, after, None, d.default_registry(), store=self.store, step="01-02", toolkit=TOOLKIT)
        self.assertNotIn(PATH, {f["path"] for f in result.accounting["files"]})
        self.assertNotIn(PATH, {c["subject_key"] for c in result.drafts})


@unittest.skipUnless(HAVE_ADAPTER, "the optional js extra (tree-sitter) is not installed")
class TestWithAdapter(JsCase):
    def test_js_structural_symbols_golden(self):
        facts = js_owl.JsOwlExtractor().facts(JS_17, PATH, TOOLKIT)
        symbols = sorted((f["kind"], f["subject_key"]) for f in facts)
        self.assertEqual(symbols, [("export", "sale_demo.DemoBadge"), ("export", "sale_demo.DemoWidget")])

    def test_added_export_is_detected(self):
        before = self.snapshot("a", {PATH: JS_16})
        after = self.snapshot("b", {PATH: JS_17})
        result = d.extract_pair(before, after, None, js_owl.EXTRACTORS, store=self.store, step="01-02", toolkit=TOOLKIT)
        added = [c for c in result.drafts if c["class"] == "ADDED"]
        self.assertEqual([c["subject_key"] for c in added], ["sale_demo.DemoBadge"])

    def test_syntax_error_is_failed(self):
        before = self.snapshot("a", {PATH: JS_16})
        after = self.snapshot("b", {PATH: "export const = ;\n"})
        result = d.extract_pair(before, after, None, js_owl.EXTRACTORS, store=self.store, step="01-02", toolkit=TOOLKIT)
        state = result.accounting["files"][0]
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))


if __name__ == "__main__":
    unittest.main()
