"""TST-008-007 (REQ-SEC-002, FR-005; SC-002, SC-003): the wall-time limit kills a non-terminating install.

Opt-in: ODOOFLUX_RUNTIME_TESTS=1. The install_loop fixture never returns from its post_init hook. The limit is 60 s
(documented in quickstart.md, Measured baseline). The run must end within the limit plus a teardown grace, be
classified timeout, and leave no labelled container or volume behind."""

import time
import unittest

from ._support import RUNTIME, any_labelled_containers, fixture, labelled_resources, remove_state, state_dir
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime import pipeline
from odooflux.validation.status import StatusInputs, decide

WALL_TIME_S = 60
GRACE_S = 60


@RUNTIME
class WallTimeLimitTests(unittest.TestCase):
    def setUp(self):
        self.state = state_dir()
        self.addCleanup(remove_state, self.state)

    def test_install_loop_is_killed_at_the_limit_and_nothing_is_left_behind(self):
        env = de.DockerEnvironment()
        started = time.monotonic()
        outcome = pipeline.run_install([fixture("install_loop")], "19.0", env, de.Limits(wall_time_s=WALL_TIME_S),
                                       self.state)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, WALL_TIME_S + GRACE_S, f"run took {elapsed:.1f}s")
        self.assertEqual(outcome.result.outcome, "FAIL", outcome.result.reason)
        self.assertTrue(outcome.result.reason.startswith("install failed: timeout"), outcome.result.reason)
        self.assertEqual(outcome.runs[0].killed_reason, "timeout")
        self.assertEqual(outcome.runs[0].exit_code, 137)
        self.assertEqual(decide(StatusInputs(layers={1: "PASS", 2: "PASS", 3: "PASS", 4: "FAIL"})).status, "FAILED")
        for run in outcome.runs:
            self.assertEqual(labelled_resources(run.run_id), ([], []))
        self.assertEqual(any_labelled_containers(), [])
        self.assertEqual(outcome.warnings, [])


if __name__ == "__main__":
    unittest.main()
