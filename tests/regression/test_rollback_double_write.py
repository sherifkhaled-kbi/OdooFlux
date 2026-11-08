"""R4 review finding: a path written twice in one run (deterministic promote, then an AI edit) logged an intermediate
``sha256_before`` that matches no backup, so rollback raised and left the file changed. Rewrites of one path are now
collapsed to the first ``before`` (the backed-up original) and the last ``after``."""

import unittest

from odooflux.core.recovery.rollback import _collapse_rewrites


def e(path, before, after, **extra):
    return {"event": "file_written", "path": path, "sha256_before": before, "sha256_after": after, **extra}


class CollapseRewritesTests(unittest.TestCase):
    def test_two_writes_become_one_original_to_final(self):
        out = _collapse_rewrites([e("a", "A", "B"), e("b", "X", "Y"), e("a", "B", "C")])
        self.assertEqual([(x["path"], x["sha256_before"], x["sha256_after"]) for x in out],
                         [("b", "X", "Y"), ("a", "A", "C")])

    def test_created_then_rewritten_keeps_absent_original(self):
        out = _collapse_rewrites([e("n", None, "B"), e("n", "B", "C")])
        self.assertEqual([(x["sha256_before"], x["sha256_after"]) for x in out], [(None, "C")])

    def test_renames_are_left_alone(self):
        entries = [e("new", "A", "B", renamed_from="old"), e("new", "B", "C")]
        self.assertEqual(_collapse_rewrites(entries), entries)

    def test_single_writes_unchanged(self):
        entries = [e("a", "A", "B"), e("b", "X", "Y")]
        self.assertEqual(_collapse_rewrites(entries), entries)


if __name__ == "__main__":
    unittest.main()
