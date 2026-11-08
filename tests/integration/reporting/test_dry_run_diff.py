"""WSD-05 follow-up (REQ-REP-004, FR-001): ``--fix --dry-run --diff`` exports the edits write mode would promote.

The dry run computes the same edits in memory and writes nothing into the module; its patch applies with ``patch -p1``
to a pristine copy and equals the write-mode patch and result byte for byte."""

import shutil
import subprocess
import unittest

from tests.unit.reporting import _setup  # noqa: F401
from tests.integration.helpers import make_module, new_tmp, tree
from tests.integration.reporting.cli import run_cli_main


def _files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class DryRunDiffTests(unittest.TestCase):
    def setUp(self):
        self.root = new_tmp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _cli(self, name, *extra):
        module = make_module(self.root / name / "addons", "kbi_demo")
        out = self.root / name / "out"
        out.mkdir(parents=True)
        code, text = run_cli_main(["--module", module, "--from-version", "14", "--state-dir", self.root / name / "s",
                                   "--no-color", "--fail-on", "none", "--diff", out / "d.patch", *extra])
        return module, out / "d.patch", code, text

    def test_dry_run_diff_is_non_empty_and_module_is_untouched(self):
        pristine = make_module(self.root / "pristine", "kbi_demo")
        module, patch, code, out = self._cli("dry", "--fix", "--dry-run")
        self.assertTrue(patch.read_bytes().strip(), out)
        self.assertEqual(tree(module), tree(pristine))
        self.assertNotIn("do not compute edits", out)
        self.assertFalse(any(p.name.endswith((".bak", ".orig")) for p in module.rglob("*")))

    @unittest.skipUnless(shutil.which("patch"), "patch(1) not available")
    def test_dry_run_diff_applies_and_equals_write_mode_output(self):
        pristine = make_module(self.root / "pristine", "kbi_demo")
        _, dry_patch, _, out = self._cli("dry", "--fix", "--dry-run")
        written, write_patch, _, _ = self._cli("write", "--fix")
        self.assertEqual(dry_patch.read_bytes(), write_patch.read_bytes())
        proc = subprocess.run(["patch", "-p1", "-d", str(self.root / "pristine" / "kbi_demo" / ".."), "-i", str(dry_patch),
                               "--no-backup-if-mismatch"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(_files(pristine), _files(written))

    def test_analyze_diff_is_still_empty(self):
        _, patch, _, out = self._cli("an")
        self.assertEqual(patch.read_text(), "")
        self.assertIn("do not compute edits", out)


if __name__ == "__main__":
    unittest.main()
