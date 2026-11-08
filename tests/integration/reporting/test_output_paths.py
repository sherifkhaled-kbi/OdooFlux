"""TST-009-012 (REQ-SEC-003, FR-009): report output paths inside scanned modules are refused with exit code 2 and
a clear message, before any processing."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.unit.reporting import _setup  # noqa: F401
from tests.integration.helpers import make_module, new_tmp, tree
from tests.integration.reporting.cli import run_cli_main

OPTIONS = ("--report", "--sarif", "--html", "--diff")


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.root = new_tmp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addons = self.root / "addons"
        self.module = make_module(self.addons, "kbi_demo")
        self.state = self.root / "state"

    def _run(self, option, target, *extra):
        before = tree(self.addons)
        code, out = run_cli_main(["--module", self.module, "--from-version", "14", option, target,
                                  "--state-dir", self.state, "--no-color", *extra])
        return code, out, before

    def test_each_output_option_refused_inside_module(self):
        for option in OPTIONS:
            target = self.module / "models" / f"out_{option.strip('-')}.dat"
            code, out, before = self._run(option, target)
            self.assertEqual(code, 2, f"{option}: {out}")
            self.assertIn("is inside the scanned module", out)
            self.assertIn(option, out)
            self.assertFalse(target.exists(), option)
            self.assertEqual(tree(self.addons), before, option)
            self.assertFalse(self.state.exists(), f"{option}: nothing may be processed before the refusal")

    def test_refused_before_any_processing_with_fix(self):
        code, out, before = self._run("--report", self.module / "r.json", "--fix")
        self.assertEqual(code, 2, out)
        self.assertEqual(tree(self.addons), before)

    def test_diff_index_sibling_also_checked(self):
        code, out, _ = self._run("--diff", self.module / "x.patch")
        self.assertEqual(code, 2, out)

    def test_inside_addons_path_refused(self):
        before = tree(self.addons)
        code, out = run_cli_main(["--addons-path", self.addons, "--from-version", "14", "--report",
                                  self.addons / "report.json", "--state-dir", self.state])
        self.assertEqual(code, 2, out)
        self.assertEqual(tree(self.addons), before)

    def test_dot_dot_traversal_refused(self):
        target = self.module / "models" / ".." / ".." / "kbi_demo" / "r.json"
        code, out, _ = self._run("--report", target)
        self.assertEqual(code, 2, out)

    def test_symlink_into_module_refused(self):
        link = self.root / "link"
        os.symlink(self.module, link)
        code, out, _ = self._run("--report", link / "r.json")
        self.assertEqual(code, 2, out)
        self.assertFalse((self.module / "r.json").exists())

    def test_outside_path_is_accepted(self):
        out_dir = self.root / "reports"
        out_dir.mkdir()
        code, out, _ = self._run("--report", out_dir / "r.json", "--report-format", "json")
        self.assertIn(code, (0, 1), out)
        self.assertTrue((out_dir / "r.json").exists())

    def test_sibling_directory_with_common_prefix_is_not_inside(self):
        sibling = self.addons / "kbi_demo_reports"
        sibling.mkdir()
        code, out, _ = self._run("--report", sibling / "r.json", "--report-format", "json")
        self.assertIn(code, (0, 1), out)
        self.assertTrue((sibling / "r.json").exists())

    def test_unit_check_function(self):
        from odooflux.reporting.model.output_paths import check_output_paths
        mod = Path(self.module)
        self.assertIsNone(check_output_paths({"--report": self.root / "a.json"}, [mod]))
        message = check_output_paths({"--html": mod / "a.html"}, [mod])
        self.assertIn("--html", message)
        self.assertIn(str(mod), message)
        self.assertIsNone(check_output_paths({"--html": None}, [mod]))


if __name__ == "__main__":
    unittest.main()
