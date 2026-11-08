"""TST-010-006 (T011, T002; REQ-PRF-001, REQ-PRF-004): the benchmark harness compares medians with the recorded
budgets and with the stored baseline, and fails on a budget violation or a regression above 20 %.

Logic tests run always. The end-to-end run on a small generated corpus is opt-in (`ODOOFLUX_BENCHMARKS=1`); the
300-module run is `python tests/benchmarks/run_benchmarks.py` on the reference machine."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from . import run_benchmarks as rb

BENCH = Path(__file__).resolve().parent


def results(serial=10.0, parallel=4.0, incremental=0.5, rss=150.0, parsed=0):
    return {"serial": {"median_wall_s": serial, "peak_rss_mib": rss, "files_parsed": None, "report_digest": "d"},
            "parallel": {"median_wall_s": parallel, "peak_rss_mib": rss, "files_parsed": None, "report_digest": "d"},
            "incremental": {"median_wall_s": incremental, "peak_rss_mib": rss, "files_parsed": parsed,
                            "report_digest": "d"}}


def budgets(value_wall=15.0, value_rss=200.0):
    rows = []
    for mode, wall in (("serial", value_wall), ("parallel", value_wall), ("incremental", value_wall)):
        rows.append({"metric": "wall_s", "mode": mode, "value": wall, "baseline_ref": "x", "headroom_factor": 1.5,
                     "approved_by": "PENDING_HUMAN_REVIEW", "date": "2026-11-07", "rationale": "r"})
        rows.append({"metric": "peak_rss_mib", "mode": mode, "value": value_rss, "baseline_ref": "x",
                     "headroom_factor": 1.5, "approved_by": "PENDING_HUMAN_REVIEW", "date": "2026-11-07",
                     "rationale": "r"})
    rows.append({"metric": "files_parsed", "mode": "incremental", "value": 0, "baseline_ref": "x",
                 "headroom_factor": 1.0, "approved_by": "PENDING_HUMAN_REVIEW", "date": "2026-11-07",
                 "rationale": "unchanged corpus parses nothing"})
    return {"schema": "odooflux.benchmark-budgets/1", "corpus_id": "c", "budgets": rows}


class HarnessLogicTests(unittest.TestCase):
    def test_median(self):
        self.assertEqual(rb.median([3, 1, 2]), 2)
        self.assertEqual(rb.median([4, 1, 3, 2]), 2.5)

    def test_within_budgets_passes(self):
        self.assertEqual(rb.check_budgets(results(), budgets()), [])

    def test_wall_time_over_budget_fails_and_is_named(self):
        failures = rb.check_budgets(results(serial=16.0), budgets())
        self.assertEqual(len(failures), 1)
        self.assertIn("serial", failures[0])
        self.assertIn("wall_s", failures[0])

    def test_rss_over_budget_fails(self):
        self.assertTrue(rb.check_budgets(results(rss=250.0), budgets()))

    def test_incremental_must_parse_nothing(self):
        failures = rb.check_budgets(results(parsed=12), budgets())
        self.assertTrue(any("files_parsed" in f for f in failures))

    def test_a_mode_without_a_budget_fails(self):
        b = budgets()
        b["budgets"] = [r for r in b["budgets"] if not (r["mode"] == "parallel" and r["metric"] == "wall_s")]
        self.assertTrue(any("parallel" in f and "no budget" in f for f in rb.check_budgets(results(), b)))

    def test_regression_over_twenty_percent_fails(self):
        base = {"modes": results()}
        self.assertEqual(rb.check_regression(results(serial=11.9), base), [])
        failures = rb.check_regression(results(serial=12.1), base)
        self.assertEqual(len(failures), 1)
        self.assertIn("20", failures[0])

    def test_regression_without_a_baseline_is_a_failure_message(self):
        self.assertTrue(rb.check_regression(results(), None))

    def test_digests_must_agree_across_modes(self):
        good = results()
        self.assertEqual(rb.check_digests(good), [])
        bad = results()
        bad["parallel"]["report_digest"] = "other"
        self.assertTrue(any("parallel" in f for f in rb.check_digests(bad)))

    def test_report_digest_ignores_run_identity_and_paths(self):
        a = {"run": {"run_id": "1", "tool_version": "x"}, "recovery": {"run_log": "/s/a", "rollback_cmd": "r 1"},
             "modules": [{"path": "/corpus/a/m"}]}
        b = {"run": {"run_id": "2", "tool_version": "x"}, "recovery": {"run_log": "/s/b", "rollback_cmd": "r 2"},
             "modules": [{"path": "/other/b/m"}]}
        self.assertEqual(rb.report_digest(a, ["/corpus/a", "/s/a"]) , rb.report_digest(b, ["/other/b", "/s/b"]))
        b["modules"][0]["path"] = "/other/b/n"
        self.assertNotEqual(rb.report_digest(a, ["/corpus/a"]), rb.report_digest(b, ["/other/b"]))

    def test_budget_file_validation_requires_value_baseline_and_approver(self):
        self.assertEqual(rb.validate_budgets(budgets()), [])
        broken = budgets()
        del broken["budgets"][0]["baseline_ref"]
        broken["budgets"][1]["approved_by"] = ""
        problems = rb.validate_budgets(broken)
        self.assertTrue(any("baseline_ref" in p for p in problems))
        self.assertTrue(any("approved_by" in p for p in problems))

    def test_every_metric_and_mode_is_budgeted(self):
        b = budgets()
        b["budgets"] = [r for r in b["budgets"] if r["mode"] != "serial"]
        self.assertTrue(any("serial" in p for p in rb.validate_budgets(b)))


class RecordedBudgetsTests(unittest.TestCase):
    """T002: the committed budgets file is complete, derived from measurements and never self-approved."""

    @classmethod
    def setUpClass(cls):
        cls.budgets = json.loads((BENCH / "budgets.json").read_text(encoding="utf-8"))

    def test_every_metric_and_mode_has_value_baseline_and_approver_field(self):
        self.assertEqual(rb.validate_budgets(self.budgets), [])

    def test_approver_is_pending_human_review_not_a_name(self):
        self.assertTrue(all(r["approved_by"] == "PENDING_HUMAN_REVIEW" for r in self.budgets["budgets"]))

    def test_rationale_names_the_headroom_and_the_baseline(self):
        for row in self.budgets["budgets"]:
            self.assertGreaterEqual(row["headroom_factor"], 1.0)
            self.assertIn("baseline", row["rationale"].lower())

    def test_reference_machine_is_recorded(self):
        text = (BENCH / "REFERENCE_MACHINE.md").read_text(encoding="utf-8")
        for word in ("CPU", "Memory", "Python", "OS", "Storage"):
            self.assertIn(word, text)

    def test_stored_baseline_matches_the_budget_corpus(self):
        baseline = json.loads((BENCH / "baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(baseline["corpus_id"], self.budgets["corpus_id"])
        self.assertEqual(set(baseline["modes"]), {"serial", "parallel", "incremental"})


@unittest.skipUnless(os.environ.get("ODOOFLUX_BENCHMARKS") == "1", "set ODOOFLUX_BENCHMARKS=1 to run")
class EndToEndTests(unittest.TestCase):
    def test_small_corpus_writes_results_json(self):
        out = Path(tempfile.mkdtemp())
        code = rb.main(["--modules", "6", "--runs", "1", "--out", str(out), "--no-enforce",
                        "--modes", "serial,parallel,incremental"])
        self.assertEqual(code, 0)
        written = list(out.glob("*.json"))
        self.assertEqual(len(written), 1)
        data = json.loads(written[0].read_text(encoding="utf-8"))
        self.assertEqual(set(data["modes"]), {"serial", "parallel", "incremental"})
        self.assertEqual(data["modes"]["incremental"]["files_parsed"], 0)
        digests = {m["report_digest"] for m in data["modes"].values()}
        self.assertEqual(len(digests), 1)


if __name__ == "__main__":
    unittest.main()
