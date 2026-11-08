"""TST-004-009 (REQ-EVD-006, FR-009): deterministic output, over-claim refusal, drift detection."""

import json
import unittest

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.matrix import OverclaimError, check_drift, generate

from .helpers import copy_fixture


class MatrixTests(unittest.TestCase):
    def test_two_generations_are_byte_identical(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        self.assertEqual(generate(kb), generate(load_knowledge(KNOWLEDGE_ROOT)))

    def test_rule_marked_rules_tested_without_tests_is_refused(self):
        root = copy_fixture("valid")
        step_path = root / "compatibility" / "16-17.research.json"
        step_path.write_text(json.dumps({
            "step": "16-17", "research_status": "RESEARCH_SEEDED", "revisions": {}, "peer_reviewed": False,
            "notes": "fixture", "review_only": "none", "seeded_evidence": ["EV-001"], "open_gaps": [],
            "categories": {"rules": {"status": "RULES_TESTED", "evidence": ["EV-001"], "gaps": []}}}), encoding="utf-8")
        (root / "compatibility" / "16-17.rules.json").write_text(json.dumps([{
            "id": "16-17.python.name-get-deprecated", "step": "16-17", "category": "python", "maturity": "DETECT_ONLY",
            "risk": "HIGH", "evidence": ["EV-001"], "detector_ref": None, "fixer_ref": None, "tests": []}]),
            encoding="utf-8")
        with self.assertRaisesRegex(OverclaimError, "16-17.python.name-get-deprecated is RULES_TESTED"):
            generate(load_knowledge(root))

    def test_researched_without_peer_review_is_refused(self):
        root = copy_fixture("valid")
        step_path = root / "compatibility" / "16-17.research.json"
        step_path.write_text(json.dumps({
            "step": "16-17", "research_status": "RESEARCHED", "revisions": {}, "peer_reviewed": False,
            "notes": "fixture", "review_only": "none", "seeded_evidence": [], "open_gaps": [], "categories": {}}),
            encoding="utf-8")
        with self.assertRaises(OverclaimError):
            generate(load_knowledge(root))

    def test_hand_edit_is_detected_as_drift(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        text = generate(kb)
        self.assertTrue(check_drift(kb, text))
        self.assertFalse(check_drift(kb, text.replace("RESEARCH_SEEDED", "RESEARCHED", 1)))

    def test_output_has_no_timestamps_and_claims_no_coverage(self):
        text = generate(load_knowledge(KNOWLEDGE_ROOT))
        self.assertNotRegex(text, r"\d{4}-\d{2}-\d{2}T")
        self.assertIn("No coverage percentages are given", " ".join(text.split()))
        self.assertIn("| 12→13 | RESEARCH_SEEDED |", text)


if __name__ == "__main__":
    unittest.main()
