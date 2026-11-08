"""TST-084 (REQ-KAP-003, REQ-KAP-001, REQ-KAP-004): static import-graph rules for the KAP packages.

AST scans only: no scanned module is imported or executed. Rules:
- (a) no `sqlite3` anywhere under `knowledge/` or in `cli/kap_*.py`;
- (b) no network module (urllib, socket, http, ssl, ftplib, smtplib, requests-like) in the KAP scope except
      `knowledge/acquisition/fetch.py`, and `urlopen` is called only from `fetch.py`;
- (c) every import in the KAP scope is stdlib or `odooflux`; no dynamic import (`__import__`,
      `import_module`) that could hide a third-party or network module.

Each check has planted-violation tests proving that it fails on a bad snippet. The allow-lists of the existing
guards (`tests/unit/test_import_graph.py`, `tests/unit/validation/test_no_customer_code_execution.py`,
`tests/unit/knowledge/kap/test_knowledge_root_guard.py`) are not touched.
"""

import ast
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SRC = REPO / "src"
PKG = SRC / "odooflux"
KNOWLEDGE = PKG / "knowledge"

KAP_DIRS = ("release", "package", "authoring", "acquisition", "extract", "ledger", "candidates", "coverage",
            "extraction_templates")
FETCH = KNOWLEDGE / "acquisition" / "fetch.py"

NETWORK_MODULES = frozenset({"urllib", "socket", "http", "ssl", "ftplib", "smtplib", "poplib", "imaplib",
                             "telnetlib", "xmlrpc", "socketserver", "requests", "httpx", "aiohttp", "urllib3"})
SQLITE_MODULES = frozenset({"sqlite3", "_sqlite3"})
DYNAMIC_IMPORT_NAMES = frozenset({"__import__", "import_module"})


def kap_scope_files() -> list:
    """Every .py file of the KAP packages, pipeline.py, parsers/extract_toolkit.py and cli/kap_*.py."""
    files = [KNOWLEDGE / "pipeline.py", PKG / "parsers" / "extract_toolkit.py"]
    for name in KAP_DIRS:
        files += (KNOWLEDGE / name).rglob("*.py")
    files += (PKG / "cli").glob("kap_*.py")
    return sorted({f for f in files if f.is_file() and "__pycache__" not in f.parts})


def knowledge_and_kap_cli_files() -> list:
    """Every .py file under src/odooflux/knowledge plus cli/kap_*.py (rule a)."""
    files = [f for f in KNOWLEDGE.rglob("*.py") if "__pycache__" not in f.parts]
    files += (PKG / "cli").glob("kap_*.py")
    return sorted(set(files))


def _imports(tree):
    """(line, top-level module) for every absolute import in the tree, including function-level imports."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name.split(".")[0]) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def sqlite_hits(source: str) -> list:
    return [(line, top) for line, top in _imports(ast.parse(source)) if top in SQLITE_MODULES]


def network_hits(source: str) -> list:
    """Network imports plus every `urlopen` call (attribute or bare name)."""
    tree = ast.parse(source)
    hits = [(line, top) for line, top in _imports(tree) if top in NETWORK_MODULES]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == "urlopen":
                hits.append((node.lineno, "urlopen"))
    return hits


def nonstdlib_hits(source: str) -> list:
    """Absolute imports that are neither stdlib nor `odooflux`, and dynamic-import calls."""
    tree = ast.parse(source)
    hits = [(line, top) for line, top in _imports(tree)
            if top != "odooflux" and top not in sys.stdlib_module_names]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in DYNAMIC_IMPORT_NAMES:
                hits.append((node.lineno, name))
    return hits


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


class KapImportGraphTests(unittest.TestCase):
    def test_scope_is_populated(self):
        self.assertGreater(len(kap_scope_files()), 40)
        self.assertIn(FETCH, kap_scope_files())

    def test_no_sqlite(self):
        problems = []
        for file in knowledge_and_kap_cli_files():
            problems += [f"{_rel(file)}:{line}: {name}" for line, name in sqlite_hits(file.read_text("utf-8"))]
        self.assertEqual(problems, [])

    def test_network_only_in_fetch(self):
        problems = []
        for file in kap_scope_files():
            if file == FETCH:
                continue
            problems += [f"{_rel(file)}:{line}: {name}" for line, name in network_hits(file.read_text("utf-8"))]
        self.assertEqual(problems, [])
        # positive control: the scanner really does see the sanctioned network import in fetch.py
        self.assertTrue(network_hits(FETCH.read_text("utf-8")))

    def test_stdlib_only(self):
        problems = []
        for file in kap_scope_files():
            problems += [f"{_rel(file)}:{line}: {name}" for line, name in nonstdlib_hits(file.read_text("utf-8"))]
        self.assertEqual(problems, [])


class PlantedViolationTests(unittest.TestCase):
    """Each check must fail on a bad snippet and pass on a clean one."""

    def test_sqlite_planted(self):
        self.assertTrue(sqlite_hits("import sqlite3\n"))
        self.assertTrue(sqlite_hits("from sqlite3 import connect\n"))
        self.assertTrue(sqlite_hits("def f():\n    import sqlite3\n"))
        self.assertEqual(sqlite_hits("import json\nfrom odooflux.utils.hashing import sha256_bytes\n"), [])

    def test_network_planted(self):
        self.assertTrue(network_hits("import urllib.request\n"))
        self.assertTrue(network_hits("from urllib import request\n"))
        self.assertTrue(network_hits("import socket\n"))
        self.assertTrue(network_hits("from http.client import HTTPSConnection\n"))
        self.assertTrue(network_hits("import ssl\n"))
        self.assertTrue(network_hits("import requests\n"))
        self.assertTrue(network_hits("def f(u):\n    return opener.urlopen(u)\n"))
        self.assertTrue(network_hits("def f(u):\n    return urlopen(u)\n"))
        self.assertEqual(network_hits("import json\nfrom odooflux.knowledge.acquisition import blobstore\n"), [])

    def test_stdlib_planted(self):
        self.assertTrue(nonstdlib_hits("import requests\n"))
        self.assertTrue(nonstdlib_hits("import yaml\n"))
        self.assertTrue(nonstdlib_hits("import tree_sitter\n"))
        self.assertTrue(nonstdlib_hits("def f():\n    import tree_sitter_javascript\n"))
        self.assertTrue(nonstdlib_hits("import importlib\nimportlib.import_module('requests')\n"))
        self.assertTrue(nonstdlib_hits("__import__('yaml')\n"))
        self.assertEqual(nonstdlib_hits("import json\nfrom . import x\nfrom odooflux.utils import y\n"), [])


if __name__ == "__main__":
    unittest.main()
