"""TST-006-011 (REQ-PY-002): FIX_ENABLED rules 18-19.python.route-type-json and 18-19.python.env-shortcuts-deprecated.

- ``route-type-json`` (EV-007, EV-115): ``type='json'`` on ``http.route`` becomes ``type='jsonrpc'``. Only a plain
  literal equal to ``json`` is rewritten; other callees, variables and other route types are left alone.
- ``env-shortcuts-deprecated`` (EV-003, EV-209, EV-304): ``self._cr``, ``self._uid`` and ``self._context`` reads become
  ``self.env.cr``, ``self.env.uid`` and ``self.env.context``. Writes and other receivers are not rewritten (and are
  not claimed as fixed).

Fixers keep everything else byte for byte, leave output that compiles, and produce no edits on a second application.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

ROUTE = "18-19.python.route-type-json"
ENV = "18-19.python.env-shortcuts-deprecated"
ROUTE_PARAMS = {"callee": "http.route", "keyword": "type", "value": "json", "new_value": "jsonrpc"}
ENV_PARAMS = {"mapping": {"self._cr": "self.env.cr", "self._uid": "self.env.uid",
                          "self._context": "self.env.context"}}
PATH = "c.py"


def ctx(rule_id):
    return RuleContext(rule_id=rule_id, severity="WARNING", step="18-19", message="m", suggestion="s")


def fix_route(src):
    document = Document.from_text(PATH, src)
    result = apply_edits(document, pg.rewrite_keyword_value(document, ctx(ROUTE), **ROUTE_PARAMS), precedence=[ROUTE])
    second = pg.rewrite_keyword_value(Document.from_text(PATH, result.text), ctx(ROUTE), **ROUTE_PARAMS)
    return result, second


def fix_env(src):
    document = Document.from_text(PATH, src)
    result = apply_edits(document, pg.rewrite_attribute_map(document, ctx(ENV), **ENV_PARAMS), precedence=[ENV])
    second = pg.rewrite_attribute_map(Document.from_text(PATH, result.text), ctx(ENV), **ENV_PARAMS)
    return result, second


class RouteTypePositiveTests(unittest.TestCase):
    def test_http_route_json_is_rewritten(self):
        result, second = fix_route("@http.route('/x', type='json', auth='user')\ndef x():\n    pass\n")
        self.assertEqual(result.text, "@http.route('/x', type='jsonrpc', auth='user')\ndef x():\n    pass\n")
        self.assertEqual(second, [])

    def test_double_quotes_are_kept(self):
        result, _ = fix_route('@http.route("/x", type="json")\ndef x():\n    pass\n')
        self.assertEqual(result.text, '@http.route("/x", type="jsonrpc")\ndef x():\n    pass\n')

    def test_route_imported_by_name_is_rewritten(self):
        result, _ = fix_route("from odoo.http import route\n@route('/x', type='json')\ndef x():\n    pass\n")
        self.assertEqual(result.text, "from odoo.http import route\n@route('/x', type='jsonrpc')\ndef x():\n    pass\n")

    def test_detector_reports_the_literal(self):
        document = Document.from_text(PATH, "@http.route('/x', type='json')\ndef x():\n    pass\n")
        findings = pg.flag_keyword_value(document, ctx(ROUTE), callee="http.route", keyword="type", value="json")
        self.assertEqual([f.line for f in findings], [1])


class RouteTypeNegativeTests(unittest.TestCase):
    def assertUnchanged(self, src):
        result, second = fix_route(src)
        self.assertEqual(result.text, src)
        self.assertEqual(second, [])

    def test_http_type_is_untouched(self):
        self.assertUnchanged("@http.route('/x', type='http')\ndef x():\n    pass\n")

    def test_jsonrpc_type_is_untouched(self):
        self.assertUnchanged("@http.route('/x', type='jsonrpc')\ndef x():\n    pass\n")

    def test_other_callee_is_untouched(self):
        self.assertUnchanged("@other.route('/x', type='json')\ndef x():\n    pass\n")

    def test_variable_value_is_untouched(self):
        self.assertUnchanged("@http.route('/x', type=KIND)\ndef x():\n    pass\n")

    def test_string_literal_is_untouched(self):
        self.assertUnchanged("doc = \"@http.route('/x', type='json')\"\n")


class EnvShortcutPositiveTests(unittest.TestCase):
    def test_cursor_read_is_rewritten(self):
        result, second = fix_env("class A(models.Model):\n    def f(self):\n        self._cr.execute('SELECT 1')\n")
        self.assertEqual(result.text, "class A(models.Model):\n    def f(self):\n        self.env.cr.execute('SELECT 1')\n")
        self.assertEqual(second, [])

    def test_uid_and_context_reads_are_rewritten(self):
        src = "def f(self):\n    u = self._uid\n    c = self._context.get('lang')\n"
        result, second = fix_env(src)
        self.assertEqual(result.text, "def f(self):\n    u = self.env.uid\n    c = self.env.context.get('lang')\n")
        self.assertEqual(second, [])

    def test_detector_reports_each_read(self):
        document = Document.from_text(PATH, "def f(self):\n    self._cr\n    self._uid\n")
        findings = pg.flag_attribute_map(document, ctx(ENV), **ENV_PARAMS)
        self.assertEqual([f.line for f in findings], [2, 3])


class EnvShortcutNegativeTests(unittest.TestCase):
    def assertUnchanged(self, src):
        result, second = fix_env(src)
        self.assertEqual(result.text, src)
        self.assertEqual(second, [])

    def test_env_form_is_untouched(self):
        self.assertUnchanged("def f(self):\n    self.env.cr.commit()\n")

    def test_other_receiver_is_untouched(self):
        self.assertUnchanged("def f(cursor):\n    cursor._cr.execute('x')\n")

    def test_write_is_not_rewritten(self):
        self.assertUnchanged("def f(self):\n    self._context = {}\n")

    def test_string_literal_is_untouched(self):
        self.assertUnchanged("doc = 'self._cr.execute()'\n")

    def test_unrelated_attribute_is_untouched(self):
        self.assertUnchanged("def f(self):\n    return self._name\n")


class FixerRejectsUnsafeParamsTests(unittest.TestCase):
    def test_new_value_with_quote_is_rejected(self):
        document = Document.from_text(PATH, "@http.route('/x', type='json')\n")
        with self.assertRaises(ValueError):
            pg.rewrite_keyword_value(document, ctx(ROUTE), callee="http.route", keyword="type", value="json",
                                     new_value="json'x")


class FixtureCatalogueTests(unittest.TestCase):
    def test_both_entries_bind_at_fix_enabled_with_tests(self):
        rules = {r["id"]: r for r in load_knowledge().rules}
        for rule_id in (ROUTE, ENV):
            with self.subTest(rule=rule_id):
                meta = rules[rule_id]
                bound = bind_rule(meta, BINDABLE_MODULES)
                self.assertEqual(bound.maturity, "FIX_ENABLED")
                self.assertIsNotNone(bound.fixer)
                self.assertFalse(bound.review_required)
                self.assertEqual(meta["tests"], {"positive": "TST-006-011", "negative": "TST-006-011",
                                                 "idempotence": "TST-006-011"})


if __name__ == "__main__":
    unittest.main()
