"""TST-002-009 (REQ-TST-005, SC-004): every test listed in tests/regression/INDEX.md exists and cites its finding ID."""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = Path(__file__).resolve().parent / "INDEX.md"
REQUIRED_FINDINGS = {"F-SAFE-1", "F-SAFE-2", "F-SAFE-3", "F-SAFE-4", "F-SAFE-5", "F-PY-1", "F-PY-2", "F-PY-4",
                     "F-PY-5", "F-PY-6", "F-XML-1", "F-XML-2", "F-XML-4", "F-REP-1", "F-MAN-1", "F-AI-6",
                     "F-VAL-1", "F-REP-3"}
_ROW = re.compile(r"^\|\s*(F-[A-Z]+-\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")


def parse_index(text: str) -> list:
    """(finding, [TST ids], test reference) for every table row."""
    rows = []
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if m:
            rows.append((m.group(1), re.findall(r"TST-\d{3}-\d{3}", m.group(2)), m.group(3)))
    return rows


def reference_problems(finding: str, reference: str, root: Path = ROOT) -> list:
    parts = reference.split("::")
    if len(parts) != 3:
        return [f"{finding}: reference {reference!r} is not path::Class::method"]
    path, cls_name, method = parts
    file = root / path
    if not file.is_file():
        return [f"{finding}: {path} does not exist"]
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name):
        for func in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method):
            docs = (ast.get_docstring(func) or "") + " " + (ast.get_docstring(cls) or "")
            if finding not in docs:
                return [f"{finding}: docstring of {cls_name}.{method} (or its class) does not contain the ID"]
            return []
    return [f"{finding}: {cls_name}.{method} not found in {path}"]


class RegressionIndexTests(unittest.TestCase):
    def setUp(self):
        self.rows = parse_index(INDEX.read_text(encoding="utf-8"))

    def test_all_p0_findings_listed_with_a_test(self):
        self.assertEqual({f for f, _, _ in self.rows}, REQUIRED_FINDINGS)
        for finding, tst_ids, reference in self.rows:
            self.assertTrue(tst_ids, f"{finding} has no TST ID")
            self.assertTrue(reference, f"{finding} has no test")

    def test_every_listed_test_exists_and_cites_the_finding(self):
        problems = [p for f, _, r in self.rows for p in reference_problems(f, r)]
        self.assertEqual(problems, [])

    def test_checker_detects_wrong_reference(self):
        good = "tests/regression/test_p0_safety_readonly.py::AnalysisIsReadOnlyTests::test_analyze_is_read_only"
        self.assertEqual(reference_problems("F-SAFE-1", good), [])
        self.assertTrue(reference_problems("F-SAFE-9", good))
        self.assertTrue(reference_problems("F-SAFE-1", good.replace("test_analyze_is_read_only", "test_nope")))
        self.assertTrue(reference_problems("F-SAFE-1", "tests/regression/missing.py::A::b"))


if __name__ == "__main__":
    unittest.main()
