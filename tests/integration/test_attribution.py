"""AF-11 (Acceptance Criterion 19): official attribution in --help, --version and the docs."""

import os
import subprocess
import sys
import unittest

from odooflux import __version__

from .helpers import REPO

FACTS = (
    "KnowledgeBI",
    "https://www.knowledgebi.net",
    "Sherif Khaled",
    "© 2026 KnowledgeBI. All rights reserved.",
)
VENV_SCRIPT = REPO / ".venv" / "bin" / "odooflux"


def _env():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run(argv):
    proc = subprocess.run(argv, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", timeout=300, env=_env())
    return proc.returncode, proc.stdout


class AttributionHelpTests(unittest.TestCase):
    def test_help_shows_all_facts_and_keeps_subcommands(self):
        code, out = _run([sys.executable, "-m", "odooflux", "--help"])
        self.assertEqual(code, 0, out)
        for fact in FACTS:
            self.assertIn(fact, out)
        self.assertIn("Subcommands: migrate (default), plan, rollback, resume, versions, knowledge.", out)


class AttributionVersionTests(unittest.TestCase):
    def _assert_version_output(self, code, out):
        self.assertEqual(code, 0, out)
        self.assertIn(f"odooflux {__version__}", out.splitlines()[0])
        for fact in FACTS:
            self.assertIn(fact, out)

    def test_version_module_run(self):
        code, out = _run([sys.executable, "-m", "odooflux", "--version"])
        self._assert_version_output(code, out)

    def test_version_launcher_script(self):
        code, out = _run([sys.executable, str(REPO / "odooflux.py"), "--version"])
        self._assert_version_output(code, out)

    def test_version_installed_entry_point(self):
        if not VENV_SCRIPT.exists():
            self.skipTest("no .venv/bin/odooflux in this checkout")
        code, out = _run([str(VENV_SCRIPT), "--version"])
        self._assert_version_output(code, out)


class AttributionDocsTests(unittest.TestCase):
    def test_readme_and_cli_doc_contain_facts(self):
        for relative in ("README.md", "docs/TECHNICAL_USAGE.md"):
            text = (REPO / relative).read_text(encoding="utf-8")
            for fact in FACTS:
                self.assertIn(fact, text, f"{relative} is missing {fact!r}")


if __name__ == "__main__":
    unittest.main()
