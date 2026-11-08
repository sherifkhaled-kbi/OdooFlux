"""Review R3 finding F-R3-1: a directory without __manifest__.py must not be reported as 'clean' (L3 could not run)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_cli(module: Path, state: Path) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), ODOOFLUX_STATE_DIR=str(state), HOME=str(state))
    proc = subprocess.run([sys.executable, "-m", "odooflux", "migrate", "--module", str(module),
                           "--from-version", "17.0", "--to-version", "18.0", "--no-color"],
                          capture_output=True, text=True, env=env, cwd=str(state))
    return proc.stdout + proc.stderr


class NoManifestNotCleanTests(unittest.TestCase):
    def test_manifestless_module_is_not_called_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "foo"
            module.mkdir()
            (module / "a.py").write_text("a = 1\n")
            out = run_cli(module, Path(tmp))
        self.assertNotIn("Module looks clean", out)
        self.assertIn("no __manifest__.py", out)
        self.assertNotIn("Traceback", out)

    def test_module_with_manifest_gets_no_missing_manifest_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "foo"
            module.mkdir()
            (module / "__manifest__.py").write_text("{'name': 'x', 'version': '18.0.1.0.0', 'depends': ['base']}\n")
            (module / "__init__.py").write_text("")
            out = run_cli(module, Path(tmp))
        self.assertNotIn("no __manifest__.py", out)  # the warning is only for manifest-less directories
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main()
