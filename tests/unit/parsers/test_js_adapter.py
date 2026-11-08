"""TST-005-013 (REQ-JS-001, REQ-JS-004): tree-sitter adapter parse/query/has_errors.

Skipped unless ODOOFLUX_JS_ADAPTER_TESTS=1 (CI job with the ``js`` extra installed).
"""

import os
import unittest

from .. import _setup  # noqa: F401  (src first on sys.path)

ENABLED = os.environ.get("ODOOFLUX_JS_ADAPTER_TESTS") == "1"

GOOD = "const a = 1;\nfunction f(x) { return x + a; }\n"
BAD = "function f( { return ;\n"


@unittest.skipUnless(ENABLED, "set ODOOFLUX_JS_ADAPTER_TESTS=1 (needs the js extra)")
class TreeSitterAdapterTests(unittest.TestCase):
    def setUp(self):
        from odooflux.parsers.javascript import treesitter_adapter as ad
        self.ad = ad
        self.assertTrue(ad.available(), "js extra must be installed when the tests are enabled")

    def test_parse_returns_root_without_errors(self):
        tree = self.ad.parse(GOOD)
        self.assertEqual(tree.root_node.type, "program")
        self.assertFalse(tree.root_node.has_error)

    def test_has_errors(self):
        self.assertIs(self.ad.has_errors(GOOD), False)
        self.assertIs(self.ad.has_errors(BAD), True)

    def test_query_returns_captures(self):
        found = self.ad.query(GOOD, "(function_declaration name: (identifier) @name)")
        self.assertEqual([(n.text.decode(), n.start_point[0]) for n in found["name"]], [("f", 1)])

    def test_query_empty_when_no_match(self):
        self.assertEqual(self.ad.query("const a = 1;", "(function_declaration) @f"), {})

    def test_satisfies_validator_protocol(self):
        from odooflux.validation.syntax.javascript import JavaScriptSyntaxValidator
        validator = JavaScriptSyntaxValidator(adapter=self.ad)
        self.assertEqual(validator.validate("a.js", GOOD).outcome, "PASS")
        self.assertEqual(validator.validate("a.js", BAD).outcome, "FAIL")


class AdapterImportSafetyTests(unittest.TestCase):
    def test_module_imports_and_available_is_bool_without_extra(self):
        from odooflux.parsers.javascript import treesitter_adapter as ad
        self.assertIsInstance(ad.available(), bool)


if __name__ == "__main__":
    unittest.main()
