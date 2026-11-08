"""TST-007-016: the AI benchmark harness runs on the fixture corpus with the fake provider and is deterministic."""

import os
import unittest

from .run_benchmark import load_corpus, run_benchmark, to_markdown


class BenchmarkHarnessTests(unittest.TestCase):
    def test_corpus_is_labelled_provisional(self):
        self.assertIn("PROVISIONAL", load_corpus()["note"])

    def test_metrics_are_recorded_and_deterministic(self):
        a, b = run_benchmark(), run_benchmark()
        self.assertEqual(a, b | {}, "two runs on the same corpus must agree")
        first = a["first_pass"]
        for key in ("acceptance_rate", "correctness_rate", "rejection_by_reason", "tokens_per_accepted_edit",
                    "calls_per_finding"):
            self.assertIn(key, first)
        self.assertGreater(first["provider_requests"], 0)
        self.assertEqual(first["accepted"], 1)
        self.assertEqual(first["correctness_rate"], 1.0)
        for reason in ("syntax_invalid", "truncated", "protected_identifier_changed", "out_of_region"):
            self.assertIn(reason, first["rejection_by_reason"])
        self.assertEqual(a["second_pass"]["cache_effectiveness"], 1.0)
        self.assertEqual(a["live"], "not run")

    def test_markdown_table_has_every_required_metric(self):
        text = to_markdown(run_benchmark())
        for metric in ("Acceptance rate", "Correctness rate", "Rejection by reason", "Tokens per accepted edit",
                       "Calls per escalated finding", "Cache effectiveness"):
            self.assertIn(metric, text)


@unittest.skipUnless(os.environ.get("ODOOFLUX_AI_TESTS") == "1", "opt-in: set ODOOFLUX_AI_TESTS=1")
class LiveBenchmarkTests(unittest.TestCase):
    def test_live_benchmark_is_not_implemented_in_this_baseline(self):
        self.skipTest("a real-provider benchmark needs an owner-chosen model and budget; not run")


if __name__ == "__main__":
    unittest.main()
