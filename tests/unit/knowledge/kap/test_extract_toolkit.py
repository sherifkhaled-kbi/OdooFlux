"""REQ-ARC-001, REQ-KAP-011: the extract toolkit and its attachment at the composition root.

The core packages receive document adapters only as a parameter. These tests check the adapters themselves, that the
composition root attaches one, and that a run without one never analyses a parser-bound file (NO_PARSER, or
NO_JS_ADAPTER for `.js`), never crashes and never skips silently. Temporary trees and the real BlobStore are used.
"""

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_registries
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.extract import driver as d
from odooflux.knowledge.candidates.templates import FIXER_PREFIXES, TemplateError
from odooflux.parsers.extract_toolkit import ExtractToolkit, ToolkitUnavailable, detector_table
from odooflux.rules.bindable import BINDABLE_MODULES

FILES_BEFORE = {"addons/sale_demo/models/x.py": "x = 1\n", "addons/sale_demo/views/v.xml": "<odoo/>\n",
                "addons/sale_demo/static/src/js/w.js": "const a = 1;\n"}
FILES_AFTER = {"addons/sale_demo/models/x.py": "x = 2\n", "addons/sale_demo/views/v.xml": "<odoo><x/></odoo>\n",
               "addons/sale_demo/static/src/js/w.js": "const a = 2;\n"}


class ToolkitBehaviour(unittest.TestCase):
    def setUp(self):
        self.kit = ExtractToolkit(detectors=detector_table(BINDABLE_MODULES))

    def test_python_document_has_tree_or_error(self):
        ok = self.kit.python_document("x = 1\n", "a.py")
        self.assertIsNotNone(ok.tree)
        self.assertIsNone(ok.parse_error)
        bad = self.kit.python_document("def broken(:\n", "a.py")
        self.assertIsNone(bad.tree)
        self.assertIn("message", bad.parse_error)

    def test_xml_document_is_span_bearing(self):
        text = '<odoo><record id="v" model="ir.ui.view"/></odoo>'
        doc = self.kit.xml_document(text, path="v.xml")
        self.assertIsNone(doc.parse_error)
        self.assertEqual([e.tag for e in doc.elements], ["odoo", "record"])
        record = doc.elements[1]
        self.assertEqual(record.parent_index, 0)
        self.assertEqual(doc.text[record.span.start:record.span.end], '<record id="v" model="ir.ui.view"/>')
        self.assertIsNotNone(self.kit.xml_document("<odoo>", path="v.xml").parse_error)

    def test_javascript_masked_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {"ODOOFLUX_DISABLE_JS_ADAPTER": "1"}):
            self.assertFalse(self.kit.javascript_available())
            with self.assertRaises(ToolkitUnavailable) as caught:
                self.kit.javascript()
        self.assertEqual(caught.exception.code, "NO_JS_ADAPTER")

    def test_detector_table_is_built_from_the_explicit_modules(self):
        table = detector_table(BINDABLE_MODULES)
        self.assertTrue(table)
        self.assertEqual(table, self.kit.detectors)
        for ref, module in table.items():
            name = ref.partition(":")[2]
            self.assertIs(module, BINDABLE_MODULES[ref.partition(":")[0]])
            self.assertTrue(callable(getattr(module, name)))
            self.assertFalse(name.startswith(("_",) + FIXER_PREFIXES), ref)

    def test_malformed_table_raises_at_construction_naming_the_ref(self):
        good = detector_table(BINDABLE_MODULES)
        ref = next(key for key in good if key.startswith("odooflux.rules.python.generic:"))
        cases = {
            "no colon": ("odooflux.rules.python.generic", good[ref]),
            "value not a module": (ref, "not-a-module"),
            "module name mismatch": (ref, BINDABLE_MODULES["odooflux.rules.xml.generic"]),
            "missing function": ("odooflux.rules.python.generic:no_such_detector", good[ref]),
            "fixer": ("odooflux.rules.python.generic:remove_decorator", good[ref]),
        }
        for label, (bad_ref, value) in cases.items():
            with self.subTest(label), self.assertRaises(TemplateError) as caught:
                ExtractToolkit(detectors={bad_ref: value})
            self.assertIn(bad_ref, str(caught.exception))

    def test_positional_detector_is_refused_at_construction(self):
        module = types.ModuleType(__name__)
        module.positional_detector = positional_detector
        ref = f"{__name__}:positional_detector"
        with self.assertRaises(TemplateError) as caught:
            ExtractToolkit(detectors={ref: module})
        self.assertIn(ref, str(caught.exception))
        self.assertIn("positional", str(caught.exception))


def positional_detector(tree, path, target):
    """A detector whose third parameter is positional: not bindable by keyword, so refused."""
    return tree, path, target

    def test_composition_root_attaches_a_toolkit(self):
        kit = build_registries().extract_toolkit
        self.assertIsInstance(kit, ExtractToolkit)
        self.assertEqual(set(kit.detectors), set(BINDABLE_MODULES))


class RunWithoutToolkit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "blobs")
        self.toolkit = ExtractToolkit(detectors=detector_table(BINDABLE_MODULES))

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, name, files):
        root = self.base / name
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        return build_snapshot(root, "src", "r1", self.store, created_at="2026-01-01T00:00:00Z")

    def run_pair(self, toolkit):
        before, after = self.snapshot("before", FILES_BEFORE), self.snapshot("after", FILES_AFTER)
        return d.extract_pair(before, after, None, d.default_registry(), store=self.store, step="01-02",
                              toolkit=toolkit)

    @staticmethod
    def states(result):
        return {f["path"]: (f["state"], f["reason_code"]) for f in result.accounting["files"]}

    def test_without_toolkit_parser_bound_files_are_unsupported(self):
        states = self.states(self.run_pair(None))
        self.assertEqual(states["addons/sale_demo/models/x.py"], ("UNSUPPORTED", "NO_PARSER"))
        self.assertEqual(states["addons/sale_demo/views/v.xml"], ("UNSUPPORTED", "NO_PARSER"))
        self.assertEqual(states["addons/sale_demo/static/src/js/w.js"], ("UNSUPPORTED", "NO_JS_ADAPTER"))

    def test_without_toolkit_every_changed_file_is_an_unknown_draft(self):
        result = self.run_pair(None)
        unknown = {draft["subject_key"]: draft["detail"]["detail"] for draft in result.drafts}
        self.assertEqual(set(unknown), set(FILES_BEFORE))
        self.assertTrue(unknown["addons/sale_demo/models/x.py"].startswith("NO_PARSER"))
        self.assertTrue(unknown["addons/sale_demo/static/src/js/w.js"].startswith("NO_JS_ADAPTER"))

    def test_with_toolkit_the_python_file_is_analysed(self):
        states = self.states(self.run_pair(self.toolkit))
        self.assertEqual(states["addons/sale_demo/models/x.py"][0], "ANALYZED")



class MissingToolkitIsAUsageError(unittest.TestCase):
    """A parser-requiring command run without the attached toolkit exits 2 (usage) before doing any work."""

    def test_extract_without_registries_is_usage_error(self):
        import contextlib
        import io
        from odooflux.cli import knowledge
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = knowledge.main(["extract", "--from", "a.json", "--to", "b.json", "--step", "01-02",
                                   "--blobs", "blobs", "--out", "out"])
        self.assertEqual(code, 2)
        self.assertIn("document adapters", err.getvalue())

    def test_rule_create_without_registries_is_usage_error(self):
        import contextlib
        import io
        from odooflux.cli import knowledge
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = knowledge.main(["rule", "create", "--path", "nowhere", "--id", "x", "--step", "12-13"])
        self.assertEqual(code, 2)
        self.assertIn("detector table", err.getvalue())


if __name__ == "__main__":
    unittest.main()
