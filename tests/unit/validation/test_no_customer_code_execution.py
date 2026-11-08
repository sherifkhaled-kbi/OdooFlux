"""TST-008-013 (REQ-SEC-001, FR-011): the package never imports or executes scanned (customer) code.

Customer code runs only inside the container, through the Docker CLI. The AST scan finds no dynamic import, exec,
eval, compile, or runpy anywhere in the package, and no ``importlib`` import outside the one allow-listed plugin
loader. ``subprocess`` is allowed only in the runtime adapter (docker CLI invocations)."""

import ast
import unittest

from .._setup import SRC  # noqa: F401

PKG = SRC / "odooflux"
FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__"}
FORBIDDEN_MODULES = {"runpy"}
# cli/plugins.py is the explicit allow-list entry for ``--plugin`` (see tests/unit/test_no_code_execution.py).
PLUGIN_LOADER = {"cli/plugins.py"}
IMPORTLIB_ALLOW = PLUGIN_LOADER
# knowledge/acquisition/adapters/git_local.py: the same pattern as knowledge/refresh.py: read-only git plumbing against a
# LOCAL clone, shell=False, cleared environment, no system or global git config, core.fsmonitor off; the exact command set
# is pinned by tests/unit/knowledge/kap/test_git_local_readonly.py. It never executes scanned code.
SUBPROCESS_ALLOW_PREFIX = ("validation/runtime/", "validation/behavioral/", "knowledge/refresh.py",
                           "knowledge/acquisition/adapters/git_local.py")


def violations(source: str, rel: str) -> list:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            found.append((node.lineno, node.func.id))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
            found.append((node.lineno, "import_module"))
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in FORBIDDEN_MODULES:
                found.append((node.lineno, f"import {top}"))
            if top == "importlib" and rel not in IMPORTLIB_ALLOW:
                found.append((node.lineno, "import importlib"))
            if top == "subprocess" and not rel.startswith(SUBPROCESS_ALLOW_PREFIX):
                found.append((node.lineno, "import subprocess outside the runtime adapter"))
    return found


class NoCustomerCodeExecutionTests(unittest.TestCase):
    def test_package_has_no_dynamic_execution(self):
        problems = []
        for file in sorted(PKG.rglob("*.py")):
            rel = file.relative_to(PKG).as_posix()
            if rel in PLUGIN_LOADER:
                continue
            for line, what in violations(file.read_text(encoding="utf-8"), rel):
                problems.append(f"{rel}:{line} {what}")
        self.assertEqual(problems, [])

    def test_planted_violations_are_detected(self):
        self.assertTrue(violations("exec(code)\n", "x.py"))
        self.assertTrue(violations("import runpy\n", "x.py"))
        self.assertTrue(violations("import importlib\n", "x.py"))
        self.assertTrue(violations("import subprocess\n", "core/x.py"))
        self.assertEqual(violations("import subprocess\n", "validation/runtime/docker_env.py"), [])


if __name__ == "__main__":
    unittest.main()
