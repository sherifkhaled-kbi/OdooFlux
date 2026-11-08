"""TST-011-065 (REQ-KAP-033): cross-checks XC-UPGRADE, XC-INDEP, XC-KB, XC-REGR, XC-BENCH.

Recall is reported only against a NAMED benchmark set and says so. A recall without a named benchmark is refused by
`recall_entry` and reported as NOT_MEASURED without a recall key. A check that was not run is NOT_RUN and still printed.
"""

import unittest

from odooflux.knowledge.coverage import crosscheck as xc
from odooflux.knowledge.extract.accounting import FileAccounting

SS_FROM = "ss-" + "ab" * 6
SS_TO = "ss-" + "cd" * 6
CHECK_IDS = ["XC-UPGRADE", "XC-INDEP", "XC-KB", "XC-REGR", "XC-BENCH"]


def _changes(*subjects):
    return [{"change_id": f"CH-{i:016x}", "subject_key": s, "class": "REMOVED", "disposition": "RULE_CREATED"}
            for i, s in enumerate(subjects, start=1)]


def _by_id(items):
    out = {}
    for item in items:
        out.setdefault(item["id"], []).append(item)
    return out


class CrossCheckTests(unittest.TestCase):
    def test_xc_upgrade_recall(self):
        refs = [{"kind": "field", "subject_key": f"res.partner::field::old_{n}"} for n in range(4)]
        changes = _changes("res.partner::field::old_0", "res.partner::field::old_1", "res.partner::field::old_2")
        item = xc.xc_upgrade(refs, changes, step="17-18")
        self.assertEqual(item["id"], "XC-UPGRADE")
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["recall"], {"found": 3, "referenced": 4, "benchmark_id": "upgrade-scripts:17-18",
                                          "benchmark_size": 4})
        self.assertEqual(item["benchmark_id"], "upgrade-scripts:17-18")
        self.assertEqual(item["benchmark_size"], 4)

        full = xc.xc_upgrade(refs, _changes(*[r["subject_key"] for r in refs]), step="17-18")
        self.assertEqual(full["status"], "PASS")
        self.assertEqual((full["recall"]["found"], full["recall"]["referenced"]), (4, 4))

        none_referenced = xc.xc_upgrade([], changes, step="17-18")
        self.assertEqual(none_referenced["status"], "NOT_MEASURED")
        self.assertNotIn("recall", none_referenced)

    def test_recall_requires_benchmark(self):
        with self.assertRaises(xc.CrossCheckError):
            xc.recall_entry(2, 3, None, 3)
        with self.assertRaises(xc.CrossCheckError):
            xc.recall_entry(2, 3, "", 3)
        entry = xc.recall_entry(2, 3, "regression:tests/regression/known.json", 3)
        self.assertEqual(entry["benchmark_id"], "regression:tests/regression/known.json")

        # a benchmark-less XC-BENCH result has no recall key and is reported as NOT_MEASURED
        item = xc.xc_bench({"benchmark_id": None, "expected": ["a::field::b"], "found": ["a::field::b"]})
        self.assertEqual(item["status"], "NOT_MEASURED")
        self.assertNotIn("recall", item)
        self.assertIsNone(item["benchmark_id"])

    def test_xc_bench_recall_names_benchmark(self):
        item = xc.xc_bench({"benchmark_id": "golden-corpus", "expected": ["a::field::x", "a::method::y"],
                            "found": ["a::field::x"]})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["recall"]["benchmark_id"], "golden-corpus")
        self.assertEqual(item["recall"]["benchmark_size"], 2)
        self.assertEqual((item["recall"]["found"], item["recall"]["referenced"]), (1, 2))

    def test_not_run_reported(self):
        items = xc.run_crosschecks({})
        ids = [item["id"] for item in items]
        for check_id in CHECK_IDS:
            self.assertIn(check_id, ids)
        for item in items:
            self.assertEqual(item["status"], "NOT_RUN", item["id"])
            self.assertNotIn("recall", item)

    def test_xc_indep_compares_independent_count(self):
        acc = FileAccounting("16-17", SS_FROM, SS_TO, {"a.py": "added", "b.py": "modified"}, independent_count=3)
        acc.set_state("a.py", "ANALYZED")
        acc.set_state("b.py", "EXCLUDED", reason_code="OUT_OF_SCOPE_GLOB")
        item = xc.xc_indep([acc.document()])
        self.assertEqual(item["status"], "FAIL")
        acc2 = FileAccounting("16-17", SS_FROM, SS_TO, {"a.py": "added"}, independent_count=1)
        acc2.set_state("a.py", "ANALYZED")
        self.assertEqual(xc.xc_indep([acc2.document()])["status"], "PASS")

    def test_xc_kb_requires_seen_or_reasoned_absence(self):
        rules = [{"rule_id": "KB-1", "subject_key": "a::field::x"}, {"rule_id": "KB-2", "subject_key": "a::field::y"}]
        changes = _changes("a::field::x")
        self.assertEqual(xc.xc_kb(rules, changes, {})["status"], "FAIL")
        ok = xc.xc_kb(rules, changes, {"a::field::y": "subject removed before 17.0 scope"})
        self.assertEqual(ok["status"], "PASS")
        blank = xc.xc_kb(rules, changes, {"a::field::y": ""})
        self.assertEqual(blank["status"], "FAIL")

    def test_xc_regr_recall_named_by_file(self):
        item = xc.xc_regr("tests/regression/known.json", ["R-1", "R-2", "R-3"], ["R-1", "R-3"])
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["recall"]["benchmark_id"], "regression:tests/regression/known.json")
        self.assertEqual((item["recall"]["found"], item["recall"]["referenced"]), (2, 3))


if __name__ == "__main__":
    unittest.main()
