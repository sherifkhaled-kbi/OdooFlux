"""TST-009-003 (REQ-REP-002, F-REP-2): colour and plain snapshots at widths 60/80/120 for every golden model.

Regenerate after a reviewed change: UPDATE_SNAPSHOTS=1 PYTHONPATH=src python3 -m unittest
tests.unit.reporting.test_terminal_snapshots"""

import os
import re
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from .helpers import GOLDEN_DIR, all_goldens

SNAP_DIR = GOLDEN_DIR / "snapshots"
WIDTHS = (60, 80, 120)
SGR = re.compile(r"\x1b\[[0-9;]*m")


def render(model, color, width):
    from odooflux.reporting.options import RendererOptions
    from odooflux.reporting.terminal.ansi import render_terminal
    return render_terminal(model, RendererOptions(color=color, width=width, show_fixed=True))


class SnapshotTests(unittest.TestCase):
    def test_snapshots_match(self):
        update = bool(os.environ.get("UPDATE_SNAPSHOTS"))
        SNAP_DIR.mkdir(exist_ok=True)
        for name, model in all_goldens().items():
            for mode, color in (("plain", "never"), ("colour", "always")):
                for width in WIDTHS:
                    path = SNAP_DIR / f"{name}.{mode}.{width}.txt"
                    text = render(model, color, width)
                    if update:
                        path.write_text(text, encoding="utf-8", newline="")
                    self.assertTrue(path.exists(), f"missing snapshot {path.name}")
                    self.assertEqual(path.read_text(encoding="utf-8"), text, path.name)

    def test_plain_has_no_ansi_and_fits_width(self):
        from odooflux.reporting.options import display_width
        for name, model in all_goldens().items():
            for width in WIDTHS:
                text = render(model, "never", width)
                self.assertNotIn("\x1b", text, name)
                for line in text.splitlines():
                    self.assertLessEqual(display_width(line), width, f"{name}@{width}: {line!r}")

    def test_colour_layout_identical_to_plain(self):
        """F-REP-2: colour adds only SGR sequences; stripped, the text equals the plain layout exactly."""
        for name, model in all_goldens().items():
            for width in WIDTHS:
                self.assertEqual(SGR.sub("", render(model, "always", width)), render(model, "never", width),
                                 f"{name}@{width}")

    def test_no_color_env_honoured_for_auto(self):
        from odooflux.reporting.options import RendererOptions
        opts = RendererOptions(color="auto")
        self.assertFalse(opts.use_color(is_tty=True, environ={"NO_COLOR": "1"}))
        self.assertTrue(opts.use_color(is_tty=True, environ={}))
        self.assertFalse(opts.use_color(is_tty=False, environ={}))

    def test_severity_never_by_colour_alone(self):
        text = SGR.sub("", render(all_goldens()["mixed"], "always", 120))
        for word in ("CRITICAL", "WARNING", "INFO"):
            self.assertIn(word, text)

    def test_wide_characters_do_not_break_alignment(self):
        from odooflux.reporting.options import display_width
        self.assertEqual(display_width("\x1b[31mabc\x1b[0m"), 3)
        self.assertEqual(display_width("日本"), 4)


if __name__ == "__main__":
    unittest.main()
