"""TST-005-016 (REQ-TRF-003): XML edit-helper idempotence over the whole XML golden corpus.

The corpus meta.json files carry no rule operations, so this harness applies fixed synthetic helper
operations to every element of every parseable corpus file, then re-runs the same operations on the
output and requires zero edits and well-formed output.
"""

import unittest
import xml.etree.ElementTree as ET

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import xml as xh

from ..unit import _setup  # noqa: F401  (src first on sys.path)

XML_ROOT = _setup.REPO / "tests" / "golden_fixtures" / "transformations" / "xml"
RULE = "test.xml-corpus-idem"
ATTR, VALUE = "data-odf-idem", "1"


def _meta(i):
    return xh.EditMeta(id=f"e{i}", rule_id=RULE, step="fix", severity="WARNING")


def _parse(text):
    document = Document.from_text("c.xml", text)
    return document, xmldoc.parse(document)


def _set_all(xdoc):
    return [e for i, el in enumerate(xmldoc.find(xdoc)) if (e := xh.set_attr(xdoc, el, ATTR, VALUE, meta=_meta(i)))]


class XmlCorpusIdempotenceTests(unittest.TestCase):
    def test_set_attr_is_idempotent_on_every_xml_corpus_file(self):
        checked = elements = 0
        for case in sorted(p for p in XML_ROOT.iterdir() if (p / "input.xml").is_file()):
            text = (case / "input.xml").read_bytes().decode("utf-8", "surrogateescape")
            with self.subTest(case=case.name):
                document, xdoc = _parse(text)
                if xdoc.parse_error is not None:
                    continue
                edits = _set_all(xdoc)
                first = apply_edits(document, edits, precedence=[RULE]).text
                ET.fromstring(first.encode("utf-8", "surrogateescape"))
                document2, xdoc2 = _parse(first)
                self.assertEqual(_set_all(xdoc2), [], "second pass must produce no edits")
                # removing then removing again is also a no-op the second time
                removes = [e for i, el in enumerate(xmldoc.find(xdoc2))
                           if (e := xh.remove_attr(xdoc2, el, ATTR, meta=_meta(i)))]
                cleaned = apply_edits(document2, removes, precedence=[RULE]).text
                _, xdoc3 = _parse(cleaned)
                self.assertEqual([e for el in xmldoc.find(xdoc3)
                                  if (e := xh.remove_attr(xdoc3, el, ATTR, meta=_meta(0)))], [])
                checked += 1
                elements += len(edits)
        self.assertGreaterEqual(checked, 20)
        print(f"xml idempotence: files={checked} elements_edited={elements}")

    def _cases(self):
        for case in sorted(p for p in XML_ROOT.iterdir() if (p / "input.xml").is_file()):
            text = (case / "input.xml").read_bytes().decode("utf-8", "surrogateescape")
            document, xdoc = _parse(text)
            if xdoc.parse_error is None:
                yield case.name, document, xdoc

    def test_rename_tag_is_idempotent_on_every_xml_corpus_file(self):
        checked = 0
        for name, document, xdoc in self._cases():
            with self.subTest(case=name):
                edits = [e for i, el in enumerate(xmldoc.find(xdoc)) for e in xh.rename_tag(xdoc, el, "odfidem", meta=_meta(i))]
                first = apply_edits(document, edits, precedence=[RULE]).text
                ET.fromstring(first.encode("utf-8", "surrogateescape"))
                _, xdoc2 = _parse(first)
                again = [e for i, el in enumerate(xmldoc.find(xdoc2)) for e in xh.rename_tag(xdoc2, el, "odfidem", meta=_meta(i))]
                self.assertEqual(again, [], "second pass must produce no edits")
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_replace_element_is_idempotent_on_every_xml_corpus_file(self):
        """replace_element always emits an edit, so idempotence is output stability (root replaced twice)."""
        checked = 0
        for name, document, xdoc in self._cases():
            with self.subTest(case=name):
                root = [el for el in xmldoc.find(xdoc) if el.depth == 0]
                if len(root) != 1:
                    continue
                new = '<odfidem a="1"><child/></odfidem>'
                first = apply_edits(document, [xh.replace_element(xdoc, root[0], new, meta=_meta(0))], precedence=[RULE]).text
                ET.fromstring(first.encode("utf-8", "surrogateescape"))
                document2, xdoc2 = _parse(first)
                root2 = [el for el in xmldoc.find(xdoc2) if el.depth == 0]
                second = apply_edits(document2, [xh.replace_element(xdoc2, root2[0], new, meta=_meta(0))], precedence=[RULE]).text
                self.assertEqual(second, first)
                checked += 1
        self.assertGreaterEqual(checked, 20)


if __name__ == "__main__":
    unittest.main()
