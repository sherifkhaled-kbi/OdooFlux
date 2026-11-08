"""TST-008-001 (REQ-VAL-006, FR-001, SC-001): every row of contracts/status-decision.md and a combinatorial sweep.

The oracle below is written from the contract text, independently of the implementation under test."""

import itertools
import unittest

from odooflux.validation.status import StatusInputs, decide

from .._setup import SRC  # noqa: F401

LAYER_OUTCOMES = ("PASS", "FAIL", "UNAVAILABLE", "SKIPPED")


def oracle(layers, coverage, *, plan_state="ok", tool_state="ok", open_critical=0, open_warning=0, open_review=0,
           sub_validator_unavailable=0):
    """Expected (status, row) for valid inputs, per contracts/status-decision.md (first matching row wins)."""
    plan, tool, sub = plan_state, tool_state, sub_validator_unavailable
    L = {n: layers.get(n, "SKIPPED") for n in range(1, 6)}
    if plan == "refused" or tool != "ok" or any(L[n] in ("UNAVAILABLE", "SKIPPED") for n in (1, 2, 3)):
        return "BLOCKED", 1
    if any(L[n] == "FAIL" for n in range(1, 6)) or open_critical > 0:
        return "FAILED", 2
    if open_review > 0 or open_warning > 0 or plan == "unverified_allowed" or sub > 0:
        return "NEEDS_REVIEW", 3
    if all(L[n] == "PASS" for n in (1, 2, 3, 4)) and L[5] == "PASS" and coverage == "full":
        return "VERIFIED_SUCCESS", 4
    if all(L[n] == "PASS" for n in (1, 2, 3, 4)):
        return "INSTALL_VERIFIED", 5
    if all(L[n] == "PASS" for n in (1, 2, 3)):
        return "STATIC_VALIDATED", 6
    return "NEEDS_REVIEW", 7


ALL_PASS = {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS", 5: "PASS"}
ROW_CASES = [
    ("row1 refused plan", ALL_PASS, None, {"plan_state": "refused"}, "BLOCKED", 1),
    ("row1 tool state", ALL_PASS, None, {"tool_state": "workspace_failed"}, "BLOCKED", 1),
    ("row1 required L3 unavailable", {1: "PASS", 2: "PASS", 3: "UNAVAILABLE"}, None, {}, "BLOCKED", 1),
    ("row1 required L2 skipped", {1: "PASS", 2: "SKIPPED", 3: "PASS"}, None, {}, "BLOCKED", 1),
    ("row2 layer FAIL", {**ALL_PASS, 1: "FAIL"}, "full", {}, "FAILED", 2),
    ("row2 L5 FAIL", {**ALL_PASS, 5: "FAIL"}, "full", {}, "FAILED", 2),
    ("row2 open critical", ALL_PASS, "full", {"open_critical": 1}, "FAILED", 2),
    ("row3 open review", ALL_PASS, "full", {"open_review": 1}, "NEEDS_REVIEW", 3),
    ("row3 open warning", ALL_PASS, "full", {"open_warning": 1}, "NEEDS_REVIEW", 3),
    ("row3 unverified plan", ALL_PASS, "full", {"plan_state": "unverified_allowed"}, "NEEDS_REVIEW", 3),
    ("row3 JS adapter unavailable", {1: "PASS", 2: "PASS", 3: "PASS", 4: "SKIPPED"}, None,
     {"sub_validator_unavailable": 1}, "NEEDS_REVIEW", 3),
    ("row4 verified success", ALL_PASS, "full", {}, "VERIFIED_SUCCESS", 4),
    ("row5 install verified (L5 partial)", ALL_PASS, "partial", {}, "INSTALL_VERIFIED", 5),
    ("row5 install verified (L5 unavailable)", {**ALL_PASS, 5: "UNAVAILABLE"}, None, {}, "INSTALL_VERIFIED", 5),
    ("row5 install verified (L5 absent)", {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS"}, None, {}, "INSTALL_VERIFIED", 5),
    ("row6 static validated (L4 skipped)", {1: "PASS", 2: "PASS", 3: "PASS"}, None, {}, "STATIC_VALIDATED", 6),
    ("row6 static validated (L4 unavailable)", {1: "PASS", 2: "PASS", 3: "PASS", 4: "UNAVAILABLE"}, None, {},
     "STATIC_VALIDATED", 6),
]


class StatusDecisionTableTests(unittest.TestCase):
    def test_every_row(self):
        for name, layers, coverage, extra, status, row in ROW_CASES:
            with self.subTest(name):
                kwargs = dict(layers=layers, l5_coverage=coverage, **extra)
                decision = decide(StatusInputs(**kwargs))
                self.assertEqual((decision.status, decision.row), (status, row), decision.reasons)
                self.assertEqual(oracle(layers, coverage, **extra), (status, row))

    def test_row7_is_unreachable_for_valid_inputs(self):
        for layers, coverage, plan, tool, crit, warn, rev, sub in self._sweep():
            with self.subTest(layers=layers, coverage=coverage, plan=plan, tool=tool):
                decision = decide(StatusInputs(layers=layers, l5_coverage=coverage, plan_state=plan,
                                               tool_state=tool, open_critical=crit, open_warning=warn,
                                               open_review=rev, sub_validator_unavailable=sub))
                self.assertNotEqual(decision.row, 7)

    def test_combinatorial_sweep_matches_oracle(self):
        count = 0
        for layers, coverage, plan, tool, crit, warn, rev, sub in self._sweep():
            count += 1
            expected = oracle(layers, coverage, plan_state=plan, tool_state=tool, open_critical=crit,
                              open_warning=warn, open_review=rev, sub_validator_unavailable=sub)
            decision = decide(StatusInputs(layers=layers, l5_coverage=coverage, plan_state=plan,
                                           tool_state=tool, open_critical=crit, open_warning=warn,
                                           open_review=rev, sub_validator_unavailable=sub))
            self.assertEqual((decision.status, decision.row), expected, (layers, coverage, plan, tool))
        self.assertGreater(count, 10000)

    def _sweep(self):
        l5_values = [("PASS", "full"), ("PASS", "partial"), ("FAIL", None), ("UNAVAILABLE", None), ("SKIPPED", None)]
        for o1, o2, o3, o4 in itertools.product(LAYER_OUTCOMES, repeat=4):
            for o5, cov in l5_values:
                layers = {1: o1, 2: o2, 3: o3, 4: o4, 5: o5}
                for plan, tool in (("ok", "ok"), ("unverified_allowed", "ok"), ("refused", "ok"), ("ok", "tool_error")):
                    for crit, warn, rev, sub in itertools.product((0, 1), repeat=4):
                        yield layers, cov, plan, tool, crit, warn, rev, sub

    def test_information_findings_do_not_change_status(self):
        decision = decide(StatusInputs(layers=ALL_PASS, l5_coverage="full"))
        self.assertEqual(decision.status, "VERIFIED_SUCCESS")

    def test_unknown_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            decide(StatusInputs(layers={1: "OK"}))
        with self.assertRaises(ValueError):
            decide(StatusInputs(layers=ALL_PASS, l5_coverage="maybe"))

    def test_decision_carries_an_inputs_digest(self):
        a = decide(StatusInputs(layers=ALL_PASS, l5_coverage="full"))
        b = decide(StatusInputs(layers=ALL_PASS, l5_coverage="partial"))
        self.assertEqual(len(a.inputs_digest), 64)
        self.assertNotEqual(a.inputs_digest, b.inputs_digest)


if __name__ == "__main__":
    unittest.main()
