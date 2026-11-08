"""TST-010-004 (T009; REQ-PRF-003, FR-005): the report of a parallel run equals the report of a serial run on the
corpus subset, `--jobs 1` against `--jobs 4`; a failed worker blocks only its own modules."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import _support as sup
from odooflux.core.orchestrator import module_plan, parallel
from odooflux.core.recovery.runlog import read_runlog


TIMING = ("timestamp", "elapsed_seconds")


def untimed(report: dict) -> dict:
    """A module report without its timing fields (the only fields allowed to differ between runs)."""
    return {k: v for k, v in report.items() if k not in TIMING}


def digest(state, corpus) -> str:
    return hashlib.sha256(sup.normalised_json(state, [corpus]).encode("utf-8")).hexdigest()


@unittest.skipUnless(hasattr(os, "fork"), "the process pool uses the fork start method")
class ParallelDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = sup.small_corpus(8)

    def run_with(self, jobs, mode="analyze", **kwargs):
        return sup.run_analysis(self.corpus, tempfile.mkdtemp(), jobs=jobs, mode=mode, **kwargs)

    def test_report_digest_equal_for_jobs_1_and_4(self):
        _, serial = self.run_with(1)
        _, par = self.run_with(4)
        self.assertEqual(digest(serial, self.corpus), digest(par, self.corpus))
        self.assertEqual([m["name"] for m in serial["modules"]], [m["name"] for m in par["modules"]])

    def test_dry_run_digest_equal_and_run_log_order_is_deterministic(self):
        run_a, serial = self.run_with(1, mode="dry_run")
        run_b, par = self.run_with(4, mode="dry_run")
        self.assertEqual(digest(serial, self.corpus), digest(par, self.corpus))
        events = lambda run: [(e["event"], e.get("module")) for e in read_runlog(run.log.path)[0]]
        self.assertEqual(events(run_a), events(run_b))

    def test_callbacks_run_in_module_order(self):
        seen = []
        self.run_with(4, on_module=lambda entry: seen.append(entry["name"]))
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(seen), 8)

    def test_a_failing_worker_blocks_only_its_module(self):
        _, serial = self.run_with(1)
        real = module_plan.plan_module

        def flaky(module_path, *args, **kwargs):
            if Path(module_path).name == "gen_mod_003":
                raise RuntimeError("injected worker failure")
            return real(module_path, *args, **kwargs)

        with mock.patch.object(module_plan, "plan_module", flaky), \
                mock.patch("odooflux.core.orchestrator.run.plan_module", flaky):
            _, par = self.run_with(4)
        by_name = {m["name"]: m for m in par["modules"]}
        blocked = by_name["gen_mod_003"]
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("injected worker failure", blocked["report"]["block_reason"])
        self.assertTrue(blocked["report"]["blocked"])
        for ref in serial["modules"]:
            if ref["name"] != "gen_mod_003":
                self.assertEqual(untimed(by_name[ref["name"]]["report"]), untimed(ref["report"]), ref["name"])

    def test_a_killed_worker_blocks_only_its_module(self):
        _, serial = self.run_with(1)
        real = module_plan.plan_module

        def dying(module_path, *args, **kwargs):
            if Path(module_path).name == "gen_mod_005":
                os._exit(7)
            return real(module_path, *args, **kwargs)

        with mock.patch("odooflux.core.orchestrator.run.plan_module", dying):
            _, par = self.run_with(3)
        by_name = {m["name"]: m for m in par["modules"]}
        self.assertEqual(by_name["gen_mod_005"]["status"], "BLOCKED")
        self.assertIn("worker", by_name["gen_mod_005"]["report"]["block_reason"])
        for ref in serial["modules"]:
            if ref["name"] != "gen_mod_005":
                self.assertEqual(untimed(by_name[ref["name"]]["report"]), untimed(ref["report"]), ref["name"])

    def test_fix_mode_is_serial(self):
        self.assertFalse(parallel.can_parallelise("fix", 4))
        self.assertTrue(parallel.can_parallelise("analyze", 4))
        self.assertTrue(parallel.can_parallelise("dry_run", 2))
        self.assertFalse(parallel.can_parallelise("analyze", 1))

    def test_resolve_jobs(self):
        self.assertEqual(parallel.resolve_jobs(3), 3)
        self.assertEqual(parallel.resolve_jobs(0), os.cpu_count() or 1)
        with self.assertRaises(ValueError):
            parallel.resolve_jobs(-1)


if __name__ == "__main__":
    unittest.main()
