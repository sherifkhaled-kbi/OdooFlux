"""TST-002-002 (REQ-TST-004): normalisation replaces paths and timestamps and sorts issues."""

import unittest

from tests._support.normalize import normalize_report


def _report(module_path, ts, elapsed, issues):
    return {"module_path": module_path, "timestamp": ts,
            "summary": {"elapsed_seconds": elapsed, "total": len(issues)}, "issues": issues}


def _issue(root, file, line, category, message):
    return {"file": f"{root}/{file}", "line": line, "category": category, "message": message}


class NormalizeTests(unittest.TestCase):
    def test_same_report_from_two_temp_dirs_is_identical(self):
        issues = [("views/v.xml", 9, "B", "m2"), ("a.py", 3, "A", "m1")]
        one = _report("/tmp/aaa/kbi", "2026-01-01T00:00:00", 1.5, [_issue("/tmp/aaa/kbi", *i) for i in issues])
        two = _report("/tmp/bbb/kbi", "2027-02-02T10:10:10", 9.9, [_issue("/tmp/bbb/kbi", *i) for i in reversed(issues)])
        self.assertEqual(normalize_report(one, "/tmp/aaa/kbi"), normalize_report(two, "/tmp/bbb/kbi"))

    def test_fields_replaced_and_sorted(self):
        rep = _report("/x/m", "now", 3.0, [_issue("/x/m", "z.py", 1, "C", "m"), _issue("/x/m", "a.py", 2, "C", "m")])
        out = normalize_report(rep, "/x/m")
        self.assertEqual(out["module_path"], "<MODULE>")
        self.assertEqual(out["timestamp"], "<TS>")
        self.assertEqual(out["summary"]["elapsed_seconds"], 0)
        self.assertEqual([i["file"] for i in out["issues"]], ["a.py", "z.py"])

    def test_input_not_mutated(self):
        rep = _report("/x/m", "now", 3.0, [])
        normalize_report(rep, "/x/m")
        self.assertEqual(rep["timestamp"], "now")


if __name__ == "__main__":
    unittest.main()
