"""Schema check for the golden expected-output review package (stdlib only)."""
import json
import unittest
from pathlib import Path

CASES = Path(__file__).resolve().parents[2] / "knowledge" / "golden_corpus" / "review" / "cases"
REQUIRED = ("case_id", "module", "source_version", "target_version", "steps", "source",
            "applicable_rule_ids", "evidence_ids", "proposed_expected_transformations",
            "unresolved_ambiguities", "review_status", "reviewer", "review_date")


class ReviewPackage(unittest.TestCase):
    def test_cases(self):
        files = sorted(CASES.glob("*.json"))
        self.assertEqual(len(files), 42)
        for p in files:
            c = json.loads(p.read_text())
            for k in REQUIRED:
                self.assertIn(k, c, p.name)
            self.assertEqual(c["case_id"], p.stem)
            self.assertEqual(c["review_status"], "PENDING_INDEPENDENT_REVIEW", p.name)
            self.assertEqual(c["reviewer"], "", p.name)
            self.assertEqual(c["review_date"], "", p.name)
            self.assertTrue(c["source"]["files"] and c["proposed_expected_transformations"], p.name)
            for f in c["source"]["files"]:
                self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("APPROVED", json.dumps(c).replace("PENDING_INDEPENDENT_REVIEW", "").replace("NOT authoritative until APPROVED", ""))


if __name__ == "__main__":
    unittest.main()
