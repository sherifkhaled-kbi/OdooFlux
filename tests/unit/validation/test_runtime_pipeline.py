"""TST-008-006/009 support and T019 (REQ-VAL-004, REQ-VAL-006, FR-004, FR-008): pipeline behaviour without Docker.

A recording fake stands in for the Docker adapter. The Enterprise and missing-image paths must never call the
environment at all: the test environment below fails the test if it is touched.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from .._setup import SRC  # noqa: F401  (puts src/ first on sys.path)
from odooflux.validation.runtime import docker_env as de
from odooflux.validation.runtime import pipeline
from odooflux.validation.runtime.log_classifier import ClassifiedError
from odooflux.validation.status import StatusInputs, decide

ROOT = Path(__file__).resolve().parents[2] / "golden_fixtures" / "runtime"
LOGS = ROOT / "logs" / "behavior"
LIMITS = de.Limits()


class TouchedDocker(AssertionError):
    pass


class NoDockerEnvironment:
    """Any call fails the test: the path under test must not start or inspect Docker."""
    name = "docker"
    contract_version = 1

    def available(self):
        raise TouchedDocker("available() was called")

    def prepare(self, *args, **kwargs):
        raise TouchedDocker("prepare() was called")

    def install(self, *args, **kwargs):
        raise TouchedDocker("install() was called")

    def upgrade(self, *args, **kwargs):
        raise TouchedDocker("upgrade() was called")

    def run_tests(self, *args, **kwargs):
        raise TouchedDocker("run_tests() was called")

    def teardown(self, *args, **kwargs):
        raise TouchedDocker("teardown() was called")


class FakeEnvironment:
    """Recording environment with canned results. Each install/upgrade/test returns a RuntimeRun."""
    name = "docker"
    contract_version = 1

    def __init__(self, available=(True, "docker server test"), prepare_error=None, install_errors=(),
                 upgrade_errors=(), test_log=None, killed=None, install_raises=None):
        self._available = available
        self.prepare_error = prepare_error
        self.install_errors = list(install_errors)
        self.upgrade_errors = list(upgrade_errors)
        self.test_log = test_log
        self.killed = killed
        self.install_raises = install_raises
        self.torn_down = []
        self.prepared = []
        self.tmp = Path(tempfile.mkdtemp(prefix="odooflux-fake-env-"))

    def _run(self, handle, step, errors, log_text=""):
        log_path = self.tmp / f"{step}.log"
        log_path.write_text(log_text, encoding="utf-8")
        return de.RuntimeRun(run_id=handle.run_id, step=step, version=handle.version, image=handle.image,
                             postgres_image=handle.postgres_image, container=f"c-{step}",
                             exit_code=1 if errors else 0, duration_ms=1, log_path=str(log_path),
                             log_excerpt="", errors=list(errors), killed_reason=None, limits=handle.limits)

    def available(self):
        return self._available

    def prepare(self, version, modules_ro_path, limits, *, state_dir):
        if self.prepare_error:
            raise self.prepare_error
        self.prepared.append(version)
        return de.EnvHandle(run_id="rfake00000000", version=version, image="odoo@sha256:" + "a" * 64,
                            postgres_image="postgres@sha256:" + "b" * 64, socket_volume="s", data_volume="d",
                            modules=tuple((str(p), Path(p).name) for p in modules_ro_path), limits=limits,
                            state_dir=str(state_dir), postgres_container="pg")

    def install(self, handle, names):
        if self.install_raises:
            raise self.install_raises
        return self._run(handle, "install", self.install_errors)

    def upgrade(self, handle, names):
        return self._run(handle, "upgrade", self.upgrade_errors)

    def run_tests(self, handle, names, tags):
        run = self._run(handle, "tests", [], log_text=Path(self.test_log).read_text(encoding="utf-8")
                        if self.test_log else "")
        if self.killed:
            run.killed_reason = self.killed
        return run

    def teardown(self, handle):
        self.torn_down.append(handle.run_id)
        return []


def module(name):
    return ROOT / name


class EnterpriseAndImageTests(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix="odooflux-pipeline-"))
        self.addCleanup(shutil.rmtree, self.state, True)

    def test_enterprise_dependency_skips_l4_and_never_touches_docker(self):
        outcome = pipeline.run_install([module("enterprise_dep")], "19.0", NoDockerEnvironment(), LIMITS, self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (4, "SKIPPED"))
        self.assertEqual(outcome.result.reason, "enterprise_dependency")
        self.assertTrue(any("sale_subscription" in note for note in outcome.notes))

    def test_enterprise_dependency_on_layer_5_is_also_skipped(self):
        outcome = pipeline.run_behavior([module("enterprise_dep")], "enterprise_dep", "19.0",
                                        NoDockerEnvironment(), LIMITS, self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome, outcome.result.reason),
                         (5, "SKIPPED", "enterprise_dependency"))

    def test_version_without_runtime_image_is_unavailable_image_unavailable_without_docker(self):
        outcome = pipeline.run_install([module("install_ok")], "17.0", NoDockerEnvironment(), LIMITS, self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (4, "UNAVAILABLE"))
        self.assertEqual(outcome.result.reason, "image_unavailable")
        self.assertNotEqual(outcome.result.outcome, "PASS")

    def test_docker_unavailable_is_unavailable_with_reason_docker_unavailable(self):
        env = FakeEnvironment(available=(False, "docker_unavailable: daemon not reachable"))
        outcome = pipeline.run_install([module("install_ok")], "19.0", env, LIMITS, self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome, outcome.result.reason),
                         (4, "UNAVAILABLE", "docker_unavailable"))
        self.assertEqual(env.prepared, [])

    def test_missing_local_image_reported_by_the_adapter_is_mapped_to_image_unavailable(self):
        env = FakeEnvironment(prepare_error=de.EnvironmentUnavailable("image_unavailable", "not pulled"))
        outcome = pipeline.run_install([module("install_ok")], "19.0", env, LIMITS, self.state)
        self.assertEqual((outcome.result.outcome, outcome.result.reason), ("UNAVAILABLE", "image_unavailable"))


class InstallResultTests(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix="odooflux-pipeline-"))
        self.addCleanup(shutil.rmtree, self.state, True)

    def test_clean_install_is_pass(self):
        env = FakeEnvironment()
        outcome = pipeline.run_install([module("install_ok")], "19.0", env, LIMITS, self.state)
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (4, "PASS"))
        self.assertEqual(env.torn_down, ["rfake00000000"])

    def test_failed_install_names_the_primary_class_and_file(self):
        errors = [ClassifiedError("unknown", None, "ERROR", "Failed to load registry"),
                  ClassifiedError("view_validation", "view_validation.error-near", "CRITICAL",
                                  "Failed to initialize database", file="broken_view/views/fixture_views.xml",
                                  xml_id="view_odooflux_fixture_form", line=3)]
        outcome = pipeline.run_install([module("broken_view")], "19.0", FakeEnvironment(install_errors=errors),
                                       LIMITS, self.state)
        self.assertEqual(outcome.result.outcome, "FAIL")
        self.assertTrue(outcome.result.reason.startswith("install failed: view_validation"), outcome.result.reason)
        self.assertIn("broken_view/views/fixture_views.xml", outcome.result.reason)

    def test_upgrade_outcome_is_a_recorded_sub_result(self):
        env = FakeEnvironment(upgrade_errors=[ClassifiedError("data_load", None, "ERROR", "boom")])
        outcome = pipeline.run_install([module("install_ok")], "19.0", env, LIMITS, self.state, upgrade=True)
        self.assertEqual(outcome.sub_results["install"].outcome, "PASS")
        self.assertEqual(outcome.sub_results["upgrade"].outcome, "FAIL")
        self.assertEqual(outcome.result.outcome, "FAIL")

    def test_teardown_runs_on_every_exit_path_even_when_install_raises(self):
        env = FakeEnvironment(install_raises=RuntimeError("driver crashed"))
        with self.assertRaises(RuntimeError):
            pipeline.run_install([module("install_ok")], "19.0", env, LIMITS, self.state)
        self.assertEqual(env.torn_down, ["rfake00000000"])


class BehaviourWiringTests(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp(prefix="odooflux-pipeline-"))
        self.addCleanup(shutil.rmtree, self.state, True)

    def test_source_and_target_regression_is_l5_fail_naming_the_test(self):
        target = FakeEnvironment(test_log=str(LOGS / "target_19.tests.log"))
        source = FakeEnvironment(test_log=str(LOGS / "source_18.tests.log"))
        outcome = pipeline.run_behavior([module("behavior_compare")], "behavior_compare", "19.0", target, LIMITS,
                                        self.state, source_version="18.0", source_env=source)
        self.assertEqual((outcome.result.layer, outcome.result.outcome), (5, "FAIL"))
        self.assertIn("test_regression", outcome.result.reason)
        self.assertEqual(outcome.result.coverage, "full")

    def test_no_source_baseline_is_partial_and_capped_at_install_verified(self):
        target = FakeEnvironment(test_log=str(LOGS / "target_19.tests.log"))
        outcome = pipeline.run_behavior([module("behavior_compare")], "behavior_compare", "19.0", target, LIMITS,
                                        self.state)
        self.assertEqual(outcome.result.coverage, "partial")
        self.assertNotEqual(outcome.result.outcome, "PASS")       # target failures with no baseline
        layers = {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS", 5: outcome.result.outcome}
        self.assertNotEqual(decide(StatusInputs(layers=layers, l5_coverage="partial")).status, "VERIFIED_SUCCESS")

    def test_source_without_runtime_image_gives_partial_coverage_with_the_reason_in_notes(self):
        target = FakeEnvironment(test_log=str(LOGS / "target_19.tests.log"))
        outcome = pipeline.run_behavior([module("behavior_compare")], "behavior_compare", "19.0", target, LIMITS,
                                        self.state, source_version="17.0")
        self.assertEqual(outcome.result.coverage, "partial")
        self.assertTrue(any("image_unavailable" in note for note in outcome.notes))

    def test_killed_test_run_is_fail_with_the_killed_reason(self):
        target = FakeEnvironment(test_log=str(LOGS / "target_19.tests.log"), killed="timeout")
        outcome = pipeline.run_behavior([module("behavior_compare")], "behavior_compare", "19.0", target, LIMITS,
                                        self.state)
        self.assertEqual((outcome.result.outcome, outcome.result.reason), ("FAIL", "timeout"))


class EnterpriseStatusTests(unittest.TestCase):
    def test_enterprise_fixture_status_is_at_most_static_validated(self):
        # T019 done-when: the real L3 check (INFO, not WARNING, for the Enterprise dependency) plus an L4 that is
        # SKIPPED with reason enterprise_dependency gives STATIC_VALIDATED. L1 and L2 are taken as PASS here.
        from odooflux.validation.dependency.integrity import check_integrity
        l3_findings, l3 = check_integrity([module("enterprise_dep")], target_version="19.0")
        self.assertEqual([f.severity for f in l3_findings], ["INFO"])
        self.assertEqual(l3.outcome, "PASS")
        l4 = pipeline.run_install([module("enterprise_dep")], "19.0", NoDockerEnvironment(), LIMITS,
                                  Path(tempfile.mkdtemp(prefix="odooflux-enterprise-")))
        self.assertEqual((l4.result.outcome, l4.result.reason), ("SKIPPED", "enterprise_dependency"))
        decision = decide(StatusInputs(layers={1: "PASS", 2: "PASS", 3: l3.outcome, 4: l4.result.outcome}))
        self.assertEqual(decision.status, "STATIC_VALIDATED")


class MappingDataTests(unittest.TestCase):
    def test_image_map_has_18_19_and_20_but_not_17(self):
        images = de.load_runtime_images()["images"]
        self.assertIn("18.0", images)
        self.assertIn("19.0", images)
        self.assertIn("20.0", images)
        self.assertNotIn("17.0", images)
        self.assertEqual(de.image_for_version("17.0"), None)
        self.assertEqual(de.image_for_version("19.0"), "odoo:19.0")
        self.assertEqual(images["20.0"]["tag_status"], "UNVERIFIED")

    def test_enterprise_seed_list_is_unverified_and_contains_sale_subscription(self):
        from odooflux.validation.dependency.integrity import load_enterprise_modules
        import json
        from odooflux.knowledge.loader import KNOWLEDGE_ROOT
        data = json.loads((KNOWLEDGE_ROOT / "compatibility" / "enterprise_modules.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "UNVERIFIED")
        self.assertIn("note", data)
        self.assertIn("sale_subscription", load_enterprise_modules())


if __name__ == "__main__":
    unittest.main()
