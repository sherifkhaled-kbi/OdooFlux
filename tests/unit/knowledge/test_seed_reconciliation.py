"""TST-004-006 (REQ-EVD-002, SC-002): every EV and G-R ID in the planning register and the feature
research exists as validated data, with the same claim and the same cited paths."""

import json
import re
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

REPO = Path(__file__).resolve().parents[3]
REGISTER = REPO / "docs" / "planning" / "research" / "OFFICIAL_EVIDENCE_REGISTER.md"
FEATURE_RESEARCH = REPO / "specs" / "004-official-source-intelligence" / "research.md"
PATH_RE = re.compile(r"[\w./-]+\.(?:py|js|xml|rst|json|md|sh)")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_rows(text, header_prefix):
    rows, active = [], False
    for line in text.splitlines():
        if line.startswith(header_prefix):
            active = True
            continue
        if active and line.startswith("|---"):
            continue
        if active and line.startswith("|"):
            rows.append(_cells(line))
        elif active:
            active = False
    return rows


def _norm(text):
    return re.sub(r"[`*_]", "", text).lower()


def register_rows():
    text = REGISTER.read_text(encoding="utf-8")
    rows = _table_rows(text, "| ID | Claim | Source |") + _table_rows(text, "| ID | Claim | Evidence")
    feature = FEATURE_RESEARCH.read_text(encoding="utf-8")
    rows += _table_rows(feature, "| ID | Claim | Evidence")
    return [r for r in rows if r and r[0].startswith("EV-")]


def register_gaps():
    gaps = _table_rows(REGISTER.read_text(encoding="utf-8"), "| ID | Gap |")
    gaps += _table_rows(FEATURE_RESEARCH.read_text(encoding="utf-8"), "| ID | Gap | Blocks |")
    return [g for g in gaps if g and g[0].startswith("G-R-")]


class SeedReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = load_knowledge(KNOWLEDGE_ROOT)
        cls.rows = register_rows()
        cls.gaps = register_gaps()

    def test_count_matches_the_documents(self):
        ids = {r[0] for r in self.rows}
        self.assertEqual(len(ids), 52)  # EV-001..015, EV-101..125, EV-201..212
        self.assertEqual(len({g[0] for g in self.gaps}), 19)  # G-R-01..19

    def test_every_register_id_exists_as_data(self):
        missing = [r[0] for r in self.rows if r[0] not in self.kb.evidence]
        self.assertEqual(missing, [])

    def test_claims_match_the_registered_text(self):
        mismatched = []
        for row in self.rows:
            claim = _norm(row[1])[:24]
            if claim not in _norm(self.kb.evidence[row[0]]["description"]):
                mismatched.append(row[0])
        self.assertEqual(mismatched, [])

    def test_cited_paths_are_present_in_the_locations(self):
        problems = []
        for row in self.rows:
            record = self.kb.evidence[row[0]]
            located = {Path(l["path"]).name for l in record["locations"]}
            cited = {Path(p).name for p in PATH_RE.findall(" ".join(row[1:]))}
            for name in cited:
                if name not in located and not name.startswith("README"):
                    problems.append(f"{row[0]}: {name}")
        self.assertEqual(problems, [])

    def test_every_gap_exists_as_data(self):
        known = {g["id"] for g in self.kb.gaps}
        self.assertEqual([g[0] for g in self.gaps if g[0] not in known], [])

    def test_known_correction_is_recorded(self):
        ev204 = self.kb.evidence["EV-204"]
        self.assertEqual(ev204["status"], "UNVERIFIED")
        self.assertIn("NOT CONFIRMED", ev204["notes"])


if __name__ == "__main__":
    unittest.main()
