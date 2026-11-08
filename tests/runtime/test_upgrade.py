"""TST-008-008 (REQ-VAL-004; FR-004): install, then upgrade (-u) of the same module on the same database handle.

Opt-in: ODOOFLUX_RUNTIME_TESTS=1. The upgrade outcome is recorded as an L4 sub-result (sub_results['upgrade'])."""

import unittest
from pathlib import Path

from ._support import RUNTIME, fixture, labelled_resources, remove_state, state_dir
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime import pipeline


@RUNTIME
class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.state = state_dir()
        self.addCleanup(remove_state, self.state)

    def test_install_then_upgrade_on_the_same_handle_is_pass_with_both_sub_results(self):
        outcome = pipeline.run_install([fixture("install_ok")], "19.0", de.DockerEnvironment(), de.Limits(),
                                       self.state, upgrade=True)
        try:
            self.assertEqual(outcome.sub_results["install"].outcome, "PASS")
            self.assertEqual(outcome.sub_results["upgrade"].outcome, "PASS", outcome.sub_results["upgrade"].reason)
            self.assertEqual(outcome.result.outcome, "PASS")
            self.assertEqual([run.step for run in outcome.runs], ["install", "upgrade"])
            self.assertEqual(len({run.run_id for run in outcome.runs}), 1, "both steps share one run")
            upgrade_log = Path(outcome.runs[1].log_path).read_text(encoding="utf-8")
            self.assertIn("loading install_ok", upgrade_log)
            self.assertEqual([line for line in upgrade_log.splitlines() if " ERROR " in line], [])
        finally:
            for run in outcome.runs:
                self.assertEqual(labelled_resources(run.run_id), ([], []))


if __name__ == "__main__":
    unittest.main()
