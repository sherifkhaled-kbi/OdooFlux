"""TST-011-064 (REQ-KAP-032): the eight coverage metrics.

Each metric keeps its own explicit numerator and denominator. A zero denominator is NOT_APPLICABLE (never 100 percent).
No blended score exists. Inputs are plain dicts; file accounting documents come from the real `FileAccounting` class.
"""

import unittest

from odooflux.knowledge.coverage import metrics as m
from odooflux.knowledge.extract.accounting import FileAccounting

SS_FROM = "ss-" + "ab" * 6
SS_TO = "ss-" + "cd" * 6


def _accounting(step="16-17", states=None):
    """states: path -> (state, reason_code). Every listed path is a changed file of the pair."""
    states = states or {}
    acc = FileAccounting(step, SS_FROM, SS_TO, {path: "modified" for path in states})
    for path, (state, reason) in states.items():
        acc.set_state(path, state, reason_code=reason)
    return acc.document()


def _change(cid, cls="ADDED", disposition="RULE_CREATED", evidence=(), rules=()):
    return {"change_id": cid, "class": cls, "disposition": disposition,
            "disposition_data": {"evidence_ids": list(evidence), "rule_ids": list(rules)}}


def _inputs(**overrides):
    base = {
        "sources": [
            {"source_id": "odoo-community-17.0", "required": True, "status": "VERIFIED"},
            {"source_id": "oca-web-17.0", "required": False, "status": "FAILED"},
        ],
        "accounting": [_accounting(states={
            "a.py": ("ANALYZED", None), "b.py": ("ANALYZED", None), "c.py": ("ANALYZED", None),
            "d.py": ("EXCLUDED", "OUT_OF_SCOPE_GLOB"), "e.py": ("UNSUPPORTED", "NO_PARSER"),
            "f.py": ("FAILED", "PARSE_ERROR"),
        })],
        "changes": [
            _change("CH-0000000000000001", "ADDED", "RULE_CREATED", evidence=["EV-1"]),
            _change("CH-0000000000000002", "UNKNOWN", "UNRESOLVED"),
            _change("CH-0000000000000003", "MOVED", "NO_CUSTOM_MODULE_IMPACT"),
            _change("CH-0000000000000004", "DEPRECATED", "DETECTION_ONLY", evidence=["EV-404"]),
            _change("CH-0000000000000005", "REMOVED", "EXISTING_RULE_LINKED", evidence=[]),
        ],
        "valid_evidence_ids": ["EV-1"],
        "release_rules": [
            {"id": "R-1", "in_release_delta": True, "validation_passed": True, "origin": "GENERATED",
             "maturity": "DETECT_ONLY", "safety_passed": True},
            {"id": "R-2", "in_release_delta": True, "validation_passed": False, "origin": "GENERATED",
             "maturity": "DRAFT", "safety_passed": True},
            {"id": "B-1", "in_release_delta": False, "validation_passed": True, "origin": None,
             "maturity": "FIX_ENABLED", "safety_passed": False},
            {"id": "R-3", "in_release_delta": False, "validation_passed": True, "origin": "GENERATED",
             "maturity": "FIX_ENABLED", "safety_passed": True},
            {"id": "R-4", "in_release_delta": False, "validation_passed": True, "origin": "GENERATED",
             "maturity": "FIX_ENABLED", "safety_passed": False},
        ],
        "declared_transitions": [
            {"step": "16-17", "sources_verified": True, "accounting_complete": True, "ledger_present": True},
            {"step": "17-18", "sources_verified": True, "accounting_complete": False, "ledger_present": True},
        ],
    }
    base.update(overrides)
    return base


def _by_id(result):
    return {item["id"]: item for item in result}


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.metrics = _by_id(m.compute_metrics(_inputs()))

    def test_metric_m1(self):
        # required sources: 1 declared, 1 verified; the optional failed source is not in the denominator
        item = self.metrics["M1"]
        self.assertEqual((item["numerator"], item["denominator"]), (1, 1))
        self.assertEqual(item["name"], "source_retrieval")

    def test_metric_m2(self):
        # numerator ANALYZED; denominator is every changed file of the pairs (sum of states, INV-3)
        item = self.metrics["M2"]
        self.assertEqual((item["numerator"], item["denominator"]), (3, 6))
        self.assertEqual(item["breakdown"], {"excluded": 1, "unsupported": 1, "failed": 1, "pending": 0})

    def test_metric_m3(self):
        # numerator: changes whose class is not UNKNOWN; denominator: all changes
        item = self.metrics["M3"]
        self.assertEqual((item["numerator"], item["denominator"]), (4, 5))

    def test_metric_m4(self):
        # numerator: changes whose disposition is not UNRESOLVED
        item = self.metrics["M4"]
        self.assertEqual((item["numerator"], item["denominator"]), (4, 5))

    def test_metric_m5(self):
        # changes needing evidence: RULE_CREATED, EXISTING_RULE_LINKED, DETECTION_ONLY (3). Only CH-...1 has a valid
        # evidence id; the others cite none or an invalid one.
        item = self.metrics["M5"]
        self.assertEqual((item["numerator"], item["denominator"]), (1, 3))

    def test_metric_m6(self):
        # release rules new or changed in this release: R-1, R-2; R-1 passes validation
        item = self.metrics["M6"]
        self.assertEqual((item["numerator"], item["denominator"]), (1, 2))

    def test_metric_m7(self):
        # FIX_ENABLED rules in release, built-in rows excluded (B-1 counted separately): R-3, R-4; R-3 passes G-SAFE
        item = self.metrics["M7"]
        self.assertEqual((item["numerator"], item["denominator"]), (1, 2))
        self.assertEqual(item["breakdown"]["builtin_grandfathered"], 1)

    def test_metric_m8(self):
        # declared transitions: 2; only 16-17 has verified sources, complete accounting and a ledger
        item = self.metrics["M8"]
        self.assertEqual((item["numerator"], item["denominator"]), (1, 2))

    def test_version_transition_not_from_rules(self):
        # every release rule passes validation, yet the transition set is incomplete: M8 must not follow the rules
        data = _inputs(release_rules=[{"id": "R-9", "in_release_delta": True, "validation_passed": True,
                                       "origin": "GENERATED", "maturity": "DETECT_ONLY", "safety_passed": True}])
        result = _by_id(m.compute_metrics(data))
        self.assertEqual(result["M6"]["numerator"], result["M6"]["denominator"])
        self.assertLess(result["M8"]["numerator"], result["M8"]["denominator"])

    def test_zero_denominator_not_applicable(self):
        data = _inputs(changes=[], valid_evidence_ids=[], release_rules=[], declared_transitions=[], sources=[],
                       accounting=[])
        result = _by_id(m.compute_metrics(data))
        for metric_id in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"):
            item = result[metric_id]
            self.assertEqual(item["denominator"], 0, metric_id)
            self.assertEqual(item["numerator"], 0, metric_id)
            self.assertEqual(item["status"], "NOT_APPLICABLE", metric_id)
            self.assertIsNone(item["per_mille"], metric_id)

    def test_no_blended_score(self):
        result = m.compute_metrics(_inputs())
        self.assertEqual([item["id"] for item in result], [f"M{i}" for i in range(1, 9)])
        for item in result:
            self.assertEqual(set(item), {"id", "name", "numerator", "denominator", "status",
                                         "denominator_definition", "per_mille", "breakdown"})
            self.assertIsInstance(item["numerator"], int)
            self.assertIsInstance(item["denominator"], int)
            self.assertLessEqual(item["numerator"], item["denominator"])
        self.assertFalse(any(name.startswith(("overall", "score", "blended")) for name in dir(m)))

    def test_per_mille_is_integer_and_line_shows_fraction(self):
        item = _by_id(m.compute_metrics(_inputs()))["M2"]
        self.assertEqual(item["per_mille"], 500)
        line = m.format_line(item)
        self.assertIn("3/6", line)
        self.assertIn("excluded=1", line)
        self.assertIn("unsupported=1", line)
        self.assertIn("failed=1", line)
        self.assertIn("pending=0", line)
        na = _by_id(m.compute_metrics(_inputs(release_rules=[])))["M6"]
        self.assertIn("NOT_APPLICABLE", m.format_line(na))
        self.assertNotIn("%", m.format_line(na))


if __name__ == "__main__":
    unittest.main()
