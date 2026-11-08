"""TST-005-008 (REQ-XML-001): XML element, start-tag and attribute spans over the golden corpus."""

import json
import pathlib
import unittest

from odooflux.core.engine.documents import Document, Span
from odooflux.parsers.xml import document as xmldoc
from odooflux.parsers.xml.attr_lexer import lex_start_tag

from .. import _setup  # noqa: F401  (src first on sys.path)

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "golden_fixtures" / "transformations" / "xml"


def _cases():
    for meta_path in sorted(CORPUS.glob("*/meta.json")):
        case_dir = meta_path.parent
        inputs = sorted(case_dir.glob("input.*"))
        assert len(inputs) == 1, case_dir
        yield case_dir.name, json.loads(meta_path.read_text(encoding="utf-8")), inputs[0]


class CorpusSpanTests(unittest.TestCase):
    def test_corpus_has_at_least_twenty_cases(self):
        self.assertGreaterEqual(len(list(CORPUS.glob("*/meta.json"))), 20)

    def test_every_case_asserts_element_start_tag_and_attribute_spans(self):
        for name, meta, path in _cases():
            with self.subTest(case=name):
                doc = Document.from_bytes(path.name, path.read_bytes())
                result = xmldoc.parse(doc)
                if meta["parse_error"]:
                    self.assertIsNotNone(result.parse_error)
                    self.assertEqual(result.elements, ())
                    continue
                self.assertIsNone(result.parse_error)
                self.assertEqual(len(result.elements), len(meta["elements"]))
                for el, expected in zip(result.elements, meta["elements"]):
                    self.assertEqual(el.tag, expected["tag"])
                    self.assertEqual(doc.text[el.span.start:el.span.end], expected["span"])
                    self.assertEqual(doc.text[el.start_tag_span.start:el.start_tag_span.end],
                                     expected["start_tag"])
                    self.assertEqual(doc.text[el.name_span.start:el.name_span.end], expected["tag"])
                    self.assertEqual([a.name for a in el.attrs], [a["name"] for a in expected["attrs"]])
                    for attr, exp in zip(el.attrs, expected["attrs"]):
                        self.assertEqual(doc.text[attr.name_span.start:attr.name_span.end], exp["name"])
                        self.assertEqual(doc.text[attr.value_span.start:attr.value_span.end], exp["raw"])
                        self.assertEqual(attr.raw_value, exp["raw"])
                        self.assertEqual(attr.value, exp["value"])
                        self.assertTrue(attr.span.start <= attr.name_span.start < attr.value_span.start)
                        self.assertEqual(doc.text[attr.value_span.start - 1], attr.quote_char)
                        self.assertEqual(doc.text[attr.value_span.end], attr.quote_char)


class LocatorApiTests(unittest.TestCase):
    def setUp(self):
        self.text = (
            '<odoo>\n'
            '  <button name="a" invisible="1"/>\n'
            '  <button name="b"/>\n'
            '  <field name="c"></field>\n'
            '</odoo>\n'
        )
        self.doc = xmldoc.parse(Document.from_text("v.xml", self.text))
        self.assertIsNone(self.doc.parse_error)

    def test_find_by_tag_returns_document_order(self):
        starts = [e.span.start for e in xmldoc.find(self.doc, tag="button")]
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts, sorted(starts))

    def test_find_by_attribute_presence(self):
        hits = xmldoc.find(self.doc, attr="invisible")
        self.assertEqual([e.tag for e in hits], ["button"])
        self.assertEqual(xmldoc.find(self.doc), list(self.doc.elements))

    def test_attr_span_whole_and_value(self):
        el = xmldoc.find(self.doc, tag="button")[0]
        whole = xmldoc.attr_span(el, "invisible")
        value = xmldoc.attr_span(el, "invisible", part="value")
        self.assertEqual(self.text[whole.start:whole.end], 'invisible="1"')
        self.assertEqual(self.text[value.start:value.end], "1")

    def test_attr_span_missing_attribute_raises(self):
        el = xmldoc.find(self.doc, tag="button")[1]
        with self.assertRaises(KeyError):
            xmldoc.attr_span(el, "invisible")

    def test_insert_attr_point_after_last_attribute(self):
        el = xmldoc.find(self.doc, tag="button")[0]
        point = xmldoc.insert_attr_point(el)
        self.assertEqual(self.text[point - 1], '"')
        self.assertEqual(self.text[point:point + 2], "/>")

    def test_insert_attr_point_without_attributes_is_after_tag_name(self):
        el = self.doc.elements[0]  # <odoo> has no attributes
        point = xmldoc.insert_attr_point(el)
        self.assertEqual(self.text[point - 4:point], "odoo")
        self.assertEqual(self.text[point], ">")

    def test_self_closing_and_parent_links(self):
        button = xmldoc.find(self.doc, tag="button")[0]
        odoo = self.doc.elements[0]
        self.assertTrue(button.self_closing)
        self.assertEqual(button.parent_index, odoo.index)
        self.assertEqual(odoo.parent_index, None)
        self.assertEqual(len(odoo.children_index), 3)


class LexerTests(unittest.TestCase):
    def test_greater_than_inside_quoted_value_does_not_end_tag(self):
        text = '<f a="x > y" b=\'q\'>'
        tag = lex_start_tag(text, 0)
        self.assertEqual(text[tag.end - 1], ">")
        self.assertEqual([text[a.value_span.start:a.value_span.end] for a in tag.attrs], ["x > y", "q"])
        self.assertFalse(tag.self_closing)

    def test_self_closing_detected(self):
        text = '<f a="1"/>'
        tag = lex_start_tag(text, 0)
        self.assertTrue(tag.self_closing)
        self.assertEqual(tag.end, len(text))

    def test_span_type_is_span(self):
        doc = xmldoc.parse(Document.from_text("v.xml", '<a b="c"/>'))
        self.assertIsInstance(doc.elements[0].span, Span)


class ErrorHandlingTests(unittest.TestCase):
    def test_parse_never_raises_on_garbage(self):
        for text in ["", "not xml at all", "<a", "<a><b></a>", "<a b=c/>", "\x00"]:
            with self.subTest(text=text):
                result = xmldoc.parse(Document.from_text("v.xml", text))
                self.assertIsNotNone(result.parse_error)
                self.assertEqual(result.elements, ())

    def test_parse_accepts_plain_text_for_convenience(self):
        result = xmldoc.parse('<a b="1"/>')
        self.assertIsNone(result.parse_error)
        self.assertEqual(result.elements[0].tag, "a")


if __name__ == "__main__":
    unittest.main()
