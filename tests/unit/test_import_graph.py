"""TST-003-001 (REQ-ARC-001, FR-001): core packages import only the standard library and other core packages."""

import ast
import sys
import unittest
from pathlib import Path

from ._setup import SRC

CORE = ("core", "discovery", "versions", "dependencies", "reporting/model", "utils", "cli",
        "validation/syntax", "validation/static", "rules/shared", "knowledge",
        "analyzers", "validation/dependency")  # knowledge: stdlib-only data validation (P3)
CORE_MODULES = {c.replace("/", ".") for c in CORE}
# lxml is the optional RNG adapter (D-02, REQ-XML-004): imported only inside validate_views and treated as
# absent when missing. This is the single sanctioned non-stdlib import in the core packages.
OPTIONAL_IMPORTS = {"odooflux/validation/static/rng.py: lxml", "odooflux/validation/static/rng.py: lxml.etree"}


def _is_core_target(name: str) -> bool:
    return any(name == "odooflux" + "." + c or name.startswith("odooflux." + c + ".") for c in CORE_MODULES) \
        or name == "odooflux"


def violations(source: str, path: str = "x.py") -> list:
    found = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top == "odooflux":
                if not _is_core_target(name):
                    found.append(f"{path}: {name}")
            elif top not in sys.stdlib_module_names:
                found.append(f"{path}: {name}")
    return found


class ImportGraphTests(unittest.TestCase):
    def test_core_packages_import_only_stdlib_and_core(self):
        problems = []
        for sub in CORE:
            for file in sorted((SRC / "odooflux" / sub).rglob("*.py")):
                rel = file.relative_to(SRC).as_posix()
                problems += [v for v in violations(file.read_text(encoding="utf-8"), rel)
                             if v not in OPTIONAL_IMPORTS]
        self.assertEqual(problems, [])

    def test_planted_third_party_import_is_flagged(self):
        self.assertTrue(violations("import requests\n"))
        self.assertTrue(violations("from odooflux.ai.providers import x\n"))
        self.assertEqual(violations("import json\nfrom odooflux.utils.hashing import sha256_bytes\n"), [])


if __name__ == "__main__":
    unittest.main()
