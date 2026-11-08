"""T032 (quickstart): ODOOFLUX_DISABLE_JS_ADAPTER=1 masks the tree-sitter adapter (detect-only path)."""

import os
import unittest
from unittest import mock

from .. import _setup  # noqa: F401  (src first on sys.path)
from odooflux.parsers.javascript import treesitter_adapter as ad
from odooflux.validation.syntax.javascript import JavaScriptSyntaxValidator


class DisableEnvTests(unittest.TestCase):
    def _loaded(self):
        return mock.patch.object(ad, "_load_parser", return_value=(object(), object()))

    def test_available_when_loadable_and_variable_unset(self):
        with self._loaded(), mock.patch.dict(os.environ):
            os.environ.pop("ODOOFLUX_DISABLE_JS_ADAPTER", None)
            self.assertTrue(ad.available())

    def test_disabled_when_set_even_if_loadable(self):
        with self._loaded() as load, mock.patch.dict(os.environ, {"ODOOFLUX_DISABLE_JS_ADAPTER": "1"}):
            self.assertFalse(ad.available())
            self.assertIsNone(ad.has_errors("const a = 1;"))
            load.assert_not_called()

    def test_zero_or_empty_does_not_disable(self):
        for value in ("", "0"):
            with self._loaded(), mock.patch.dict(os.environ, {"ODOOFLUX_DISABLE_JS_ADAPTER": value}):
                self.assertTrue(ad.available(), value)

    def test_validator_reports_unavailable_when_disabled(self):
        with self._loaded(), mock.patch.dict(os.environ, {"ODOOFLUX_DISABLE_JS_ADAPTER": "1"}):
            result = JavaScriptSyntaxValidator(ad).validate("x.js", "const a = 1;")
        self.assertEqual(result.outcome, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
