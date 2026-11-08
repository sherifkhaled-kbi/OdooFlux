"""TST-004-010 (REQ-EVD-006, SC-005): the committed matrix equals the generated output, and the
statuses and evidence IDs in it match the planning matrix it replaced."""

import re
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.matrix import generate

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "docs" / "planning" / "VERSION_COMPATIBILITY_MATRIX.md"


class MatrixCommittedTests(unittest.TestCase):
    def test_committed_matrix_matches_generated(self):
        self.assertEqual(COMMITTED.read_text(encoding="utf-8"), generate(load_knowledge(KNOWLEDGE_ROOT)))

    def test_statuses_and_evidence_ids_survive_regeneration(self):
        text = COMMITTED.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^\| \d+→\d+ \| (RESEARCH_SEEDED|NOT_ASSESSED) \|", text, re.M)), 8)
        self.assertIn("| 12→13 | EV-101, EV-103, EV-125, EV-205, EV-206, EV-211 |", text)
        self.assertIn("| 16→17 | EV-011, EV-012, EV-108, EV-109, EV-110, EV-111, EV-117, EV-125, EV-207 |", text)


if __name__ == "__main__":
    unittest.main()
