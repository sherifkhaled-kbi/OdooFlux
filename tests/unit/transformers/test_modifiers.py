"""TST-005-010 (REQ-XML-002): attrs/states -> modifier expression converter over the golden corpus."""

import json
import pathlib
import unittest
import xml.etree.ElementTree as ET
from collections import Counter

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import modifiers as mod
from odooflux.transformers.xml import EditMeta

from .. import _setup  # noqa: F401  (src first on sys.path)

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "golden_fixtures" / "transformations" / "converter"
RULE = "test.converter"
GROUPS = ("operators", "nesting", "modes", "context_names", "list_values", "merge", "states",
          "column_invisible", "entities", "multiline", "unsupported", "malformed", "unknown_keys")


def _target(xdoc):
    for element in xdoc.elements:
        if element.get_attr("attrs") is not None or element.get_attr("states") is not None:
            return element
    # After a conversion nothing is left to convert; the first element must then yield zero edits.
    return xdoc.elements[1]


def _cases():
    for meta_path in sorted(CORPUS.glob("*/meta.json")):
        yield meta_path.parent.name, json.loads(meta_path.read_text(encoding="utf-8")), meta_path.parent


def _convert(text, meta):
    document = Document.from_text("v.xml", text)
    xdoc = xmldoc.parse(document)
    assert xdoc.parse_error is None, xdoc.parse_error
    conversion = mod.convert_element(
        xdoc, _target(xdoc), mode=meta["mode"], in_list_view=meta["in_list_view"],
        meta=EditMeta(id="conv", rule_id=RULE, step="fix", severity="WARNING"))
    result = apply_edits(document, conversion.edits, precedence=[RULE])
    return conversion, result


class CorpusTests(unittest.TestCase):
    def test_corpus_size_and_group_coverage(self):
        cases = list(_cases())
        self.assertGreaterEqual(len(cases), 60)
        counts = Counter(meta["group"] for _, meta, _ in cases)
        for group in GROUPS:
            self.assertGreaterEqual(counts[group], 3, group)

    def test_every_case_matches_expected_output_and_reasons(self):
        for name, meta, case_dir in _cases():
            with self.subTest(case=name):
                text = (case_dir / "input.xml").read_text(encoding="utf-8")
                expected = (case_dir / "expected.xml").read_text(encoding="utf-8")
                conversion, result = _convert(text, meta)
                self.assertEqual(result.rejected, (), "no edit may be rejected")
                self.assertTrue(result.preserved_ok)
                self.assertEqual(result.text, expected)
                self.assertEqual(bool(conversion.edits), meta["expect"] == "edit")
                self.assertEqual([(u.key, u.reason) for u in conversion.unconverted],
                                 [(u["key"], u["reason"]) for u in meta["unconverted"]])
                self.assertEqual(list(conversion.warnings), meta["warnings"])
                ET.fromstring(result.text.encode("utf-8"))
                self.assertNotIn("<!--", result.text)

    def test_second_conversion_yields_zero_edits(self):
        for name, meta, case_dir in _cases():
            with self.subTest(case=name):
                text = (case_dir / "input.xml").read_text(encoding="utf-8")
                _, first = _convert(text, meta)
                second, _ = _convert(first.text, meta)
                self.assertEqual(second.edits, ())


class DomainToExpressionTests(unittest.TestCase):
    def test_string_expression_is_returned_unchanged(self):
        self.assertEqual(mod.domain_to_expression("state == 'x' and y", "falsy"), "state == 'x' and y")

    def test_empty_domain_is_true(self):
        self.assertEqual(mod.domain_to_expression([], "falsy"), "True")

    def test_unsupported_operator_is_reported(self):
        out = mod.domain_to_expression([("a", "like", "x")], "falsy")
        self.assertIsInstance(out, mod.Unconvertible)
        self.assertEqual(out.reason, "unsupported operator like")

    def test_malformed_domain_is_reported(self):
        out = mod.domain_to_expression(42, "falsy")
        self.assertIsInstance(out, mod.Unconvertible)
        self.assertEqual(out.reason, "malformed-domain")

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            mod.domain_to_expression([("a", "=", 1)], "strict")

    def test_top_level_parentheses_removed_only_once(self):
        out = mod.domain_to_expression(["&", ("a", "=", 1), "|", ("b", "=", 2), ("c", "=", 3)], "falsy")
        self.assertEqual(out, "a == 1 and (b == 2 or c == 3)")


if __name__ == "__main__":
    unittest.main()
