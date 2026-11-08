"""TST-006-033 (REQ-PY-002, REQ-EVD-003, FR-015): every legacy rule row has a recorded disposition (68/68)."""

import json
import re
import unittest
from collections import Counter

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

from .. import _setup  # noqa: F401

DISPOSITIONS = ("keep", "correct", "retire", "needs-research")
EXPECTED_REFS = (
    [f"PYTHON_RULES#{n}" for n in range(1, 30)] + [f"XML_RULES#{n}" for n in range(1, 22)]
    + [f"MANIFEST_RULES#M{n}" for n in range(1, 5)] + [f"JS_TS_RULES#J{n}" for n in range(1, 7)]
    + [f"CSS_RULES#C{n}" for n in range(1, 3)] + [f"VERSION_RULES#V18-{n}" for n in range(1, 6)]
    + ["VERSION_RULES#V19-1"])
DOC = KNOWLEDGE_ROOT.parents[2] / "docs" / "planning" / "MIGRATION_RULE_ENGINE.md"


class LegacyDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = KNOWLEDGE_ROOT / "compatibility" / "legacy_disposition.json"
        cls.data = json.loads(path.read_text(encoding="utf-8"))
        cls.rows = cls.data  # a flat list (data-model.md RetiredRule)
        cls.kb = load_knowledge()

    def test_every_legacy_row_is_present(self):
        refs = [r["legacy_ref"] for r in self.rows]
        self.assertEqual(sorted(refs), sorted(EXPECTED_REFS))
        self.assertEqual(len(set(refs)), 68)
        print(f"legacy dispositions: {len(set(refs) & set(EXPECTED_REFS))}/{len(EXPECTED_REFS)}")

    def test_dispositions_are_valid_and_only_research_results_change_the_planning_totals(self):
        self.assertTrue(all(r["disposition"] in DISPOSITIONS for r in self.rows))
        baseline = {"keep": 1, "correct": 16, "retire": 29, "needs-research": 22}   # planning document totals
        actual = Counter(r["disposition"] for r in self.rows)
        self.assertEqual(sum(actual.values()), 68)
        researched = [r for r in self.rows if r.get("researched_by")]
        for row in researched:
            self.assertTrue(row["evidence"], row["legacy_ref"])   # a changed disposition cites evidence
        if not researched:
            self.assertEqual(actual, baseline)
        self.assertLessEqual(actual["needs-research"], baseline["needs-research"])

    def test_rows_match_the_document_table(self):
        if not DOC.is_file():
            self.skipTest("planning document not present")
        text = DOC.read_text(encoding="utf-8")
        table = re.findall(r"^\| ((?:\d+|[MJCV]\d+(?:-\d+)?)) \| .*? \| (keep|correct|retire|needs-research) \|",
                           text, re.M)
        self.assertEqual(len(table), 68)
        researched = sum(1 for r in self.rows if r.get("researched_by"))
        differing = sum((Counter(d for _n, d in table) - Counter(r["disposition"] for r in self.rows)).values())
        self.assertLessEqual(differing, researched)

    def test_every_row_has_a_reason(self):
        for row in self.rows:
            self.assertTrue(row["reason"].strip(), row["legacy_ref"])

    def test_ported_rows_name_existing_rules(self):
        known = {r["id"] for r in self.kb.rules}
        for row in self.rows:
            for rid in row["new_rule_ids"]:
                self.assertIn(rid, known, row["legacy_ref"])
            if row["disposition"] == "keep":
                self.assertTrue(row["new_rule_ids"], row["legacy_ref"])

    def test_evidence_and_gaps_exist(self):
        gaps = {g["id"] for g in self.kb.gaps}
        for row in self.rows:
            for ev in row["evidence"]:
                self.assertIn(ev, self.kb.evidence, row["legacy_ref"])
            if row["gap"] is not None:
                self.assertIn(row["gap"], gaps, row["legacy_ref"])

    def test_needs_research_rows_are_pending_and_have_a_gap_or_evidence(self):
        for row in self.rows:
            if row["disposition"] == "needs-research":
                self.assertEqual(row["status"], "PENDING", row["legacy_ref"])
                self.assertTrue(row["gap"] or row["evidence"], row["legacy_ref"])


if __name__ == "__main__":
    unittest.main()
