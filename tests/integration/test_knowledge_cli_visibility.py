"""AC-17: `knowledge` is discoverable from `odooflux --help` and `knowledge status` runs through the entry point."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run(*args):
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if k != "ODOOFLUX_KB_HOME"}
        env.update(PYTHONPATH=str(REPO / "src"), XDG_CACHE_HOME=tmp, XDG_DATA_HOME=tmp, ODOOFLUX_KB_HOME=tmp)
        return subprocess.run([sys.executable, "-m", "odooflux", *args], cwd=tmp, env=env,
                              capture_output=True, text=True, timeout=120)


class KnowledgeVisibility(unittest.TestCase):
    def test_main_help_lists_knowledge(self):
        out = _run("--help")
        self.assertEqual(out.returncode, 0)
        self.assertIn("knowledge", out.stdout)

    def test_knowledge_help_lists_subcommands(self):
        out = _run("knowledge", "--help")
        self.assertEqual(out.returncode, 0)
        for name in ("status", "update", "check", "validate"):
            self.assertIn(name, out.stdout)

    def test_knowledge_status_runs(self):
        out = _run("knowledge", "status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("OdooFlux Knowledge Status", out.stdout)

    def test_installed_entry_point_lists_and_runs_knowledge(self):
        exe = REPO / ".venv" / "bin" / "odooflux"
        if not exe.exists():
            self.skipTest("odooflux entry point not installed in .venv")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "ODOOFLUX_KB_HOME": tmp, "XDG_CACHE_HOME": tmp}
            helped = subprocess.run([str(exe), "--help"], capture_output=True, text=True, env=env, timeout=120)
            status = subprocess.run([str(exe), "knowledge", "status"], capture_output=True, text=True, env=env,
                                    timeout=120)
        self.assertIn("knowledge", helped.stdout)
        self.assertEqual(status.returncode, 0, status.stderr)


if __name__ == "__main__":
    unittest.main()
