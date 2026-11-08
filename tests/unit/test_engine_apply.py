"""TST-003-016 (REQ-VER-004, REQ-TRF-001): right-to-left apply; precedence; before-mismatch rejects."""

import unittest

from odooflux.core.contracts.records import Edit
from odooflux.core.engine.apply import apply_edits, diff_to_edits

from ._setup import SRC  # noqa: F401


class ApplyEditsTests(unittest.TestCase):
    def test_non_overlapping_edits_apply(self):
        text = "aaa bbb ccc"
        edits = [Edit("f", 0, 3, "aaa", "X"), Edit("f", 8, 11, "ccc", "Z")]
        out, applied, rejected = apply_edits(text, edits)
        self.assertEqual(out, "X bbb Z")
        self.assertEqual(len(applied), 2)
        self.assertEqual(rejected, [])

    def test_overlap_resolved_by_precedence(self):
        text = "abcdef"
        low = Edit("f", 0, 4, "abcd", "LOW", precedence=1)
        high = Edit("f", 2, 6, "cdef", "HIGH", precedence=5)
        out, applied, rejected = apply_edits(text, [low, high])
        self.assertEqual(out, "abHIGH")
        self.assertEqual(low.status, "REJECTED")
        self.assertEqual(high.status, "APPLIED")

    def test_equal_precedence_overlap_rejects_both(self):
        text = "abcdef"
        a = Edit("f", 0, 4, "abcd", "A")
        b = Edit("f", 2, 6, "cdef", "B")
        out, applied, rejected = apply_edits(text, [a, b])
        self.assertEqual(out, "abcdef")
        self.assertEqual({a.status, b.status}, {"REJECTED"})

    def test_before_mismatch_is_rejected_with_reason(self):
        out, applied, rejected = apply_edits("hello", [Edit("f", 0, 5, "world", "x")])
        self.assertEqual(out, "hello")
        self.assertEqual(rejected[0].status, "REJECTED")
        self.assertIn("does not match", rejected[0].rejection_reason)

    def test_diff_then_apply_reproduces_the_new_text(self):
        before = "def f():\n    return 1\nprint(f())\n"
        after = "def f():\n    return 2\nprint(f())\nprint('x')\n"
        edits = diff_to_edits("f.py", before, after)
        out, _, rejected = apply_edits(before, edits)
        self.assertEqual(out, after)
        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
