"""P0 User Story 1: analysis never changes a module (F-SAFE-1, F-SAFE-5, FR-001)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from tests._support.p0 import make_addons, run_cli, tree_digest


class AnalysisIsReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addons = make_addons(self.tmp)
        self.module = self.addons / "kbi_demo"
        self.state = self.tmp / "state"

    def tearDown(self):
        self._tmp.cleanup()

    def test_analyze_is_read_only(self):
        """F-SAFE-1: analysis without --fix creates no __manifest__.py and changes no byte."""
        before = tree_digest(self.module)
        code, out = run_cli(["--module", self.module, "--from-version", "14",
                             "--no-color", "--state-dir", self.state])
        self.assertEqual(tree_digest(self.module), before)
        self.assertFalse((self.module / "__manifest__.py").exists())
        self.assertEqual(code, 1, out)  # critical findings remain: exit 1 (default --fail-on critical)
        self.assertIn("rename __openerp__.py -> __manifest__.py", out)  # reported as planned

    def test_dry_run_is_read_only(self):
        """FR-001: --fix --dry-run changes nothing and lists the edits it would apply."""
        before = tree_digest(self.module)
        code, out = run_cli(["--module", self.module, "--from-version", "14",
                             "--fix", "--dry-run", "--no-color", "--state-dir", self.state])
        self.assertEqual(tree_digest(self.module), before)
        self.assertIn("would change", out)
        # P2 (TST-003-030): a dry run creates only runs/<id>/{state.json,log}; no backup, no work copy.
        (run,) = list((self.state / "runs").iterdir())
        self.assertEqual(sorted(p.name for p in run.iterdir()), ["log", "state.json"])


class BothManifestsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addons = make_addons(self.tmp)
        self.module = self.addons / "kbi_demo"
        (self.module / "__manifest__.py").write_text(
            "{'name': 'KBI Demo', 'version': '14.0.1.0.0'}\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_both_manifests_reported_not_copied(self):
        """F-SAFE-5: when both manifests exist, report the duplicate and do not copy or rename."""
        files_before = {rel for rel, _ in tree_digest(self.module)}
        openerp_before = (self.module / "__openerp__.py").read_bytes()
        code, out = run_cli(["--module", self.module, "--from-version", "14", "--fix",
                             "--no-color", "--state-dir", self.tmp / "state"])
        files_after = {rel for rel, _ in tree_digest(self.module)}
        self.assertEqual(files_after, files_before)
        self.assertEqual((self.module / "__openerp__.py").read_bytes(), openerp_before)
        self.assertIn("Duplicate Manifest", out)


if __name__ == "__main__":
    unittest.main()
