"""TST-003-040 (R-01, ADR-001): the root launcher resolves odooflux to src/odooflux and runs the CLI."""

import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class LauncherResolutionTests(unittest.TestCase):
    def test_launcher_imports_the_package_from_src(self):
        probe = (
            "import runpy\n"
            "runpy.run_path('odooflux.py', run_name='probe')\n"
            "import odooflux as pkg\n"
            "print(pkg.__file__)\n")
        proc = subprocess.run([sys.executable, "-c", probe], cwd=REPO, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        resolved = Path(proc.stdout.strip().splitlines()[-1]).resolve()
        self.assertEqual(resolved, (REPO / "src" / "odooflux" / "__init__.py").resolve())

    def test_help_runs_through_the_launcher(self):
        proc = subprocess.run([sys.executable, "odooflux.py", "--help"], cwd=REPO, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("usage: odooflux", proc.stdout)


if __name__ == "__main__":
    unittest.main()
