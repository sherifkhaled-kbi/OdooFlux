"""TST-009-005 (REQ-REP-002, REQ-SEC-004, FR-008): untrusted text cannot inject escape sequences or control
characters into the terminal."""

import re
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import golden

OWN_SGR = re.compile(r"\x1b\[(?:\d{1,3}(?:;\d{1,3})*)m")
BAD = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f-\x9f]")


def render(color, width=100):
    from odooflux.reporting.options import RendererOptions
    from odooflux.reporting.terminal.ansi import render_terminal
    return render_terminal(golden("hostile"), RendererOptions(color=color, width=width, show_fixed=True))


class EscapingTests(unittest.TestCase):
    def test_plain_has_no_escape_or_control_characters(self):
        text = render("never")
        self.assertNotIn("\x1b", text)
        self.assertIsNone(BAD.search(text))

    def test_colour_contains_only_our_sgr(self):
        text = render("always")
        stripped = OWN_SGR.sub("", text)
        self.assertNotIn("\x1b", stripped)
        self.assertIsNone(BAD.search(stripped))

    def test_injection_is_visible_not_interpreted(self):
        text = render("never", 200)
        self.assertIn("<U+001B>[31mRED<U+001B>[0m", text)
        self.assertIn("<U+0007>", text)

    def test_sanitize_text_unit(self):
        from odooflux.reporting.options import sanitize_text
        self.assertEqual(sanitize_text("a\x1b[2Jb"), "a<U+001B>[2Jb")
        self.assertEqual(sanitize_text("l1\nl2\r\nl3\tx"), "l1 l2 l3 x")
        self.assertEqual(sanitize_text("\x9b31m"), "<U+009B>31m")
        self.assertEqual(sanitize_text("plain ünïcode"), "plain ünïcode")

    def test_module_and_path_fields_sanitised(self):
        model = golden("hostile")
        model["modules"][0]["name"] = "evil\x1b[2Jmod"
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal.ansi import render_terminal
        text = render_terminal(model, RendererOptions(color="never", width=100))
        self.assertNotIn("\x1b", text)


if __name__ == "__main__":
    unittest.main()
