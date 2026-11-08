"""TST-007-002 (REQ-AI-001): core modules import no provider SDK and no odooflux.ai.providers.*."""

import ast
import sys
import unittest

from ._setup_path import SRC


def imports(source: str) -> list:
    names = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def violations(source: str, path: str = "x.py") -> list:
    bad = []
    for name in imports(source):
        top = name.split(".")[0]
        if name.startswith("odooflux.ai") or (top != "odooflux" and top not in sys.stdlib_module_names):
            bad.append(f"{path}: {name}")
    return bad


class CoreIsolationTests(unittest.TestCase):
    def test_core_imports_no_provider_or_third_party(self):
        problems = []
        for file in sorted((SRC / "odooflux" / "core").rglob("*.py")):
            problems += violations(file.read_text(encoding="utf-8"), file.relative_to(SRC).as_posix())
        self.assertEqual(problems, [])

    def test_cli_option_module_does_not_import_ai_package(self):
        text = (SRC / "odooflux" / "cli" / "ai_options.py").read_text(encoding="utf-8") \
            if (SRC / "odooflux" / "cli" / "ai_options.py").exists() else ""
        self.assertEqual([n for n in imports(text) if n.startswith("odooflux.ai")], [])

    def test_planted_violations_are_flagged(self):
        self.assertTrue(violations("import anthropic\n"))
        self.assertTrue(violations("from odooflux.ai.providers.fake import FakeProvider\n"))
        self.assertEqual(violations("import json\nfrom odooflux.utils import redact\n"), [])


if __name__ == "__main__":
    unittest.main()
