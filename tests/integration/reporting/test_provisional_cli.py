"""ADR-019 item 4 through the CLI: a run is labelled PROVISIONAL by ``--provisional-corpus`` or by a PROVISIONAL.md
marker above the module; JSON, SARIF, HTML and the terminal all show it; an ordinary run carries no label."""

import json
import shutil
import unittest

from tests.unit.reporting import _setup  # noqa: F401
from tests.integration.helpers import make_module, new_tmp
from tests.integration.reporting.cli import run_cli_main


class ProvisionalCliTests(unittest.TestCase):
    def setUp(self):
        self.root = new_tmp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.out = self.root / "out"
        self.out.mkdir()

    def _run(self, addons, *extra):
        module = make_module(addons, "kbi_demo")
        code, text = run_cli_main(["--module", module, "--from-version", "14", "--state-dir", self.root / "s",
                                   "--no-color", "--fail-on", "none", "--report", self.out / "r.json",
                                   "--report-format", "json", "--sarif", self.out / "r.sarif",
                                   "--html", self.out / "r.html", "--ui", "ansi", *extra])
        return json.loads((self.out / "r.json").read_text(encoding="utf-8")), text

    def _assert_everywhere(self, report, text):
        self.assertTrue(report["provisional"]["active"])
        self.assertTrue(any("PROVISIONAL" in label for label in report["provisional"]["labels"]))
        sarif = json.loads((self.out / "r.sarif").read_text(encoding="utf-8"))
        self.assertTrue(sarif["runs"][0]["properties"]["provisional"]["active"])
        self.assertIn('class="provisional"', (self.out / "r.html").read_text(encoding="utf-8"))
        self.assertIn("PROVISIONAL", text)

    def test_flag_labels_every_renderer(self):
        report, text = self._run(self.root / "addons", "--provisional-corpus")
        self._assert_everywhere(report, text)

    def test_marker_above_module_labels_automatically(self):
        addons = self.root / "corpus" / "17.0"
        addons.mkdir(parents=True)
        (addons / "PROVISIONAL.md").write_text("PROVISIONAL\n", encoding="utf-8")
        report, text = self._run(addons)
        self._assert_everywhere(report, text)

    def test_ordinary_run_is_not_labelled(self):
        report, text = self._run(self.root / "addons")
        self.assertNotIn("provisional", report)
        self.assertNotIn("PROVISIONAL", text)
        self.assertNotIn('class="provisional"', (self.out / "r.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
