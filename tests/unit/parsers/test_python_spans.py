"""TST-005-005 (REQ-PY-001, REQ-PY-004): Python span locators over the golden corpus, plus UTF-8 columns."""

import json
import pathlib
import unittest

from odooflux.core.engine import documents as docs
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp

from .. import _setup  # noqa: F401  (src first on sys.path)

CORPUS = _setup.REPO / "tests" / "golden_fixtures" / "transformations" / "python"


def load_case(name):
    case = CORPUS / name
    raw = (case / "input.py").read_bytes()
    meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
    return case, raw, meta


def corpus_names():
    return sorted(p.name for p in CORPUS.iterdir() if (p / "meta.json").exists())


def pick(items, occurrence):
    if occurrence >= len(items):
        raise AssertionError(f"occurrence {occurrence} requested but only {len(items)} match")
    return items[occurrence]


def resolve_span(doc, item):
    """Return the span selected by one corpus span item (see meta.json schema)."""
    locator = item["locator"]
    occurrence = item.get("occurrence", 0)
    if locator == "decorator_removal":
        decorators = sp.decorators_named(doc, item["decorator"])
        if "matches" in item:
            return None, len(decorators)
        return sp.decorator_removal_span(doc, pick(decorators, occurrence)), len(decorators)
    if locator in ("keyword_removal", "keyword_rename"):
        pairs = [(call, kw) for call in sp.calls_named(doc, item["call"])
                 for kw in sp.keywords_named(call, item["keyword"])]
        if locator == "keyword_removal":
            finder = lambda call, kw: sp.keyword_removal_span(doc, call, kw)  # noqa: E731
        else:
            finder = lambda call, kw: sp.keyword_rename_span(doc, kw)  # noqa: E731
        if "matches" in item:
            return None, len(pairs)
        call, kw = pick(pairs, occurrence)
        return finder(call, kw), len(pairs)
    if locator == "node":
        kind, name = item["kind"], item["name"]
        if kind == "call":
            nodes = sp.calls_named(doc, name)
        elif kind == "callee":
            nodes = [call.func for call in sp.calls_named(doc, name)]
        elif kind == "attribute":
            nodes = sp.attributes_named(doc, name)
        else:
            raise AssertionError(f"unknown node kind {kind}")
        if not nodes:
            return None, 0
        return sp.node_span(doc, pick(nodes, occurrence)), len(nodes)
    raise AssertionError(f"unknown locator {locator}")


class CorpusSpanTests(unittest.TestCase):
    def test_every_case_has_span_assertions_or_is_a_reject(self):
        for name in corpus_names():
            _, _, meta = load_case(name)
            with self.subTest(case=name):
                if meta["expect"] == "reject":
                    self.assertEqual(meta["spans"], [])
                else:
                    self.assertTrue(meta["spans"], "no span assertion")

    def test_corpus_spans(self):
        for name in corpus_names():
            case, raw, meta = load_case(name)
            document = docs.Document.from_bytes(str(case / "input.py"), raw)
            parsed = pydoc.parse_document(document)
            if meta["expect"] == "reject":
                with self.subTest(case=name):
                    self.assertIsNotNone(parsed.parse_error)
                    self.assertIsNone(parsed.tree)
                    self.assertEqual(parsed.tokens, ())
                continue
            self.assertIsNone(parsed.parse_error, name)
            for item in meta["spans"]:
                with self.subTest(case=name, locator=item["locator"]):
                    span, count = resolve_span(parsed, item)
                    if "matches" in item:
                        self.assertEqual(count, item["matches"])
                    else:
                        self.assertIsNotNone(span, "no node matched")
                        self.assertEqual(parsed.text[span.start:span.end], item["covers"])


class ParseTests(unittest.TestCase):
    def test_parse_never_raises_on_invalid_input(self):
        for source in ("def (", "\x00", "x = '\udc80'", "if x:\n\tpass\n    pass\n", ""):
            with self.subTest(source=source):
                parsed = pydoc.parse(source)
                self.assertTrue(parsed.parse_error is None or isinstance(parsed.parse_error, dict))

    def test_parse_error_carries_message_line_and_column(self):
        parsed = pydoc.parse("x = (\n")
        self.assertIsNone(parsed.tree)
        self.assertEqual(set(parsed.parse_error), {"message", "line", "column"})
        self.assertGreaterEqual(parsed.parse_error["line"], 1)

    def test_valid_source_has_tree_and_tokens(self):
        parsed = pydoc.parse("x = 1\n")
        self.assertIsNone(parsed.parse_error)
        self.assertIsNotNone(parsed.tree)
        self.assertTrue(any(tok[1] == "x" for tok in parsed.tokens))


class SpanConversionTests(unittest.TestCase):
    def test_utf8_byte_columns_become_character_offsets(self):
        source = "label = 'héllo'; size(x=1)\n"
        parsed = pydoc.parse(source)
        call = parsed.tree.body[1].value
        kw = call.keywords[0]
        span = sp.node_span(parsed, kw)
        self.assertEqual(source[span.start:span.end], "x=1")

    def test_line_span_with_and_without_newline(self):
        parsed = pydoc.parse("a = 1\nb = 2\n")
        self.assertEqual(parsed.text[sp.line_span(parsed, 2).start:sp.line_span(parsed, 2).end], "b = 2\n")
        span = sp.line_span(parsed, 2, include_newline=False)
        self.assertEqual(parsed.text[span.start:span.end], "b = 2")

    def test_decorator_must_start_its_own_line(self):
        parsed = pydoc.parse("class A:\n    @api.multi\n    def f(self):\n        pass\n")
        decorator = sp.decorators_named(parsed, "api.multi")[0]
        span = sp.decorator_removal_span(parsed, decorator)
        self.assertEqual(parsed.text[span.start:span.end], "    @api.multi\n")


if __name__ == "__main__":
    unittest.main()
