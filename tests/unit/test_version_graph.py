"""TST-003-008 (REQ-VER-002): every ordered pair among 12.0–19.0 yields consecutive steps."""

import itertools
import unittest

from odooflux.core.contracts import UnsupportedVersionError
from odooflux.versions.graph.graph import VersionGraph, normalize
from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data

from ._setup import SRC  # noqa: F401


class VersionGraphTests(unittest.TestCase):
    def setUp(self):
        versions, transitions = load_version_data(KNOWLEDGE_FILE)
        self.graph = VersionGraph(versions, transitions)
        self.order = self.graph.versions

    def test_all_28_pairs_give_consecutive_steps(self):
        pairs = list(itertools.combinations(self.order, 2))
        self.assertEqual(len(pairs), 28)
        for s, t in pairs:
            steps = self.graph.steps(s, t)
            i, j = self.order.index(s), self.order.index(t)
            self.assertEqual([(x.source, x.target) for x in steps],
                             list(zip(self.order[i:j], self.order[i + 1:j + 1])))

    def test_source_not_lower_than_target_raises(self):
        with self.assertRaises(UnsupportedVersionError):
            self.graph.steps("14.0", "14.0")
        with self.assertRaises(UnsupportedVersionError):
            self.graph.steps("16.0", "14.0")

    def test_unknown_version_raises(self):
        with self.assertRaises(UnsupportedVersionError):
            self.graph.steps("14.0", "99.0")

    def test_normalize_accepts_both_forms(self):
        self.assertEqual(normalize("14"), "14.0")
        self.assertEqual(normalize("14.0"), "14.0")
        with self.assertRaises(UnsupportedVersionError):
            normalize("fourteen")


if __name__ == "__main__":
    unittest.main()
