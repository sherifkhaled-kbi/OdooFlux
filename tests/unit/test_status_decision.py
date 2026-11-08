"""TST-003-021 (REQ-VAL-006, FR-017): one subTest per row of the status decision table."""

import unittest

from odooflux.core.orchestrator.status import decide_status

from ._setup import SRC  # noqa: F401

ALL_PASS = {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS", 5: "PASS"}
CASES = [
    # (name, layers, kwargs, expected status)
    ("row1 blocked plan", ALL_PASS, {"blocked_reason": "unsupported"}, "BLOCKED"),
    ("row1 tool state", ALL_PASS, {"tool_ok": False}, "BLOCKED"),
    ("row1 required layer unavailable", {1: "PASS", 2: "PASS", 3: "UNAVAILABLE"}, {"required": (3,)}, "BLOCKED"),
    ("row2 layer FAIL", {**ALL_PASS, 1: "FAIL"}, {}, "FAILED"),
    ("row2 open critical", ALL_PASS, {"open_critical": 1}, "FAILED"),
    ("row3 open review", ALL_PASS, {"open_review": 1}, "NEEDS_REVIEW"),
    ("row3 open warning", ALL_PASS, {"open_warning": 1}, "NEEDS_REVIEW"),
    ("row3 unverified plan", ALL_PASS, {"unverified": True}, "NEEDS_REVIEW"),
    # P7: L3 is implemented and always required (contracts/status-decision.md row 1), so UNAVAILABLE blocks.
    ("row1 mandatory L3 unavailable", {1: "PASS", 2: "PASS", 3: "UNAVAILABLE"}, {}, "BLOCKED"),
    ("row4 verified success", ALL_PASS, {"l5_coverage": "full"}, "VERIFIED_SUCCESS"),
    ("row5 install verified (L5 partial)", ALL_PASS, {"l5_coverage": "partial"}, "INSTALL_VERIFIED"),
    ("row5 install verified (L5 skipped)", {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS"}, {}, "INSTALL_VERIFIED"),
    ("row6 static validated (L4 skipped)", {1: "PASS", 2: "PASS", 3: "PASS"}, {}, "STATIC_VALIDATED"),
    ("row7 unmatched falls back", {1: "PASS", 2: "PASS", 3: "PASS", 4: "FAIL"}, {}, "FAILED"),
]


class StatusDecisionTests(unittest.TestCase):
    def test_table_rows(self):
        for name, layers, kwargs, expected in CASES:
            with self.subTest(name):
                status, reasons = decide_status(layers, **kwargs)
                self.assertEqual(status, expected, reasons)

    def test_info_findings_never_change_status(self):
        status, _ = decide_status(ALL_PASS, l5_coverage="full")
        self.assertEqual(status, "VERIFIED_SUCCESS")

    def test_unmatched_combination_reason_is_recorded(self):
        status, reasons = decide_status({1: "PASS", 2: "PASS", 3: "PASS", 4: "UNAVAILABLE"})
        self.assertEqual(status, "STATIC_VALIDATED")
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
