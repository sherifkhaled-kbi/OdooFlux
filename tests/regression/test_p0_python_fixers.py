"""P0 Python fixers: F-PY-1..6, EV-101/102/103, FR-007 and FR-013."""

import ast
import unittest
from pathlib import Path

import odooflux.rules.shared.legacy_rules as legacy
from odooflux.rules.shared.legacy_rules import (
    MigrationReport, apply_python_fixes, check_content)


def _findings(content, from_version, to_version):
    """Run the real Python rule set over *content*; return the Issue list."""
    report = MigrationReport(module_path="", from_version=from_version, to_version=to_version)
    rules = legacy._rules_for_file(Path("models.py"), to_version=to_version)
    check_content(content, "models.py", rules, from_version, report)
    return report.issues


class SizeArgumentTests(unittest.TestCase):
    """TST-001-011 (F-PY-2): size= removal is comma-aware."""

    def test_size_first_arg(self):
        out = apply_python_fixes("name = fields.Char(size=64, string='X')\n", 14, 19)
        self.assertEqual(out, "name = fields.Char(string='X')\n")

    def test_size_last_arg(self):
        out = apply_python_fixes("name = fields.Char(string='X', size=64)\n", 14, 19)
        self.assertEqual(out, "name = fields.Char(string='X')\n")

    def test_size_continuation_line(self):
        src = "code = fields.Char(\n    string='Code',\n    size=\n    32,\n)\n"
        out = apply_python_fixes(src, 14, 19)
        ast.parse(out)  # output compiles
        self.assertNotIn("size", out)
        self.assertIn("string='Code'", out)


class DecoratorRemovalTests(unittest.TestCase):
    """TST-001-012 (F-PY-1): whole decorator lines are removed; indentation and comments survive."""

    SRC = (
        "class A(models.Model):\n"
        "    _name = 'a'\n"
        "\n"
        "    @api.multi\n"
        "    # keep this comment\n"
        "    def f(self):\n"
        "        return 1\n"
        "\n"
        "    @api.returns(\n"
        "        'self',\n"
        "    )\n"
        "    def g(self):\n"
        "        return self.search([])\n"
    )

    def test_decorator_removal_keeps_indentation(self):
        out = apply_python_fixes(self.SRC, 14, 19)
        ast.parse(out)
        self.assertNotIn("@api.multi", out)
        self.assertNotIn("@api.returns", out)
        self.assertIn("    # keep this comment\n    def f(self):\n", out)
        self.assertIn("\n    def g(self):\n", out)


class ApiDecoratorVersionTests(unittest.TestCase):
    """TST-001-020/021/022 (EV-101, EV-102, F-PY-3, F-PY-4)."""

    def test_api_returns_target18_kept_review(self):
        src = "    @api.returns('self')\n    def g(self):\n        pass\n"
        self.assertIn("@api.returns('self')", apply_python_fixes(src, 14, 18))
        review = [i for i in _findings(src, 14, 18) if i.category.startswith("Returns")]
        self.assertTrue(review)
        self.assertEqual(review[0].status, "NEEDS_REVIEW")
        self.assertIn("EV-102", review[0].message)

    def test_api_returns_target19_removed_review(self):
        src = "    @api.returns('self')\n    def g(self):\n        pass\n"
        self.assertNotIn("@api.returns", apply_python_fixes(src, 14, 19))
        review = [i for i in _findings(src, 14, 19) if i.category.startswith("Returns")]
        self.assertTrue(review, "a review finding about return values must remain for v19")
        self.assertEqual(review[0].status, "NEEDS_REVIEW")

    def test_api_one_detect_only(self):
        """@api.one is never removed; it is a NEEDS_REVIEW finding citing EV-101 (13.0)."""
        src = "    @api.one\n    def f(self):\n        pass\n"
        self.assertIn("@api.one", apply_python_fixes(src, 14, 19))
        found = [i for i in _findings(src, 14, 19) if "@api.one" in i.message]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].status, "NEEDS_REVIEW")
        self.assertIn("EV-101", found[0].message)
        self.assertIn("13.0", found[0].message)


class SudoTests(unittest.TestCase):
    """TST-001-023 (EV-103, F-PY-5)."""

    def test_sudo_bool_unchanged(self):
        for src in ("x = self.sudo(False).search([])\n",
                    "x = self.sudo(True).search([])\n",
                    "x = self.sudo(flag=False).search([])\n"):
            self.assertEqual(apply_python_fixes(src, 12, 19), src)
            self.assertEqual(apply_python_fixes(src, 14, 19), src)

    def test_sudo_user_rewritten_only_from_12(self):
        src = "x = self.sudo(user).search([])\n"
        self.assertEqual(apply_python_fixes(src, 12, 19),
                         "x = self.with_user(user).sudo().search([])\n")
        self.assertEqual(apply_python_fixes(src, 14, 19), src)


class NoJsInPythonTests(unittest.TestCase):
    """TST-001-015 (F-PY-6): the Python fixer never injects JavaScript text."""

    def test_no_js_comment_in_python(self):
        src = "res = ajax.jsonRpc('/a', 'call', {})\n"
        out = apply_python_fixes(src, 14, 19)
        self.assertNotIn("/*", out)
        self.assertNotIn("TODO", out)


class VersionMessageTests(unittest.TestCase):
    """TST-001-027 (EV-110, FR-013): rule messages state correct versions."""

    def test_warning_message_versions(self):
        warn_rules = [r for r in legacy.PYTHON_RULES if "Warning" in r[4]]
        self.assertTrue(warn_rules)
        for rule in warn_rules:
            self.assertIn("17.0", rule[5], rule[4])
            self.assertIn("14.0", rule[5], rule[4])
            self.assertIn("EV-110", rule[5], rule[4])

    def test_api_one_message_states_13(self):
        msgs = [r[5] for r in legacy.PYTHON_RULES if "@api.one" in r[5]]
        self.assertTrue(msgs)
        self.assertTrue(any("13.0" in m for m in msgs))


if __name__ == "__main__":
    unittest.main()
