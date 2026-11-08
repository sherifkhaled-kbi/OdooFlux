"""TST-005-001 (REQ-TRF-004): Document decoding/encoding round-trip, newline/BOM handling, positions."""

import hashlib
import unittest

from odooflux.core.engine import documents as docs

from .. import _setup  # noqa: F401  (src first on sys.path)

BOM = b"\xef\xbb\xbf"


class DocumentRoundTripTests(unittest.TestCase):
    def assertRoundTrip(self, path, raw):
        doc = docs.Document.from_bytes(path, raw)
        self.assertEqual(doc.encode(), raw)
        return doc

    def test_utf8_plain(self):
        raw = "x = 'héllo'\n".encode()
        doc = self.assertRoundTrip("a.py", raw)
        self.assertEqual(doc.text, "x = 'héllo'\n")
        self.assertEqual(doc.encoding, "utf-8")
        self.assertFalse(doc.bom)
        self.assertEqual(doc.newline, "\n")

    def test_utf8_bom_stripped_from_text_and_restored(self):
        doc = self.assertRoundTrip("a.txt", BOM + b"hello\n")
        self.assertTrue(doc.bom)
        self.assertEqual(doc.text, "hello\n")

    def test_crlf_detected(self):
        doc = self.assertRoundTrip("a.txt", b"a\r\nb\r\n")
        self.assertEqual(doc.newline, "\r\n")
        self.assertEqual(doc.text, "a\r\nb\r\n")

    def test_cr_only_detected(self):
        doc = self.assertRoundTrip("a.txt", b"a\rb\r")
        self.assertEqual(doc.newline, "\r")

    def test_mixed_newlines_detected_and_preserved(self):
        doc = self.assertRoundTrip("a.txt", b"a\r\nb\nc\rd")
        self.assertEqual(doc.newline, "mixed")

    def test_latin1_declared_in_xml_declaration(self):
        raw = b'<?xml version="1.0" encoding="ISO-8859-1"?>\n<a>caf\xe9</a>\n'
        doc = self.assertRoundTrip("v.xml", raw)
        self.assertEqual(doc.encoding, "iso8859-1")
        self.assertTrue(doc.text.endswith("<a>café</a>\n"))

    def test_python_coding_cookie_latin1(self):
        raw = b"# -*- coding: latin-1 -*-\nname = '\xe9'\n"
        doc = self.assertRoundTrip("m.py", raw)
        self.assertEqual(doc.encoding, "iso8859-1")
        self.assertIn("'é'", doc.text)

    def test_coding_cookie_ignored_outside_python(self):
        raw = b"# coding: latin-1\nx=\xe9\n"
        doc = self.assertRoundTrip("notes.txt", raw)
        self.assertEqual(doc.encoding, "utf-8")
        self.assertIn("undecodable-bytes", doc.issues)

    def test_undecodable_utf8_bytes_round_trip(self):
        raw = b"ok \xff\xfe bytes\n"
        doc = self.assertRoundTrip("a.py", raw)
        self.assertIn("undecodable-bytes", doc.issues)

    def test_truncated_utf8_sequence_round_trips(self):
        self.assertRoundTrip("a.py", b"abc\xe2\x82")

    def test_unknown_declared_encoding_falls_back_with_issue(self):
        raw = b'<?xml version="1.0" encoding="x-nonexistent"?><a/>'
        doc = self.assertRoundTrip("v.xml", raw)
        self.assertEqual(doc.encoding, "utf-8")
        self.assertIn("unknown-encoding:x-nonexistent", doc.issues)

    def test_utf16_declared_is_not_decoded_as_utf16(self):
        raw = b'<?xml version="1.0" encoding="UTF-16"?><a/>'
        doc = self.assertRoundTrip("v.xml", raw)
        self.assertEqual(doc.encoding, "utf-8")
        self.assertIn("unsupported-encoding:utf-16", doc.issues)

    def test_empty_file(self):
        doc = self.assertRoundTrip("empty.py", b"")
        self.assertEqual(doc.text, "")
        self.assertEqual(doc.newline, "")

    def test_bom_with_crlf_and_non_ascii(self):
        doc = self.assertRoundTrip("a.txt", BOM + "é\r\n€\r\n".encode())
        self.assertEqual(doc.newline, "\r\n")

    def test_sha256_is_of_raw_bytes(self):
        raw = BOM + b"x\n"
        doc = docs.Document.from_bytes("a.txt", raw)
        self.assertEqual(doc.sha256, hashlib.sha256(raw).hexdigest())


class PositionTests(unittest.TestCase):
    def test_columns_count_characters_not_bytes(self):
        doc = docs.Document.from_bytes("a.py", "é = 1\nx = 'ü' + y\n".encode())
        self.assertEqual(doc.line_col(doc.text.index("y")), (2, 10))

    def test_crlf_line_starts(self):
        doc = docs.Document.from_bytes("a.txt", b"ab\r\ncd\r\n")
        self.assertEqual(doc.line_col(doc.text.index("c")), (2, 0))
        self.assertEqual(doc.offset(2, 1), doc.text.index("d"))

    def test_cr_only_line_starts(self):
        doc = docs.Document.from_bytes("a.txt", b"ab\rcd")
        self.assertEqual(doc.line_col(doc.text.index("c")), (2, 0))

    def test_offset_and_line_col_are_inverse(self):
        doc = docs.Document.from_bytes("a.txt", "a\né\n\nxyz".encode())
        for offset in range(len(doc.text) + 1):
            self.assertEqual(doc.offset(*doc.line_col(offset)), offset)

    def test_out_of_range_offset_raises(self):
        doc = docs.Document.from_bytes("a.txt", b"abc")
        with self.assertRaises(ValueError):
            doc.line_col(-1)
        with self.assertRaises(ValueError):
            doc.line_col(4)

    def test_span_rejects_inverted_bounds(self):
        with self.assertRaises(ValueError):
            docs.Span(3, 2)

    def test_locate_span_returns_both_ends(self):
        doc = docs.Document.from_bytes("a.txt", b"ab\ncd\n")
        start, end = doc.text.index("b"), doc.text.index("d") + 1
        self.assertEqual(doc.locate(docs.Span(start, end)), (1, 1, 2, 2))

    def test_with_text_keeps_encoding_and_bom_and_recomputes_newline(self):
        doc = docs.Document.from_bytes("a.txt", BOM + b"a\r\nb\r\n")
        new = doc.with_text("x\ny\n")
        self.assertTrue(new.bom)
        self.assertEqual(new.newline, "\n")
        self.assertEqual(new.encode(), BOM + b"x\ny\n")


if __name__ == "__main__":
    unittest.main()
