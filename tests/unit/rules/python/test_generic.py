"""TST-006-003 (REQ-PY-002, REQ-TRF-003): generic Python detectors and fixers with import-alias resolution.

Fixers must produce text that compiles, must leave everything else byte for byte unchanged, and must
produce no edits on a second application. Detectors report findings and never edit.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext

from ... import _setup  # noqa: F401  (src first on sys.path)

CTX = RuleContext(rule_id="test.python-generic", severity="WARNING", step="17-18",
                  message="generic message", suggestion="generic suggestion")
PATH = "m.py"


def fix(fixer, src, **params):
    """Apply a fixer once, return (result, second-pass edits)."""
    document = Document.from_text(PATH, src)
    result = apply_edits(document, fixer(document, CTX, **params), precedence=[CTX.rule_id])
    second = fixer(Document.from_text(PATH, result.text), CTX, **params)
    return result, second


def detect(detector, src, **params):
    return detector(Document.from_text(PATH, src), CTX, **params)


class KeywordRenameTests(unittest.TestCase):
    def assertRenamed(self, src, expected, **params):
        result, second = fix(pg.rename_keyword, src, **params)
        self.assertEqual(result.rejected, ())
        self.assertTrue(result.preserved_ok)
        self.assertEqual(result.text, expected)
        self.assertEqual(second, [])

    def test_literal_callee_keyword_is_renamed(self):
        self.assertRenamed("x = fields.Char(group_operator='sum')\n",
                           "x = fields.Char(aggregator='sum')\n",
                           callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_from_import_alias_resolves_to_callee(self):
        self.assertRenamed("from odoo import fields as f\nx = f.Float(group_operator='max')\n",
                           "from odoo import fields as f\nx = f.Float(aggregator='max')\n",
                           callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_module_import_alias_resolves_to_callee(self):
        self.assertRenamed("import odoo.fields as F\nx = F.Char(group_operator='sum')\n",
                           "import odoo.fields as F\nx = F.Char(aggregator='sum')\n",
                           callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_other_callee_is_not_renamed(self):
        src = "x = models.Char(group_operator='sum')\n"
        result, second = fix(pg.rename_keyword, src, callee="fields.", keyword="group_operator",
                             new_keyword="aggregator")
        self.assertEqual(result.text, src)
        self.assertEqual(second, [])

    def test_string_literal_is_not_code(self):
        src = "x = \"fields.Char(group_operator='sum')\"\n"
        self.assertEqual(fix(pg.rename_keyword, src, callee="fields.", keyword="group_operator",
                             new_keyword="aggregator")[0].text, src)

    def test_ambiguous_alias_is_not_fixed(self):
        src = "from odoo import fields\nfrom legacy import fields\nx = fields.Char(group_operator='sum')\n"
        result, _ = fix(pg.rename_keyword, src, callee="fields.", keyword="group_operator",
                        new_keyword="aggregator")
        self.assertEqual(result.text, src)

    def test_multiline_call_is_renamed(self):
        self.assertRenamed("x = fields.Char(\n    string='a',\n    group_operator='sum',\n)\n",
                           "x = fields.Char(\n    string='a',\n    aggregator='sum',\n)\n",
                           callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_nested_calls_are_both_renamed(self):
        self.assertRenamed(
            "x = fields.Many2one(comodel_name='a', group_operator=fields.Char(group_operator='x'))\n",
            "x = fields.Many2one(comodel_name='a', aggregator=fields.Char(aggregator='x'))\n",
            callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_non_ascii_before_keyword_keeps_span_exact(self):
        self.assertRenamed("# caf\u00e9\nx = fields.Char(string='\u00e9', group_operator='sum')\n",
                           "# caf\u00e9\nx = fields.Char(string='\u00e9', aggregator='sum')\n",
                           callee="fields.", keyword="group_operator", new_keyword="aggregator")

    def test_bom_and_crlf_are_preserved(self):
        raw = b"\xef\xbb\xbfx = fields.Char(group_operator='sum')\r\ny = 1\r\n"
        document = Document.from_bytes(PATH, raw)
        edits = pg.rename_keyword(document, CTX, callee="fields.", keyword="group_operator",
                                  new_keyword="aggregator")
        result = apply_edits(document, edits, precedence=[CTX.rule_id])
        produced = document.with_text(result.text).encode()
        self.assertEqual(produced, b"\xef\xbb\xbfx = fields.Char(aggregator='sum')\r\ny = 1\r\n")

    def test_double_star_mapping_is_not_renamed(self):
        src = "x = fields.Char(**{'group_operator': 1})\ny = fields.Char(**opts)\n"
        self.assertEqual(fix(pg.rename_keyword, src, callee="fields.", keyword="group_operator",
                             new_keyword="aggregator")[0].text, src)

    def test_non_identifier_new_name_raises(self):
        with self.assertRaises(ValueError):
            pg.rename_keyword(Document.from_text(PATH, "x = f(a=1)\n"), CTX, callee="f", keyword="a",
                              new_keyword="not valid")

    def test_unparsable_source_yields_no_edits(self):
        self.assertEqual(pg.rename_keyword(Document.from_text(PATH, "def (:\n"), CTX, callee="f",
                                           keyword="a", new_keyword="b"), [])


class KeywordRemoveTests(unittest.TestCase):
    def assertRemoved(self, src, expected):
        result, second = fix(pg.remove_keyword, src, callee="fields.", keyword="group_operator")
        self.assertEqual(result.rejected, ())
        self.assertEqual(result.text, expected)
        self.assertEqual(second, [])

    def test_first_keyword_removed_with_its_comma(self):
        self.assertRemoved("x = fields.Char(group_operator='sum', string='x')\n",
                           "x = fields.Char(string='x')\n")

    def test_last_keyword_removed_with_preceding_comma(self):
        self.assertRemoved("x = fields.Char(string='x', group_operator='sum')\n",
                           "x = fields.Char(string='x')\n")

    def test_sole_keyword_removed(self):
        self.assertRemoved("x = fields.Char(group_operator='sum')\n", "x = fields.Char()\n")

    def test_whole_line_keyword_removed(self):
        self.assertRemoved("x = fields.Char(\n    string='a',\n    group_operator='sum',\n)\n",
                           "x = fields.Char(\n    string='a',\n)\n")

    def test_call_without_keyword_yields_no_edits(self):
        src = "x = fields.Char(string='x')\n"
        self.assertEqual(fix(pg.remove_keyword, src, callee="fields.", keyword="group_operator")[0].text, src)

    def test_ambiguous_alias_is_not_fixed(self):
        src = "from odoo import fields\nfrom legacy import fields\nx = fields.Char(group_operator='sum')\n"
        self.assertEqual(fix(pg.remove_keyword, src, callee="fields.", keyword="group_operator")[0].text, src)


class DecoratorTests(unittest.TestCase):
    CLASS = "from odoo import api\n\n\nclass A(models.Model):\n    @api.multi\n    def f(self):\n        pass\n"

    def test_decorator_line_removed(self):
        result, second = fix(pg.remove_decorator, self.CLASS, decorator="api.multi")
        self.assertEqual(result.text, self.CLASS.replace("    @api.multi\n", ""))
        self.assertEqual(second, [])

    def test_aliased_decorator_removed(self):
        src = "from odoo import api as a\n\n\nclass A:\n    @a.multi\n    def f(self):\n        pass\n"
        result, _ = fix(pg.remove_decorator, src, decorator="api.multi")
        self.assertNotIn("@a.multi", result.text)

    def test_call_form_decorator_removed(self):
        src = "from odoo import api\n\n\nclass A:\n    @api.returns('x')\n    def f(self):\n        pass\n"
        result, second = fix(pg.remove_decorator, src, decorator="api.returns")
        self.assertNotIn("api.returns", result.text)
        self.assertEqual(second, [])

    def test_other_decorator_is_kept(self):
        src = self.CLASS.replace("api.multi", "api.model")
        self.assertEqual(fix(pg.remove_decorator, src, decorator="api.multi")[0].text, src)

    def test_decorator_text_in_comment_is_kept(self):
        src = "# @api.multi\nclass A:\n    pass\n"
        self.assertEqual(fix(pg.remove_decorator, src, decorator="api.multi")[0].text, src)

    def test_flag_decorator_reports_and_does_not_edit(self):
        findings = detect(pg.flag_decorator, self.CLASS, decorator="api.multi")
        self.assertEqual([f.line for f in findings], [5])
        self.assertEqual(detect(pg.flag_decorator, self.CLASS, decorator="api.model"), [])


class CallFlagTests(unittest.TestCase):
    def test_flags_each_matching_call_with_line_and_context(self):
        findings = detect(pg.flag_call, "from odoo import fields\nx = fields.Char()\ny = fields.Char()\n",
                          callee="fields.Char")
        self.assertEqual([f.line for f in findings], [2, 3])
        self.assertEqual(findings[0].rule_id, CTX.rule_id)
        self.assertEqual(findings[0].severity, "WARNING")
        self.assertEqual(findings[0].message, "generic message")

    def test_other_call_is_not_flagged(self):
        self.assertEqual(detect(pg.flag_call, "x = fields.Integer()\n", callee="fields.Char"), [])

    def test_ambiguous_alias_is_still_flagged(self):
        src = "from odoo import fields\nfrom legacy import fields\nx = fields.Char()\n"
        self.assertEqual(len(detect(pg.flag_call, src, callee="fields.Char")), 1)


class MethodOverrideTests(unittest.TestCase):
    def test_method_in_class_is_flagged(self):
        src = "class A:\n    def name_get(self):\n        return []\n"
        findings = detect(pg.flag_method_override, src, method="name_get")
        self.assertEqual([f.line for f in findings], [2])

    def test_async_method_is_flagged(self):
        src = "class A:\n    async def name_get(self):\n        return []\n"
        self.assertEqual(len(detect(pg.flag_method_override, src, method="name_get")), 1)

    def test_decorated_method_reports_the_def_line(self):
        src = "class A:\n    @property\n    def name_get(self):\n        return []\n"
        self.assertEqual([f.line for f in detect(pg.flag_method_override, src, method="name_get")], [3])

    def test_module_function_is_not_flagged(self):
        self.assertEqual(detect(pg.flag_method_override, "def name_get(x):\n    return x\n",
                                method="name_get"), [])

    def test_other_method_name_is_not_flagged(self):
        self.assertEqual(detect(pg.flag_method_override, "class A:\n    def name_search(self):\n        pass\n",
                                method="name_get"), [])


class ClassAttributeTests(unittest.TestCase):
    def test_class_attribute_is_flagged(self):
        src = "class A:\n    _sql_constraints = [('a', 'b', 'c')]\n"
        self.assertEqual([f.line for f in detect(pg.flag_class_attribute, src, attribute="_sql_constraints")],
                         [2])

    def test_annotated_class_attribute_is_flagged(self):
        src = "class A:\n    _sql_constraints: list = []\n"
        self.assertEqual(len(detect(pg.flag_class_attribute, src, attribute="_sql_constraints")), 1)

    def test_local_variable_is_not_flagged(self):
        src = "class A:\n    def f(self):\n        _sql_constraints = []\n"
        self.assertEqual(detect(pg.flag_class_attribute, src, attribute="_sql_constraints"), [])

    def test_module_level_assignment_is_not_flagged(self):
        self.assertEqual(detect(pg.flag_class_attribute, "_sql_constraints = []\n", attribute="_sql_constraints"),
                         [])


class AttributeAccessTests(unittest.TestCase):
    def test_load_is_rewritten(self):
        result, second = fix(pg.rewrite_attribute_access, "x = self._context\n",
                             old="self._context", new="self.env.context")
        self.assertEqual(result.text, "x = self.env.context\n")
        self.assertEqual(second, [])

    def test_chained_load_is_rewritten(self):
        result, _ = fix(pg.rewrite_attribute_access, "x = self._context.get('a')\n",
                        old="self._context", new="self.env.context")
        self.assertEqual(result.text, "x = self.env.context.get('a')\n")

    def test_store_is_not_rewritten(self):
        src = "self._context = {}\n"
        self.assertEqual(fix(pg.rewrite_attribute_access, src, old="self._context", new="self.env.context")[0].text,
                         src)

    def test_longer_name_is_not_rewritten(self):
        src = "x = self._contextual\n"
        self.assertEqual(fix(pg.rewrite_attribute_access, src, old="self._context", new="self.env.context")[0].text,
                         src)

    def test_ambiguous_head_is_not_rewritten(self):
        src = "from odoo import api\nfrom legacy import api\nx = api.foo\n"
        self.assertEqual(fix(pg.rewrite_attribute_access, src, old="api.foo", new="api.bar")[0].text, src)

    def test_invalid_new_name_raises(self):
        with self.assertRaises(ValueError):
            pg.rewrite_attribute_access(Document.from_text(PATH, "x = a.b\n"), CTX, old="a.b", new="1 bad")

    def test_flag_reports_loads_and_stores(self):
        src = "x = self._context\nself._context = {}\n"
        self.assertEqual([f.line for f in detect(pg.flag_attribute_access, src, old="self._context")], [1, 2])


class ParseErrorTests(unittest.TestCase):
    def test_every_generic_function_is_silent_on_syntax_errors(self):
        document = Document.from_text(PATH, "def (:\n")
        calls = [
            lambda: pg.flag_call(document, CTX, callee="a.b"),
            lambda: pg.flag_decorator(document, CTX, decorator="a.b"),
            lambda: pg.flag_method_override(document, CTX, method="m"),
            lambda: pg.flag_class_attribute(document, CTX, attribute="a"),
            lambda: pg.flag_attribute_access(document, CTX, old="a.b"),
            lambda: pg.keyword_in_call(document, CTX, callee="a.", keyword="k"),
            lambda: pg.remove_decorator(document, CTX, decorator="a.b"),
            lambda: pg.remove_keyword(document, CTX, callee="a.", keyword="k"),
            lambda: pg.rewrite_attribute_access(document, CTX, old="a.b", new="c.d"),
        ]
        for call in calls:
            self.assertEqual(call(), [])


if __name__ == "__main__":
    unittest.main()
