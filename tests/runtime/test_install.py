"""TST-008-006 (REQ-VAL-004, REQ-ACL-002, FR-004, FR-006, FR-007; SC-002): install fixtures on a real runtime.

Opt-in: ODOOFLUX_RUNTIME_TESTS=1. Uses odoo:19.0 (digest-pinned from the local daemon) and the postgres image named
in runtime_images.json. Each test removes every labelled resource it created (SC-003)."""

import unittest

from ._support import RUNTIME, any_labelled_containers, fixture, labelled_resources, remove_state, state_dir
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime import pipeline
from odooflux.validation.status import StatusInputs, decide

TARGET = "19.0"


@RUNTIME
class InstallFixtureTests(unittest.TestCase):
    def setUp(self):
        self.env = de.DockerEnvironment()
        self.state = state_dir()
        self.addCleanup(remove_state, self.state)

    def assert_no_leftovers(self, outcome):
        for run in outcome.runs:
            containers, volumes = labelled_resources(run.run_id)
            self.assertEqual((containers, volumes), ([], []), f"leftovers for run {run.run_id}")

    def test_install_ok_is_pass_and_reaches_install_verified(self):
        outcome = pipeline.run_install([fixture("install_ok")], TARGET, self.env, de.Limits(), self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (4, "PASS"), outcome.result.reason)
        self.assertEqual(outcome.runs[0].errors, [])
        self.assertEqual(outcome.warnings, [])
        # L1-L3 are not run by this test; they are taken as PASS to exercise the L4 part of the decision.
        decision = decide(StatusInputs(layers={1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS"}))
        self.assertEqual(decision.status, "INSTALL_VERIFIED")
        self.assert_no_leftovers(outcome)

    def test_broken_view_is_fail_with_view_validation_attributed_to_the_view_file(self):
        outcome = pipeline.run_install([fixture("broken_view")], TARGET, self.env, de.Limits(), self.state)
        self.assertEqual(outcome.result.outcome, "FAIL", outcome.result.reason)
        classes = [e.error_class for e in outcome.errors]
        self.assertIn("view_validation", classes)
        view = next(e for e in outcome.errors if e.error_class == "view_validation")
        self.assertEqual(view.file, "broken_view/views/fixture_views.xml")
        self.assertTrue(outcome.result.reason.startswith("install failed: view_validation"), outcome.result.reason)
        self.assertEqual(decide(StatusInputs(layers={1: "PASS", 2: "PASS", 3: "PASS", 4: "FAIL"})).status, "FAILED")
        self.assert_no_leftovers(outcome)

    def test_acl_missing_model_is_fail_with_access_rights(self):
        outcome = pipeline.run_install([fixture("acl_missing_model")], TARGET, self.env, de.Limits(), self.state)
        self.assertEqual(outcome.result.outcome, "FAIL", outcome.result.reason)
        self.assertTrue(outcome.result.reason.startswith("install failed: access_rights"), outcome.result.reason)
        acl = next(e for e in outcome.errors if e.error_class == "access_rights")
        self.assertEqual(acl.file, "acl_missing_model/security/ir.model.access.csv")
        self.assert_no_leftovers(outcome)

    def test_enterprise_dependency_is_skipped_and_no_container_is_started(self):
        outcome = pipeline.run_install([fixture("enterprise_dep")], TARGET, self.env, de.Limits(), self.state)
        self.assertEqual((outcome.result.outcome, outcome.result.reason), ("SKIPPED", "enterprise_dependency"))
        self.assertEqual(outcome.runs, [])
        self.assertEqual(any_labelled_containers(), [])
        self.assertEqual(outcome.warnings, [])


if __name__ == "__main__":
    unittest.main()
