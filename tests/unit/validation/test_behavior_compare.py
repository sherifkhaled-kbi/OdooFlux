"""TST-008-009 (REQ-BIZ-002, REQ-VAL-005, FR-008): test-outcome parsing, comparison classifications and the L5
judgement. Inputs are the recorded outputs in tests/golden_fixtures/runtime/logs/behavior/ (real odoo 18.0 and
19.0 runs of the behavior_compare fixture, plus two derived variants marked in that folder's README)."""

import unittest
from pathlib import Path

from .._setup import SRC  # noqa: F401  (puts src/ first on sys.path)
from odooflux.validation.behavioral import compare as cmp
from odooflux.validation.status import StatusInputs, decide

ROOT = Path(__file__).resolve().parents[2] / "golden_fixtures" / "runtime"
FIXTURE = ROOT / "behavior_compare"
LOGS = ROOT / "logs" / "behavior"
MODULE = "behavior_compare"
PASS_BOTH = f"{MODULE}.TestBehavior.test_pass_both"
FAIL_BOTH = f"{MODULE}.TestBehavior.test_fail_both"
REGRESSION = f"{MODULE}.TestBehavior.test_regression"
UNIVERSE = frozenset({PASS_BOTH, FAIL_BOTH, REGRESSION})


def log(name):
    return (LOGS / name).read_text(encoding="utf-8")


def parsed(name):
    return cmp.parse_test_output(log(name), MODULE, UNIVERSE)


def full_pass(ids=UNIVERSE):
    return cmp.ParsedTests(outcomes={t: "pass" for t in ids}, ran=True, complete=True, universe=frozenset(ids))


class StaticUniverseTests(unittest.TestCase):
    def test_ast_scan_finds_every_test_method_without_importing_it(self):
        self.assertEqual(cmp.scan_static_universe(FIXTURE, MODULE), UNIVERSE)

    def test_module_without_tests_has_an_empty_universe(self):
        self.assertEqual(cmp.scan_static_universe(ROOT / "install_ok", "install_ok"), frozenset())


class ParseTests(unittest.TestCase):
    def test_recorded_target_run_on_19_0(self):
        result = parsed("target_19.tests.log")
        self.assertEqual(result.outcomes, {PASS_BOTH: "pass", FAIL_BOTH: "fail", REGRESSION: "fail"})
        self.assertTrue(result.ran)
        self.assertTrue(result.complete)

    def test_recorded_source_run_on_18_0(self):
        result = parsed("source_18.tests.log")
        self.assertEqual(result.outcomes, {PASS_BOTH: "pass", FAIL_BOTH: "fail", REGRESSION: "pass"})

    def test_failures_logged_at_install_and_post_install_collapse_to_one_outcome(self):
        text = log("target_19.tests.log")
        self.assertGreaterEqual(text.count("FAIL: TestBehavior.test_fail_both"), 2)
        self.assertEqual(sum(1 for o in parsed("target_19.tests.log").outcomes.values() if o == "fail"), 2)

    def test_test_never_started_is_not_inferred_as_a_pass(self):
        result = parsed("source_18_without_pass_both.tests.log")
        self.assertNotIn(PASS_BOTH, result.outcomes)
        self.assertFalse(result.complete)

    def test_empty_output_means_nothing_ran(self):
        result = cmp.parse_test_output("", MODULE, UNIVERSE)
        self.assertFalse(result.ran)
        self.assertEqual(result.outcomes, {})

    def test_subtest_failure_maps_to_its_parent_test(self):
        text = (f"2026-11-07 10:00:00,000 1 INFO odoo odoo.addons.{MODULE}.tests.test_behavior: "
                "Starting TestBehavior.test_regression ...\n"
                f"2026-11-07 10:00:00,001 1 ERROR odoo odoo.addons.{MODULE}.tests.test_behavior: "
                "Subtest TestBehavior.test_regression (i=2)\n")
        result = cmp.parse_test_output(text, MODULE, UNIVERSE)
        self.assertEqual(result.outcomes, {REGRESSION: "fail"})

    def test_skip_record_is_a_skip_not_a_pass(self):
        text = (f"2026-11-07 10:00:00,000 1 INFO odoo odoo.addons.{MODULE}.tests.test_behavior: "
                "Starting TestBehavior.test_pass_both ...\n"
                f"2026-11-07 10:00:00,001 1 INFO odoo odoo.addons.{MODULE}.tests.test_behavior: "
                "skipped TestBehavior.test_pass_both : not on this platform\n")
        result = cmp.parse_test_output(text, MODULE, UNIVERSE)
        self.assertEqual(result.outcomes, {PASS_BOTH: "skip"})

    def test_errors_from_other_loggers_are_not_test_outcomes(self):
        text = ("2026-11-07 10:00:00,000 1 ERROR odoo odoo.sql_db: bad query: FAIL: TestBehavior.test_regression\n")
        self.assertEqual(cmp.parse_test_output(text, MODULE, UNIVERSE).outcomes, {})


class CompareTests(unittest.TestCase):
    def counts(self, source, target):
        comparisons = cmp.compare(source.outcomes, target.outcomes)
        return cmp.classification_counts(comparisons)

    def test_recorded_18_to_19_gives_one_regression_one_fail_both_one_pass_both(self):
        counts = self.counts(parsed("source_18.tests.log"), parsed("target_19.tests.log"))
        self.assertEqual(counts["pass_both"], [PASS_BOTH])
        self.assertEqual(counts["regression"], [REGRESSION])
        self.assertEqual(counts["fail_both"], [FAIL_BOTH])
        self.assertEqual(counts["fixed"], [])
        self.assertEqual(counts["target_only"], [])
        self.assertEqual(counts["source_only"], [])

    def test_recorded_19_to_18_gives_the_fixed_classification(self):
        counts = self.counts(parsed("target_19.tests.log"), parsed("source_18.tests.log"))
        self.assertEqual(counts["fixed"], [REGRESSION])

    def test_test_only_on_the_target_is_target_only(self):
        counts = self.counts(parsed("source_18_without_pass_both.tests.log"), parsed("target_19.tests.log"))
        self.assertEqual(counts["target_only"], [PASS_BOTH])

    def test_test_only_on_the_source_is_source_only(self):
        counts = self.counts(parsed("source_18.tests.log"), parsed("target_19_without_pass_both.tests.log"))
        self.assertEqual(counts["source_only"], [PASS_BOTH])

    def test_all_six_classifications_are_produced_from_recorded_outputs(self):
        seen = set()
        pairs = [("source_18.tests.log", "target_19.tests.log"),
                 ("target_19.tests.log", "source_18.tests.log"),
                 ("source_18_without_pass_both.tests.log", "target_19.tests.log"),
                 ("source_18.tests.log", "target_19_without_pass_both.tests.log")]
        for source, target in pairs:
            seen |= {k for k, v in self.counts(parsed(source), parsed(target)).items() if v}
        self.assertEqual(seen, set(cmp.CLASSIFICATIONS))


class JudgeTests(unittest.TestCase):
    def test_regression_gives_fail_naming_only_the_regressed_test_with_full_coverage(self):
        result = cmp.judge(parsed("target_19.tests.log"), parsed("source_18.tests.log"))
        self.assertEqual(result.layer, 5)
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn(REGRESSION, result.reason)
        self.assertNotIn(PASS_BOTH, result.reason)
        self.assertEqual(result.coverage, "full")

    def test_pre_existing_failure_alone_does_not_fail_when_a_baseline_exists(self):
        source = cmp.ParsedTests(outcomes={FAIL_BOTH: "fail", PASS_BOTH: "pass"}, ran=True, complete=True,
                                 universe=frozenset({FAIL_BOTH, PASS_BOTH}))
        target = cmp.ParsedTests(outcomes={FAIL_BOTH: "fail", PASS_BOTH: "pass"}, ran=True, complete=True,
                                 universe=frozenset({FAIL_BOTH, PASS_BOTH}))
        result = cmp.judge(target, source)
        self.assertEqual((result.outcome, result.coverage), ("PASS", "full"))

    def test_pass_with_full_coverage_needs_baseline_ran_and_no_regression(self):
        result = cmp.judge(full_pass(), full_pass())
        self.assertEqual((result.outcome, result.coverage), ("PASS", "full"))

    def test_no_baseline_with_target_failures_is_fail_with_partial_coverage(self):
        result = cmp.judge(parsed("target_19.tests.log"), None, source_reason="no odoo:18.0 image")
        self.assertEqual(result.outcome, "FAIL")
        self.assertEqual(result.coverage, "partial")
        self.assertIn("without a baseline", result.reason)

    def test_no_baseline_and_all_target_tests_pass_is_pass_with_partial_coverage(self):
        result = cmp.judge(full_pass(), None, source_reason="no odoo:18.0 image")
        self.assertEqual((result.outcome, result.coverage), ("PASS", "partial"))

    def test_incomplete_target_run_is_partial_even_when_it_passes(self):
        target = cmp.ParsedTests(outcomes={PASS_BOTH: "pass"}, ran=True, complete=False, universe=UNIVERSE)
        result = cmp.judge(target, full_pass())
        self.assertEqual((result.outcome, result.coverage), ("PASS", "partial"))

    def test_no_tests_is_skipped_with_reason_no_tests(self):
        empty = cmp.ParsedTests(outcomes={}, ran=False, complete=False, universe=frozenset())
        result = cmp.judge(empty, None)
        self.assertEqual((result.outcome, result.reason), ("SKIPPED", "no_tests"))

    def test_tests_that_never_started_are_a_failure_to_run(self):
        target = cmp.ParsedTests(outcomes={}, ran=False, complete=False, universe=UNIVERSE)
        result = cmp.judge(target, None)
        self.assertEqual(result.outcome, "FAIL")
        self.assertIn("tests_not_run", result.reason)

    def test_partial_coverage_is_capped_at_install_verified_by_the_decision_function(self):
        layers = {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS"}
        partial = decide(StatusInputs(layers={**layers, 5: "PASS"}, l5_coverage="partial"))
        full = decide(StatusInputs(layers={**layers, 5: "PASS"}, l5_coverage="full"))
        self.assertEqual(partial.status, "INSTALL_VERIFIED")
        self.assertEqual(full.status, "VERIFIED_SUCCESS")


if __name__ == "__main__":
    unittest.main()
