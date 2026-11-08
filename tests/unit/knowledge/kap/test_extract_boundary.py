"""REQ-ARC-001, REQ-KAP-011: the KAP core (extract, candidates, kap CLI groups) reaches adapters only through injection.

The AST scan covers `knowledge/extract/` (including `domains/`), `knowledge/candidates/` and `cli/kap_*.py`. None of
them may import a non-core odooflux package that holds adapters (`parsers`, `rules`, `ai`, `validation.runtime`) or the
composition root (`builtins`). The one module that defines `ExtractToolkit` lives in the adapter layer, `parsers/`.
This is a regression test for the boundary; `tests/unit/test_import_graph.py` remains the guard for core packages.
"""

import ast
import unittest

from pathlib import Path

PKG = Path(__file__).resolve().parents[4] / "src" / "odooflux"
SCOPED = (PKG / "knowledge" / "extract", PKG / "knowledge" / "candidates")
FORBIDDEN_PREFIXES = ("odooflux.parsers", "odooflux.rules", "odooflux.ai", "odooflux.validation.runtime",
                      "odooflux.builtins")


def boundary_violations(source: str, path: str = "x.py") -> list:
    found = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
            if node.module == "odooflux":
                names += [f"odooflux.{a.name}" for a in node.names]
        for name in names:
            if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                found.append(f"{path}:{node.lineno} {name}")
    return found


def scoped_files() -> list:
    files = []
    for base in SCOPED:
        files += sorted(base.rglob("*.py"))
    files += sorted((PKG / "cli").glob("kap_*.py"))
    return files


class KapBoundaryTests(unittest.TestCase):
    def test_kap_core_imports_no_adapters_or_composition_root(self):
        problems = []
        for file in scoped_files():
            rel = file.relative_to(PKG.parent).as_posix()
            problems += boundary_violations(file.read_text(encoding="utf-8"), rel)
        self.assertEqual(problems, [])

    def test_scope_is_not_empty(self):
        self.assertTrue(any(f.name == "driver.py" for f in scoped_files()))
        self.assertTrue(any(f.name == "kap_extract.py" for f in scoped_files()))

    def test_extract_toolkit_is_the_only_definition_in_the_adapter_layer(self):
        definitions = []
        for file in sorted(PKG.rglob("*.py")):
            if "class ExtractToolkit" in file.read_text(encoding="utf-8"):
                definitions.append(file)
        self.assertEqual([f.relative_to(PKG).as_posix() for f in definitions], ["parsers/extract_toolkit.py"])

    def test_planted_violations_are_detected(self):
        self.assertTrue(boundary_violations("from odooflux.parsers.python.document import parse\n"))
        self.assertTrue(boundary_violations("import odooflux.builtins\n"))
        self.assertTrue(boundary_violations("from odooflux.rules.bindable import BINDABLE_MODULES\n"))
        self.assertTrue(boundary_violations("from odooflux import builtins\n"))
        self.assertTrue(boundary_violations("from odooflux.ai.providers import x\n"))
        self.assertEqual(boundary_violations("from odooflux.knowledge.extract.driver import ParseFailure\n"), [])
        self.assertEqual(boundary_violations("import json\nfrom odooflux.parsers_note import x\n"), [])


if __name__ == "__main__":
    unittest.main()
