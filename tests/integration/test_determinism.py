"""TST-003-023 (REQ-ARC-005, SC-005): two runs give identical normalised v1 reports."""

import unittest

from .helpers import make_module, new_tmp, run_cli_main
from odooflux.reporting.model.schema_check import validate_report
import json


def _report(root, module, state, name):
    out = root / f"{name}.json"
    run_cli_main(["--module", module, "--from-version", "14", "--no-color", "--report-format", "json",
                  "--report", out, "--state-dir", state])
    return json.loads(out.read_text(encoding="utf-8"))


def _normal(report, roots):
    text = json.dumps(report, sort_keys=True)
    for root in roots:
        text = text.replace(str(root), "<ROOT>")
    data = json.loads(text)
    for key in ("run_id", "rollback_cmd", "run_log"):
        data["run"].pop(key, None)
        data["recovery"].pop(key, None)
    return data


class DeterminismTests(unittest.TestCase):
    def test_analysis_is_identical_across_runs(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        first = _report(root, module, root / "s1", "a")
        second = _report(root, module, root / "s2", "b")
        self.assertEqual(validate_report(first), [])
        self.assertEqual(_normal(first, [root]), _normal(second, [root]))

    def test_fix_runs_on_two_copies_are_identical_after_normalising_the_root(self):
        results = []
        roots = []
        for name in ("one", "two"):
            root = new_tmp()
            roots.append(root)
            module = make_module(root, "kbi_demo")
            results.append(_normal(_report_fix(root, module), [root]))
        self.assertEqual(results[0], results[1])


def _report_fix(root, module):
    out = root / "fix.json"
    run_cli_main(["--module", module, "--from-version", "14", "--fix", "--no-color", "--report-format", "json",
                  "--report", out, "--state-dir", root / "state"])
    return json.loads(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
