"""TST-005-002 (REQ-TRF-001, REQ-TRF-002, REQ-TRF-004): apply_edits validation, stale spans, overlaps, preservation."""

import dataclasses
import unittest
from unittest import mock

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng

from .. import _setup  # noqa: F401  (src first on sys.path)

BOM = b"\xef\xbb\xbf"


def make_edit(doc, start, end, after, *, rule="r.a", severity="WARNING", id=None, before=None):
    return eng.Edit(
        id=id or f"{rule}:{start}:{end}:{after}", rule_id=rule, path=doc.path, start=start, end=end,
        before=doc.text[start:end] if before is None else before, after=after, severity=severity,
        step="step-1", validation=("syntax",))


class RequiredFieldTests(unittest.TestCase):
    def setUp(self):
        self.doc = docs.Document.from_bytes("m.py", b"abc def\n")
        self.valid = make_edit(self.doc, 0, 3, "X")

    def assertRejected(self, edit, reason):
        result = eng.apply_edits(self.doc, [edit], precedence=["r.a"])
        self.assertEqual(result.applied, ())
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].rejection_reason, reason)
        self.assertEqual(result.rejected[0].status, "REJECTED")
        self.assertEqual(result.text, self.doc.text)

    def test_valid_edit_is_accepted_as_control(self):
        result = eng.apply_edits(self.doc, [self.valid], precedence=["r.a"])
        self.assertEqual(result.text, "X def\n")

    def test_missing_id(self):
        self.assertRejected(dataclasses.replace(self.valid, id=""), "invalid-edit:id")

    def test_missing_rule_id(self):
        self.assertRejected(dataclasses.replace(self.valid, rule_id=""), "invalid-edit:rule_id")

    def test_missing_step(self):
        self.assertRejected(dataclasses.replace(self.valid, step=""), "invalid-edit:step")

    def test_path_differs_from_document(self):
        self.assertRejected(dataclasses.replace(self.valid, path="other.py"), "invalid-edit:path")

    def test_unknown_severity(self):
        self.assertRejected(dataclasses.replace(self.valid, severity="HIGH"), "invalid-edit:severity")

    def test_validation_list_missing(self):
        self.assertRejected(dataclasses.replace(self.valid, validation=None), "invalid-edit:validation")

    def test_inverted_span(self):
        self.assertRejected(dataclasses.replace(self.valid, start=4, end=2), "invalid-edit:start")

    def test_span_past_end_of_text(self):
        self.assertRejected(dataclasses.replace(self.valid, end=99), "invalid-edit:end")

    def test_negative_start(self):
        self.assertRejected(dataclasses.replace(self.valid, start=-1), "invalid-edit:start")

    def test_before_not_a_string(self):
        self.assertRejected(dataclasses.replace(self.valid, before=None), "invalid-edit:before")

    def test_after_not_encodable_in_document_encoding(self):
        latin = docs.Document.from_bytes("m.py", b"# coding: latin-1\nabc\n")
        edit = make_edit(latin, 0, 0, "€")
        result = eng.apply_edits(latin, [edit], precedence=["r.a"])
        self.assertEqual(result.rejected[0].rejection_reason, "invalid-edit:after")


class StaleSpanTests(unittest.TestCase):
    def test_before_text_mismatch_is_stale(self):
        doc = docs.Document.from_bytes("m.py", b"abc def\n")
        stale = make_edit(doc, 0, 3, "X", before="zzz")
        result = eng.apply_edits(doc, [stale], precedence=["r.a"])
        self.assertEqual(result.rejected[0].rejection_reason, "stale-span")
        self.assertEqual(result.text, doc.text)


class OverlapTests(unittest.TestCase):
    def setUp(self):
        self.doc = docs.Document.from_bytes("m.py", b"abcdef")

    def test_higher_severity_wins_over_earlier_rule(self):
        low = make_edit(self.doc, 0, 4, "X", rule="r.a", severity="WARNING")
        high = make_edit(self.doc, 2, 6, "Y", rule="r.b", severity="CRITICAL")
        result = eng.apply_edits(self.doc, [low, high], precedence=["r.a", "r.b"])
        self.assertEqual(result.text, "abY")
        rejected = {e.id: e.rejection_reason for e in result.rejected}
        self.assertEqual(rejected[low.id], f"conflict:{high.id}")

    def test_equal_severity_earlier_in_precedence_wins(self):
        a = make_edit(self.doc, 0, 4, "X", rule="r.a")
        b = make_edit(self.doc, 2, 6, "Y", rule="r.b")
        result = eng.apply_edits(self.doc, [a, b], precedence=["r.b", "r.a"])
        self.assertEqual(result.text, "abY")
        self.assertEqual(result.rejected[0].id, a.id)

    def test_equal_severity_and_rule_rejects_both(self):
        a = make_edit(self.doc, 0, 4, "X", rule="r.a", id="a")
        b = make_edit(self.doc, 2, 6, "Y", rule="r.a", id="b")
        result = eng.apply_edits(self.doc, [a, b], precedence=["r.a"])
        self.assertEqual(result.applied, ())
        self.assertEqual(result.text, self.doc.text)
        self.assertEqual({e.rejection_reason for e in result.rejected}, {"conflict:a,b"})

    def test_adjacent_spans_are_not_overlaps(self):
        doc = docs.Document.from_bytes("m.py", b"aaabbb")
        a = make_edit(doc, 0, 3, "X")
        b = make_edit(doc, 3, 6, "Y")
        result = eng.apply_edits(doc, [a, b], precedence=["r.a"])
        self.assertEqual(result.text, "XY")
        self.assertEqual(result.rejected, ())

    def test_insertion_inside_span_conflicts(self):
        doc = docs.Document.from_bytes("m.py", b"abcdef")
        span = make_edit(doc, 1, 5, "X", rule="r.a")
        ins = make_edit(doc, 3, 3, "I", rule="r.b")
        result = eng.apply_edits(doc, [span, ins], precedence=["r.a", "r.b"])
        self.assertEqual(result.text, "aXf")
        self.assertEqual(result.rejected[0].id, ins.id)

    def test_insertion_at_span_boundary_is_not_an_overlap(self):
        doc = docs.Document.from_bytes("m.py", b"abcdef")
        span = make_edit(doc, 1, 3, "X", rule="r.a")
        ins = make_edit(doc, 3, 3, "I", rule="r.b")
        result = eng.apply_edits(doc, [span, ins], precedence=["r.a", "r.b"])
        self.assertEqual(result.text, "aXIdef")
        self.assertEqual(result.rejected, ())

    def test_same_offset_insertions_ordered_by_precedence(self):
        doc = docs.Document.from_bytes("m.py", b"ab")
        b = make_edit(doc, 1, 1, "B", rule="r.b")
        a = make_edit(doc, 1, 1, "A", rule="r.a")
        result = eng.apply_edits(doc, [b, a], precedence=["r.a", "r.b"])
        self.assertEqual(result.text, "aABb")
        self.assertEqual(result.rejected, ())

    def test_same_offset_insertions_same_rule_ordered_by_id(self):
        doc = docs.Document.from_bytes("m.py", b"ab")
        z = make_edit(doc, 1, 1, "Z", id="z")
        y = make_edit(doc, 1, 1, "Y", id="y")
        result = eng.apply_edits(doc, [z, y], precedence=["r.a"])
        self.assertEqual(result.text, "aYZb")

    def test_unlisted_rule_ranks_after_listed_rule(self):
        listed = make_edit(self.doc, 0, 4, "X", rule="r.a")
        unlisted = make_edit(self.doc, 2, 6, "Y", rule="r.z")
        result = eng.apply_edits(self.doc, [unlisted, listed], precedence=["r.a"])
        self.assertEqual(result.text, "Xef")


class ResultTests(unittest.TestCase):
    def test_applied_and_rejected_partition_the_input(self):
        doc = docs.Document.from_bytes("m.py", b"abc def ghi\n")
        good = make_edit(doc, 0, 3, "X")
        stale = make_edit(doc, 4, 7, "Y", before="nope")
        bad = dataclasses.replace(make_edit(doc, 8, 11, "Z"), step="")
        result = eng.apply_edits(doc, [good, stale, bad], precedence=["r.a"])
        self.assertEqual(len(result.applied) + len(result.rejected), 3)
        self.assertEqual([e.status for e in result.applied], ["APPLIED"])
        self.assertTrue(all(e.rejection_reason for e in result.rejected))

    def test_inputs_are_not_mutated(self):
        doc = docs.Document.from_bytes("m.py", b"abc def\n")
        edits = [make_edit(doc, 0, 3, "X"), make_edit(doc, 4, 7, "Y", before="nope")]
        snapshot = [(e.status, e.rejection_reason) for e in edits]
        original_text, original_list = doc.text, list(edits)
        eng.apply_edits(doc, edits, precedence=["r.a"])
        self.assertEqual([(e.status, e.rejection_reason) for e in edits], snapshot)
        self.assertEqual(doc.text, original_text)
        self.assertEqual(edits, original_list)

    def test_crlf_and_bom_bytes_outside_spans_are_preserved(self):
        doc = docs.Document.from_bytes("m.txt", BOM + b"a\r\nbb\r\n")
        edit = make_edit(doc, doc.text.index("bb"), doc.text.index("bb") + 2, "c")
        result = eng.apply_edits(doc, [edit], precedence=["r.a"])
        self.assertTrue(result.preserved_ok)
        self.assertEqual(doc.with_text(result.text).encode(), BOM + b"a\r\nc\r\n")

    def test_empty_batch_is_a_no_op(self):
        doc = docs.Document.from_bytes("m.py", b"x\n")
        result = eng.apply_edits(doc, [], precedence=[])
        self.assertEqual((result.text, result.applied, result.rejected, result.preserved_ok),
                         ("x\n", (), (), True))

    def test_preservation_failure_rejects_whole_batch(self):
        doc = docs.Document.from_bytes("m.py", b"abc def\n")
        edits = [make_edit(doc, 0, 3, "X")]
        with mock.patch.object(eng, "_reference_splice", return_value="WRONG"):
            result = eng.apply_edits(doc, edits, precedence=["r.a"])
        self.assertFalse(result.preserved_ok)
        self.assertEqual(result.applied, ())
        self.assertEqual([e.rejection_reason for e in result.rejected], ["internal-preservation-failure"])
        self.assertEqual(result.text, doc.text)

    def test_precedence_is_keyword_only(self):
        doc = docs.Document.from_bytes("m.py", b"x\n")
        with self.assertRaises(TypeError):
            eng.apply_edits(doc, [], ["r.a"])


if __name__ == "__main__":
    unittest.main()
