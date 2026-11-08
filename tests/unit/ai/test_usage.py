"""TST-007-012 (REQ-AI-006, FR-008, SC-004): usage totals equal provider-reported usage; cost null without pricing."""

import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.providers.types import Usage, UsageRecord
from odooflux.ai.usage.usage import UsageLedger, compute_cost

PRICING = {"input_per_mtok": 1.0, "output_per_mtok": 2.0, "cached_per_mtok": 0.5}


def rec(i, model="m-one", inp=100, out=20, cached=0, cost=None, outcome="accepted", module="mod", est=False,
        attempts=1):
    return UsageRecord(request_id=f"r{i}", provider="alpha", model=model, input_tokens=inp, output_tokens=out,
                       cached_tokens=cached, estimated=est, cost=cost, outcome=outcome, module=module,
                       attempts=attempts)


class CostTests(unittest.TestCase):
    def test_cost_from_configured_pricing(self):
        cost = compute_cost(Usage(input=1_000_000, output=500_000, cached=0), PRICING)
        self.assertAlmostEqual(cost, 2.0)

    def test_cached_tokens_priced_separately(self):
        cost = compute_cost(Usage(input=1_000_000, output=0, cached=1_000_000), PRICING)
        self.assertAlmostEqual(cost, 1.0 + 0.5)

    def test_no_pricing_is_none(self):
        self.assertIsNone(compute_cost(Usage(input=5, output=5), None))
        self.assertIsNone(compute_cost(Usage(input=5, output=5), {"input_per_mtok": 1.0}))  # incomplete pricing


class LedgerTests(unittest.TestCase):
    def test_totals_equal_the_sum_of_reported_usage_exactly(self):
        ledger = UsageLedger()
        sums = [(100, 20, 5), (333, 77, 0), (1, 1, 1), (4096, 900, 12)]
        for i, (a, b, c) in enumerate(sums):
            ledger.record(rec(i, inp=a, out=b, cached=c))
        s = ledger.summary()
        self.assertEqual(s["totals"]["input_tokens"], sum(x[0] for x in sums))
        self.assertEqual(s["totals"]["output_tokens"], sum(x[1] for x in sums))
        self.assertEqual(s["totals"]["cached_tokens"], sum(x[2] for x in sums))
        self.assertEqual(s["requests"], 4)

    def test_cost_is_null_and_labelled_without_pricing(self):
        ledger = UsageLedger()
        ledger.record(rec(1))
        s = ledger.summary()
        self.assertIsNone(s["totals"]["cost"])
        self.assertEqual(s["totals"]["cost_label"], "pricing not configured")

    def test_cost_total_when_all_priced(self):
        ledger = UsageLedger()
        ledger.record(rec(1, cost=0.25))
        ledger.record(rec(2, cost=0.5))
        s = ledger.summary()
        self.assertAlmostEqual(s["totals"]["cost"], 0.75)
        self.assertNotIn("cost_label", s["totals"])

    def test_cache_hits_and_skips_are_not_provider_requests(self):
        ledger = UsageLedger()
        ledger.record(rec(1))
        ledger.record(rec(2, inp=0, out=0, outcome="cache_hit", attempts=0))
        ledger.record(rec(3, inp=0, out=0, outcome="skipped:budget_job", attempts=0))
        s = ledger.summary()
        self.assertEqual((s["requests"], s["cache_hits"], s["provider_calls"]), (1, 1, 1))
        self.assertEqual(s["outcomes"], {"accepted": 1, "cache_hit": 1, "skipped:budget_job": 1})

    def test_per_model_and_per_module_and_estimated_flag(self):
        ledger = UsageLedger()
        ledger.record(rec(1, model="a", module="x", est=True))
        ledger.record(rec(2, model="b", module="y", attempts=3))
        s = ledger.summary()
        self.assertEqual(sorted(s["by_model"]), ["alpha/a", "alpha/b"])
        self.assertEqual(sorted(s["by_module"]), ["x", "y"])
        self.assertTrue(s["totals"]["estimated"])
        self.assertEqual(s["attempts"], 4)

    def test_a_model_decline_is_a_provider_request(self):
        ledger = UsageLedger()
        ledger.record(rec(1, outcome="skipped:model_declined"))  # the provider answered; it just declined
        self.assertEqual(ledger.summary()["requests"], 1)

    def test_empty_ledger_reports_zero_requests(self):
        s = UsageLedger().summary()
        self.assertEqual(s["requests"], 0)
        self.assertEqual(s["totals"]["input_tokens"], 0)

    def test_rejection_reasons_counted(self):
        ledger = UsageLedger()
        ledger.record(rec(1, outcome="rejected:syntax_invalid"))
        ledger.record(rec(2, outcome="rejected:syntax_invalid"))
        self.assertEqual(ledger.summary()["rejections"], {"syntax_invalid": 2})


if __name__ == "__main__":
    unittest.main()
