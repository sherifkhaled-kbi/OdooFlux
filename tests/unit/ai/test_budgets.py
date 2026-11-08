"""TST-007-011 (REQ-AI-005, FR-007): nested budgets are hard stops checked before sending."""

import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.usage.budgets import BudgetTree


class BudgetTests(unittest.TestCase):
    def test_request_scope(self):
        b = BudgetTree(job_tokens=10_000, request_tokens=100)
        self.assertEqual(b.check("m", "f", 80, 50), "budget_request")
        self.assertIsNone(b.check("m", "f", 40, 50))

    def test_file_scope_exhaustion_is_latched_and_recorded_once(self):
        b = BudgetTree(job_tokens=10_000, file_tokens=200)
        self.assertIsNone(b.check("m", "f1", 100, 50))
        b.charge("m", "f1", 150)
        self.assertEqual(b.check("m", "f1", 40, 50), "budget_file")
        self.assertEqual(b.check("m", "f1", 1, 1), "budget_file")  # later, smaller request is skipped too
        self.assertIsNone(b.check("m", "f2", 100, 50))  # another file has its own budget
        self.assertEqual([e["scope"] for e in b.events], ["file"])

    def test_module_scope(self):
        b = BudgetTree(job_tokens=10_000, module_tokens=300)
        b.charge("m1", "a", 250)
        self.assertEqual(b.check("m1", "b", 40, 20), "budget_module")
        self.assertIsNone(b.check("m2", "a", 40, 20))
        self.assertEqual(len(b.events), 1)

    def test_job_scope_stops_everything(self):
        b = BudgetTree(job_tokens=500)
        b.charge("m1", "a", 450)
        self.assertEqual(b.check("m2", "b", 40, 20), "budget_job")
        self.assertEqual(b.check("m3", "c", 1, 1), "budget_job")
        self.assertEqual(len([e for e in b.events if e["scope"] == "job"]), 1)

    def test_every_scope_must_fit(self):
        b = BudgetTree(job_tokens=1000, module_tokens=1000, file_tokens=100)
        self.assertEqual(b.check("m", "f", 90, 20), "budget_file")  # fits job and module, not file

    def test_actual_usage_replaces_estimate(self):
        b = BudgetTree(job_tokens=1000)
        b.check("m", "f", 400, 100)  # estimate is not reserved
        b.charge("m", "f", 120)  # actual
        self.assertEqual(b.remaining("job", "m", "f"), 880)

    def test_job_budget_is_mandatory(self):
        with self.assertRaises(ValueError):
            BudgetTree(job_tokens=None)
        with self.assertRaises(ValueError):
            BudgetTree(job_tokens=0)

    def test_cost_budget_needs_a_known_cost(self):
        b = BudgetTree(job_tokens=10_000, job_cost=1.0)
        self.assertEqual(b.check("m", "f", 1, 1, est_cost=None), "budget_job")
        self.assertIsNone(b.check("m", "f", 1, 1, est_cost=0.5))
        b.charge("m", "f", 10, cost=0.9)
        self.assertEqual(b.check("m", "f", 1, 1, est_cost=0.5), "budget_job")


class EscalatorBudgetTests(unittest.TestCase):
    TEXT = "class A:\n    def f_ok(self):\n        return old_api(1)\n\n    def g_ok(self):\n        return old_api(2)\n"
    SCRIPT = {"entries": [{"match": {"contains": "def "}, "response": {
        "replacement": "", "notes": "", "cannot_fix": True, "usage": {"input": 60, "output": 10}}}]}

    def run_with(self, budgets):
        from . import _helpers as h
        from odooflux.ai.escalation import Escalator
        from odooflux.ai.providers.fake import FakeProvider
        from odooflux.ai.providers.types import ModelDescriptor
        from odooflux.ai.usage.usage import UsageLedger
        p = FakeProvider(self.SCRIPT, models=[ModelDescriptor("fake", "fake-model")])
        ledger = UsageLedger()
        esc = Escalator(p.complete, provider="fake", model="fake-model", step="s", validate=h.python_validate,
                        rescan=h.toy_rescan, budgets=budgets, ledger=ledger)
        result = esc.escalate_file("mod", "m.py", self.TEXT, h.toy_findings("m.py", self.TEXT), h.TOY_METAS)
        return p, result, ledger, budgets

    def test_job_budget_hard_stop_skips_the_rest_with_reason(self):
        p, result, ledger, budgets = self.run_with(BudgetTree(job_tokens=300))
        # estimate for one request is larger than 300 -> nothing is sent
        outcomes = {o.outcome for o in result.outcomes}
        self.assertEqual(outcomes, {"skipped:budget_job"})
        self.assertEqual(p.requests, [])
        self.assertEqual(ledger.summary()["outcomes"], {"skipped:budget_job": 2})
        self.assertEqual(len(budgets.events), 1)

    def test_actual_usage_is_charged_and_second_request_is_stopped(self):
        # first request fits (est ~ 150 + max_out), actual charge 70, remaining too small for the second
        tree = BudgetTree(job_tokens=700)
        p, result, _ledger, _ = self.run_with(tree)
        self.assertLessEqual(len(p.requests), 2)
        spent = 700 - tree.remaining("job", "mod", "m.py")
        self.assertEqual(spent, 70 * len(p.requests))

    def test_file_budget(self):
        p, result, _l, _b = self.run_with(BudgetTree(job_tokens=100_000, file_tokens=50))
        self.assertEqual({o.outcome for o in result.outcomes}, {"skipped:budget_file"})
        self.assertEqual(p.requests, [])


if __name__ == "__main__":
    unittest.main()
