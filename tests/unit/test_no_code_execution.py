"""TST-003-002 (REQ-SEC-001, FR-019): no exec/eval/importlib/runpy on customer or scanned code.
``pkg/cli/plugins.py`` is the explicit allow-list entry for ``--plugin``."""

import ast
import unittest

from ._setup import SRC

FORBIDDEN_NAMES = {"exec", "eval", "__import__"}
FORBIDDEN_ATTRS = {("importlib", "import_module"), ("runpy", "run_path"), ("runpy", "run_module")}
ALLOW_LIST = {"cli/plugins.py"}


def forbidden_uses(source: str) -> list:
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            hits.append((node.lineno, node.id))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and (node.value.id, node.attr) in FORBIDDEN_ATTRS:
            hits.append((node.lineno, f"{node.value.id}.{node.attr}"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "compile" \
                and len(node.args) >= 3 and isinstance(node.args[2], ast.Constant) and node.args[2].value == "exec":
            hits.append((node.lineno, "compile(..., 'exec')"))
        if isinstance(node, ast.ImportFrom) and node.module in ("runpy",):
            hits.append((node.lineno, f"from {node.module}"))
    return hits


class NoCodeExecutionTests(unittest.TestCase):
    def test_package_has_no_dynamic_execution_outside_allow_list(self):
        problems = []
        for file in sorted((SRC / "odooflux").rglob("*.py")):
            rel = file.relative_to(SRC / "odooflux").as_posix()
            if rel in ALLOW_LIST:
                continue
            problems += [f"{rel}:{line} {what}" for line, what in forbidden_uses(file.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [])

    def test_planted_exec_is_flagged(self):
        self.assertEqual(forbidden_uses("exec(code)\n")[0][1], "exec")
        self.assertTrue(forbidden_uses("import importlib\nimportlib.import_module('x')\n"))
        self.assertEqual(forbidden_uses("ast.literal_eval(text)\n"), [])


if __name__ == "__main__":
    unittest.main()
