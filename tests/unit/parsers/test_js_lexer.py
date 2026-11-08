"""TST-005-012 (REQ-JS-001): the stdlib JS lexer marks strings, templates, comments and regex literals.

Corpus cases live in tests/golden_fixtures/transformations/js/<case>/ and state, in meta.json,
which token kind each marker text must have. Every occurrence of the marker must lie inside a
token of that kind.
"""

import json
import unittest

from .. import _setup  # noqa: F401  (src first on sys.path)
from .._setup import REPO
from odooflux.core.engine.documents import Span
from odooflux.parsers.javascript.lexer import code_spans, tokenize

CORPUS = REPO / "tests" / "golden_fixtures" / "transformations" / "js"


def load_cases():
    return sorted(path for path in CORPUS.iterdir() if (path / "meta.json").is_file())


def occurrences(text, needle):
    found = []
    index = text.find(needle)
    while index != -1:
        found.append(index)
        index = text.find(needle, index + 1)
    return found


def kinds_at(tokens, start, end):
    return [t.kind for t in tokens if t.start <= start and end <= t.end]


class JsLexerCorpusTests(unittest.TestCase):
    def test_corpus_has_at_least_15_cases(self):
        self.assertGreaterEqual(len(load_cases()), 15)

    def test_every_corpus_case_is_tokenised_as_declared(self):
        for case in load_cases():
            with self.subTest(case=case.name):
                text = (case / "input.js").read_bytes().decode("utf-8")
                meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
                tokens = tokenize(text)
                self.assertEqual(self._cover(tokens, text), [],
                                 "tokens must tile the input exactly")
                for expectation in meta["tokens"]:
                    needle, kind = expectation["text"], expectation["kind"]
                    found = occurrences(text, needle)
                    self.assertTrue(found, f"marker {needle!r} not in input")
                    for start in found:
                        end = start + len(needle)
                        self.assertIn(kind, kinds_at(tokens, start, end),
                                      f"{needle!r} at {start} is not a {kind} token")

    def test_corpus_code_spans_never_contain_a_non_code_marker(self):
        for case in load_cases():
            with self.subTest(case=case.name):
                text = (case / "input.js").read_bytes().decode("utf-8")
                meta = json.loads((case / "meta.json").read_text(encoding="utf-8"))
                spans = code_spans(text)
                for expectation in meta["tokens"]:
                    if expectation["kind"] == "code":
                        continue
                    for start in occurrences(text, expectation["text"]):
                        end = start + len(expectation["text"])
                        self.assertFalse(any(s.start <= start and end <= s.end for s in spans),
                                         f"{expectation['text']!r} leaked into code spans")

    @staticmethod
    def _cover(tokens, text):
        problems, position = [], 0
        for token in tokens:
            if token.start != position or token.end <= token.start:
                problems.append((token, position))
            position = token.end
        if position != len(text):
            problems.append(("end", position))
        return problems


class JsLexerBehaviourTests(unittest.TestCase):
    def kinds(self, text):
        return [(t.kind, text[t.start:t.end]) for t in tokenize(text) if t.kind != "code"]

    def test_empty_input_has_no_tokens(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(code_spans(""), [])

    def test_code_spans_are_span_objects(self):
        self.assertEqual(code_spans("x // y"), [Span(0, 2)])

    def test_comment_only_file_has_only_whitespace_as_code(self):
        text = "// a\n/* b */\n"
        code_text = "".join(text[s.start:s.end] for s in code_spans(text))
        self.assertEqual(code_text, "\n\n")

    def test_division_after_identifier_closing_paren_and_bracket(self):
        text = "a = (b) / 2 / c[0] / d;"
        slashes = occurrences(text, "/")
        for start in slashes:
            self.assertEqual(kinds_at(tokenize(text), start, start + 1), ["code"])

    def test_regex_after_operators_and_punctuation(self):
        text = "x = a ? /y/ : /z/;"
        self.assertEqual(self.kinds(text), [("regex", "/y/"), ("regex", "/z/")])

    def test_regex_flags_belong_to_the_literal(self):
        self.assertEqual(self.kinds("var r = /a/gi;"), [("regex", "/a/gi")])

    def test_unclosed_regex_on_one_line_falls_back_to_code(self):
        text = "x = /abc\ny/"
        self.assertEqual([k for k, _ in self.kinds(text)], [])

    def test_unterminated_string_ends_at_the_line_break(self):
        tokens = tokenize("'abc\ndef")
        self.assertEqual((tokens[0].kind, tokens[0].start, tokens[0].end), ("string", 0, 4))
        self.assertEqual(tokens[1].kind, "code")

    def test_escaped_quote_does_not_end_a_string(self):
        self.assertEqual(self.kinds("'it\\'s' + 1"), [("string", "'it\\'s'")])

    def test_line_comment_ends_before_carriage_return(self):
        tokens = tokenize("// a\r\nb")
        self.assertEqual((tokens[0].kind, tokens[0].end), ("comment", 4))

    def test_unterminated_block_comment_runs_to_end_of_file(self):
        text = "a /* open\n odoo.define('x')"
        self.assertEqual(self.kinds(text), [("comment", "/* open\n odoo.define('x')")])

    def test_block_comment_hides_string_quotes(self):
        self.assertEqual(self.kinds("/* ' */ x"), [("comment", "/* ' */")])

    def test_escaped_backtick_inside_template(self):
        self.assertEqual(self.kinds("`a\\`b`"), [("template", "`a\\`b`")])

    def test_template_substitution_contains_code_between_template_parts(self):
        text = "`a${x}b`"
        kinds = [(t.kind, text[t.start:t.end]) for t in tokenize(text)]
        self.assertEqual(kinds, [("template", "`a${"), ("code", "x"), ("template", "}b`")])

    def test_tokens_tile_arbitrary_input(self):
        samples = ["", "x", "'", "`", "/", "/*", "${}", "a/b/c", "\\", "\r\n\r\n", "`${`${}`}`"]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(JsLexerCorpusTests._cover(tokenize(text), text), [])


if __name__ == "__main__":
    unittest.main()
