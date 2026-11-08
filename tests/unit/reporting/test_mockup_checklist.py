"""T025 automated part (REQ-REP-002, REQ-REP-006): a checklist of the sections and labels the
docs/planning/REPORTING_AND_UX.md mockups require, asserted against the real renderers.

This is NOT mockup parity certification. Whether the rendering matches the intended design (layout, wording,
usability on real terminals) is a human review item: Certification: PENDING_HUMAN_REVIEW (see
docs/reviews/fragments/ws-d-human-review.md). The deviations below are known and listed for that reviewer."""

import re
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from .helpers import golden

DOC = Path(__file__).resolve().parents[3] / "docs" / "planning" / "REPORTING_AND_UX.md"

# (mockup heading in the doc, strings the terminal output must contain, golden that exercises it)
TERMINAL = [
    ("Mockup — progress", ["PROGRESS", "[1/4] kbi_sale_approval"], "mixed", {"verbose": True}),
    ("Mockup — per-module summary", ["MODULE RESULTS", "Status", "Module", "Open C/W/I", "Fixed", "Rejected", "Layers",
                                      "Why not verified:"], "mixed", {}),
    ("Mockup — file detail with evidence", ["WARNING", "Action:", "Evidence:", "[NEEDS_REVIEW]", "FIXED"],
     "needs_review", {"show_fixed": True}),
    ("Mockup — rejected edits", ["REJECTED EDITS (2)", "reason:"], "failed", {}),
    ("Mockup — verification scope and AI usage", ["VERIFICATION SCOPE", "Ran:", "Not run:", "Limit:",
                                                   "AI USAGE  (enabled, consent given)", "requests", "budget event"],
     "ai_enabled", {}),
    ("Mockup — recovery", ["RECOVERY", "Run log:", "Roll back:"], "install_verified", {}),
]
HTML_SECTIONS = ["summary", "plan", "modules", "rejected", "scope", "ai", "recovery"]  # "Page outline"
KNOWN_DEVIATIONS = [
    "Plan line does not show per-step research status (the model carries step ids only).",
    "Progress lines are derived from the final model (module, status, layer outcomes); no live detect/fix counters.",
    "Verification scope lists layers, not sub-validators (for example the RNG view check): the model has no such data.",
    "Recovery shows run log and rollback only; no backup path and no resume line (not in the model).",
    "Layer outcomes are written as words (L1 PASS) instead of check marks, so no meaning depends on a symbol.",
]


def _terminal(name, **options):
    from odooflux.reporting.options import RendererOptions
    from odooflux.reporting.terminal.ansi import render_terminal
    return render_terminal(golden(name), RendererOptions(color="never", width=160, **options))


class MockupChecklistTests(unittest.TestCase):
    def test_doc_still_contains_the_mockups_this_checklist_was_derived_from(self):
        text = DOC.read_text(encoding="utf-8")
        for heading, *_ in TERMINAL:
            self.assertIn(heading, text)
        for needle in ('<section id="summary">', '<section id="recovery">'):
            self.assertIn(needle, text)

    def test_terminal_sections_required_by_the_mockups(self):
        for heading, needles, name, options in TERMINAL:
            output = _terminal(name, **options)
            for needle in needles:
                self.assertIn(needle, output, f"{heading}: {needle!r} missing from {name}")

    def test_accessibility_rules(self):
        output = _terminal("mixed")
        self.assertNotIn("\x1b", output)  # works without colour
        for word in ("CRITICAL", "WARNING"):
            self.assertIn(word, output)   # severity named, never colour alone

    def test_html_page_outline(self):
        from odooflux.reporting.html.html import render_html
        page = render_html(golden("mixed"))
        for section in HTML_SECTIONS:
            self.assertIn(f'<section id="{section}">', page)
        for tag in ("<header>", "<nav>", "<footer>", "<details"):
            self.assertIn(tag, page)

    def test_exit_code_table_in_doc_matches_constants(self):
        from odooflux.cli import exit_codes as e
        text = DOC.read_text(encoding="utf-8")
        rows = dict(re.findall(r"^\| (\d) \| (.+?) \|$", text, re.M))
        self.assertEqual(sorted(rows), ["0", "1", "2", "3", "4"])
        self.assertEqual((e.OK, e.THRESHOLD, e.USAGE, e.REJECTED, e.BLOCKED), (0, 1, 2, 3, 4))

    def test_known_deviations_are_recorded(self):
        self.assertGreaterEqual(len(KNOWN_DEVIATIONS), 5)


if __name__ == "__main__":
    unittest.main()
