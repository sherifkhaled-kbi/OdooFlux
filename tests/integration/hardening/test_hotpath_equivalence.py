"""T014 (REQ-PRF-001): hot-path optimisations keep results identical.

Each optimisation is pinned by a behaviour check against a reference implementation or by a work counter."""

import io
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest import mock

from tests.unit import _setup  # noqa: F401

from odooflux.core.engine.documents import Document, Span
from odooflux.core.orchestrator import knowledge_rules
from odooflux.parsers.python import document as pydoc
from odooflux.rules.python import generic

TEXTS = [
    "x = 1\n",
    "x = 1",
    "def f(a,\r\n      b):\r\n    return a +\\\r\n        b\r\n",
    "a = 1\rb = 'é€'\r",
    "class A:\n    def f(self):\n        s = '''multi\nline'''\n        return \"ü\"  # c\n\n\n",
    "# only a comment\n",
    "x = (1,\n     2)\r\ny = 3\n",
    "",
]


def reference_tokens(document):
    """The pre-optimisation tokenisation (per-token offset scan), kept as the oracle."""
    def offset(row, col):
        if row > document.line_col(len(document.text))[0]:
            return len(document.text)
        line_start = document.offset(row, 0)
        line_end = line_start
        text = document.text
        while line_end < len(text) and text[line_end] not in "\r\n":
            line_end += 1
        return line_start + min(col, line_end - line_start)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(document.text, newline=None).readline):
        start, end = offset(*tok.start), offset(*tok.end)
        out.append((tok.type, tok.string, Span(start, max(start, end))))
    return tuple(out)


class TokenOffsetTests(unittest.TestCase):
    def test_tokens_equal_the_reference(self):
        for text in TEXTS:
            document = Document.from_text("m.py", text)
            self.assertEqual(pydoc._tokenize(document), reference_tokens(document), repr(text))

    def test_line_ends_helper_matches_a_scan(self):
        document = Document.from_text("m.py", "ab\r\ncd\ref\n\ngh")
        self.assertEqual(pydoc._line_content_ends(document), [2, 6, 9, 10, 13])


class SharedWorkTests(unittest.TestCase):
    def test_file_kind_is_memoised(self):
        self.assertTrue(hasattr(knowledge_rules.file_kind, "cache_info"))
        self.assertEqual(knowledge_rules.file_kind("a/b/__manifest__.py"), "manifest")
        self.assertEqual(knowledge_rules.file_kind("a/b/x.XML"), "xml")
        self.assertEqual(knowledge_rules.file_kind("Makefile"), "")

    def test_import_names_are_built_once_per_parsed_document(self):
        text = "from odoo import fields\nx = fields.Char()\n"
        parsed = pydoc.parse_document(Document.from_text("one.py", text))
        with mock.patch.object(generic, "Names", wraps=generic.Names) as names:
            for _ in range(5):
                generic._load(Document.from_text("one.py", text))
        self.assertEqual(names.call_count, 1)
        self.assertIsNotNone(parsed.tree)

    def test_rules_share_one_document_per_file(self):
        class Bound:
            def detect(self, document):
                return []
        meta = {"step": "*", "file_kinds": ["python"], "evidence": []}
        bound = type("B", (), {"rule_id": "r", "maturity": "DETECT_ONLY", "review_required": False,
                               "fixer": None, "detect": Bound().detect})()
        rules = [knowledge_rules.KnowledgeRule(bound, meta) for _ in range(6)]
        doc = Document.from_text("x.py", "a = 1\n")
        with mock.patch.object(Document, "from_text", wraps=Document.from_text) as from_text:
            for rule in rules:
                rule.detect(doc)
        self.assertEqual(from_text.call_count, 1)


class NodeCacheTests(unittest.TestCase):
    def test_all_nodes_is_cached_per_tree_across_interleaving(self):
        import ast
        from odooflux.parsers.python import spans as sp
        a, b = ast.parse("x = 1\ny = [1, 2]\n"), ast.parse("z = 3\n")
        first = sp.all_nodes(a)
        sp.all_nodes(b)
        self.assertIs(sp.all_nodes(a), first)
        self.assertEqual(list(first), list(ast.walk(a)))

    def test_hot_modules_use_the_shared_node_cache(self):
        root = Path(__file__).resolve().parents[3] / "src" / "odooflux"
        for rel in ("rules/python/sql_constraints.py", "rules/security/field_refs.py", "rules/xml/view_types.py",
                    "validation/dependency/integrity.py"):
            self.assertNotIn("ast.walk(", (root / rel).read_text(encoding="utf-8"), rel)


class ParseAndBucketTests(unittest.TestCase):
    SOURCE = ("from odoo import models, fields, api\n\nclass A(models.Model):\n    _name = 'x.y'\n"
              "    f = fields.Many2one('x.y')\n    @api.multi\n    def go(self):\n        return self.env['x.y']\n")

    def test_parse_memo_returns_the_same_tree_for_the_same_text(self):
        from odooflux.utils import astnodes
        self.assertIs(astnodes.parse(self.SOURCE, "a.py"), astnodes.parse(self.SOURCE, "b.py"))
        with self.assertRaises(SyntaxError):
            astnodes.parse("def (:\n", "bad.py")

    def test_nodes_of_matches_a_filter_in_walk_order(self):
        import ast
        from odooflux.utils import astnodes
        tree = astnodes.parse(self.SOURCE, "a.py")
        for types in (ast.Call, ast.ClassDef, ast.Name, ast.Subscript, (ast.FunctionDef, ast.ClassDef), ast.Pass):
            expected = [n for n in ast.walk(tree) if isinstance(n, types)]
            self.assertEqual(list(astnodes.nodes_of(tree, types)), expected, types)

    def test_ast_parse_runs_once_for_parse_document_and_inventory(self):
        import ast
        from odooflux.analyzers.risk_inventory import inventory_python
        text = self.SOURCE + "# unique-marker-1\n"
        with mock.patch.object(ast, "parse", wraps=ast.parse) as parse:
            pydoc.parse_document(Document.from_text("u.py", text))
            inventory_python("u.py", text)
        self.assertEqual(parse.call_count, 1)

    def test_spans_are_built_only_when_tokens_are_read(self):
        text = self.SOURCE + "# unique-marker-2\n"
        with mock.patch.object(pydoc, "_spans_for", wraps=pydoc._spans_for) as spans:
            parsed = pydoc.parse_document(Document.from_text("lazy.py", text))
            self.assertEqual(spans.call_count, 0)
            tokens = parsed.tokens
            self.assertEqual(spans.call_count, 1)
            self.assertIs(parsed.tokens, tokens)
        self.assertEqual(tokens, reference_tokens(Document.from_text("lazy.py", text)))


class JsLexerMemoTests(unittest.TestCase):
    def test_javascript_tokenize_is_memoised_and_unchanged(self):
        from odooflux.parsers.javascript import lexer
        text = "odoo.define('a.b', function (require) {\n  var s = `x${1}`; // c\n  return /re/g;\n});\n"
        first = lexer.tokenize(text)
        self.assertIs(lexer.tokenize(text), first)
        self.assertEqual(first, lexer._tokenize_uncached(text))


if __name__ == "__main__":
    unittest.main()
