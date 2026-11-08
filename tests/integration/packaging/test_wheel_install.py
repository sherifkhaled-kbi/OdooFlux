"""T027 (FC A-10): install the built wheel in a clean venv and use it from outside the repository.

Opt-in (slow: builds a wheel and a venv): ``ODOOFLUX_PACKAGING_INSTALL=1``.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import _wheel

FIXTURE = _wheel.REPO / "tests" / "golden_fixtures" / "p0_kbi_demo_v14"


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@unittest.skipUnless(os.environ.get("ODOOFLUX_PACKAGING_INSTALL") == "1",
                     "opt-in: set ODOOFLUX_PACKAGING_INSTALL=1 (builds a wheel and a venv)")
@unittest.skipIf(_wheel.tooling_gap(), _wheel.tooling_gap() or "n/a")
class WheelInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="odooflux-install-"))
        venv = cls.work / "venv"
        made = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True)
        if made.returncode:
            raise unittest.SkipTest("cannot create a venv with pip (ensurepip unavailable): " + made.stderr[-300:])
        cls.py = venv / "bin" / "python"
        cls.exe = venv / "bin" / "odooflux"
        done = subprocess.run([str(cls.py), "-m", "pip", "install", "--no-index", "--no-deps",
                               str(_wheel.build_wheel())], capture_output=True, text=True, env=_clean_env())
        if done.returncode:
            raise RuntimeError("install failed:\n" + done.stdout[-1500:] + done.stderr[-1500:])
        cls.outside = cls.work / "outside"
        cls.outside.mkdir()

    def _run(self, *args):
        return subprocess.run([str(self.exe), *map(str, args)], cwd=self.outside, capture_output=True, text=True,
                              env=_clean_env(), timeout=300)

    def test_package_imports_from_site_packages_not_the_repo(self):
        proc = subprocess.run([str(self.py), "-c", "import odooflux; print(odooflux.__file__)"], cwd=self.outside,
                              capture_output=True, text=True, env=_clean_env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("site-packages", proc.stdout)
        self.assertNotIn(str(_wheel.REPO), proc.stdout)

    def test_help(self):
        proc = self._run("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("migrate", proc.stdout + proc.stderr)

    def test_knowledge_validate_uses_packaged_data(self):
        proc = self._run("knowledge", "validate")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_analyze_fixture_from_outside_the_repo(self):
        module = self.outside / "kbi_demo"
        subprocess.run(["cp", "-r", str(FIXTURE), str(module)], check=True)
        report = self.outside / "report.json"
        proc = self._run("--module", module, "--from-version", "14", "--to-version", "15", "--report-format", "json",
                         "--report", report, "--state-dir", self.outside / "state")
        self.assertIn(proc.returncode, (0, 1, 3), proc.stdout + proc.stderr)
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(data["modules"][0]["findings"])


if __name__ == "__main__":
    unittest.main()
