"""Regression tests that cite audit findings (REQ-TST-005, TST-010-002).

F-WALK-1 (the ``.gitignore`` translation was a naive unanchored substring regex without ``!`` negation, leading ``/``
anchors or trailing ``/`` directory patterns) was fixed by 003 T020 in ``discovery/ignore.py``. The behaviour was already
tested in ``tests/unit/test_discovery.py``; this test cites the finding and pins the fixed cases end to end."""

import tempfile
import unittest
from pathlib import Path

from tests.unit import _setup  # noqa: F401

from odooflux.discovery.ignore import IgnoreRules


class FWalk1GitignoreTests(unittest.TestCase):
    """F-WALK-1"""

    def test_f_walk_1_negation(self):
        rules = IgnoreRules(["*.pyc", "!keep.pyc"])
        self.assertTrue(rules.ignored("a.pyc"))
        self.assertFalse(rules.ignored("keep.pyc"))

    def test_f_walk_1_leading_slash_anchors_to_the_root(self):
        rules = IgnoreRules(["/build/"])
        self.assertTrue(rules.ignored("build", True))
        self.assertFalse(rules.ignored("sub/build", True))

    def test_f_walk_1_trailing_slash_matches_directories_only(self):
        rules = IgnoreRules(["tmp/"])
        self.assertTrue(rules.ignored("tmp", True))
        self.assertFalse(rules.ignored("tmp", False))

    def test_f_walk_1_pattern_is_not_an_unanchored_substring(self):
        rules = IgnoreRules(["log"])
        self.assertTrue(rules.ignored("log"))
        self.assertFalse(rules.ignored("catalog.py"))
        self.assertFalse(rules.ignored("logic/rules.py"))


if __name__ == "__main__":
    unittest.main()
