"""TST-008-010 (REQ-BIZ-002, REQ-BIZ-003, FR-008; SC-004, SC-005): the behavioural fixture on a source and a target.

Opt-in: ODOOFLUX_RUNTIME_TESTS=1. Source odoo:18.0 (baseline), target odoo:19.0. Expected: exactly one regression
(test_regression), one pre-existing failure (test_fail_both), one pass on both (test_pass_both). L5 is FAIL. Without a
source baseline the coverage is partial and the status is never VERIFIED_SUCCESS."""

import unittest

from ._support import RUNTIME, fixture, labelled_resources, remove_state, state_dir
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime import pipeline
from odooflux.validation.status import StatusInputs, decide

MODULE = "behavior_compare"
REGRESSION = f"{MODULE}.TestBehavior.test_regression"
FAIL_BOTH = f"{MODULE}.TestBehavior.test_fail_both"
PASS_BOTH = f"{MODULE}.TestBehavior.test_pass_both"


@RUNTIME
class BehaviourFixtureTests(unittest.TestCase):
    def setUp(self):
        self.state = state_dir()
        self.addCleanup(remove_state, self.state)

    def assert_no_leftovers(self, outcome):
        for run in outcome.runs:
            self.assertEqual(labelled_resources(run.run_id), ([], []), f"leftovers for run {run.run_id}")

    def test_18_to_19_gives_one_regression_one_pre_existing_failure_and_one_pass_both(self):
        outcome = pipeline.run_behavior([fixture(MODULE)], MODULE, "19.0", de.DockerEnvironment(), de.Limits(),
                                        self.state, source_version="18.0")
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (5, "FAIL"), outcome.result.reason)
        self.assertEqual(outcome.classifications["regression"], [REGRESSION])
        self.assertEqual(outcome.classifications["fail_both"], [FAIL_BOTH])
        self.assertEqual(outcome.classifications["pass_both"], [PASS_BOTH])
        self.assertIn("test_regression", outcome.result.reason)
        self.assertNotIn("test_pass_both", outcome.result.reason)
        self.assertEqual(outcome.result.coverage, "full")
        self.assert_no_leftovers(outcome)

    def test_without_a_source_baseline_coverage_is_partial_and_never_verified_success(self):
        outcome = pipeline.run_behavior([fixture(MODULE)], MODULE, "19.0", de.DockerEnvironment(), de.Limits(),
                                        self.state)
        self.assertEqual(outcome.result.coverage, "partial")
        self.assertIn("no baseline", outcome.result.reason)
        # The target fixture has failing tests and there is no baseline, so L5 is FAIL (brief rule: PASS only when no
        # target test fails without a baseline). The decision is FAILED, which is below VERIFIED_SUCCESS.
        self.assertEqual(outcome.result.outcome, "FAIL", outcome.result.reason)
        decision = decide(StatusInputs(layers={1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS",
                                               5: outcome.result.outcome}, l5_coverage="partial"))
        self.assertEqual(decision.status, "FAILED")
        self.assert_no_leftovers(outcome)


if __name__ == "__main__":
    unittest.main()
