"""T011 (REQ-REP-002, D-07): the optional rich adapter is used only with --ui rich and only when importable."""

import importlib.util
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import golden

HAS_RICH = importlib.util.find_spec("rich") is not None


class RichAdapterTests(unittest.TestCase):
    def test_absent_rich_falls_back_to_ansi_without_error(self):
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal import rich_adapter
        from odooflux.reporting.terminal.ansi import render_terminal
        opts = RendererOptions(color="never", width=100)
        original = rich_adapter.rich_available
        rich_adapter.rich_available = lambda: False
        try:
            out, used = rich_adapter.render_ui(golden("mixed"), opts, ui="rich")
        finally:
            rich_adapter.rich_available = original
        self.assertEqual(used, "ansi")
        self.assertEqual(out, render_terminal(golden("mixed"), opts))

    def test_default_ui_is_ansi_even_when_rich_installed(self):
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal import rich_adapter
        out, used = rich_adapter.render_ui(golden("mixed"), RendererOptions(color="never"), ui="ansi")
        self.assertEqual(used, "ansi")
        out, used = rich_adapter.render_ui(golden("mixed"), RendererOptions(color="never"), ui="auto")
        self.assertEqual(used, "ansi")

    def test_unknown_ui_rejected(self):
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal import rich_adapter
        with self.assertRaises(ValueError):
            rich_adapter.render_ui(golden("mixed"), RendererOptions(), ui="fancy")

    def test_core_modules_do_not_import_rich_at_module_level(self):
        import ast
        import odooflux.reporting.terminal.ansi as ansi
        import odooflux.reporting.terminal.rich_adapter as adapter
        for module in (ansi, adapter):
            tree = ast.parse(__import__("pathlib").Path(module.__file__).read_text(encoding="utf-8"))
            for node in tree.body:
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) else [])
                self.assertFalse(any(n and n.split(".")[0] == "rich" for n in names), module.__name__)

    @unittest.skipUnless(HAS_RICH, "rich not installed (optional adapter)")
    def test_rich_render_carries_exact_counts(self):
        import re
        from odooflux.reporting.options import RendererOptions
        from odooflux.reporting.terminal import rich_adapter
        out, used = rich_adapter.render_ui(golden("mixed"), RendererOptions(color="never", width=120), ui="rich")
        self.assertEqual(used, "rich")
        self.assertRegex(re.sub(r"\x1b\[[0-9;]*m", "", out), r"TOTALS modules=4 findings=")
        self.assertIn("VERIFICATION SCOPE", out)


if __name__ == "__main__":
    unittest.main()
