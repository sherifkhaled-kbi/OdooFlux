"""TST-003-003 (REQ-ARC-003, FR-003): no Odoo version literal in engine code. Versions come from data."""

import re
import unittest

from ._setup import SRC

LITERAL = re.compile(r"\b1[0-9]\.0\b")
ALLOWED = {"rules/shared/legacy_rules.py"}  # moved P0 tables: their version facts are EV-cited rule text


class NoVersionLiteralTests(unittest.TestCase):
    def test_engine_code_has_no_version_literals(self):
        problems = []
        for file in sorted((SRC / "odooflux").rglob("*.py")):
            rel = file.relative_to(SRC / "odooflux").as_posix()
            if rel in ALLOWED:
                continue
            for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if LITERAL.search(line):
                    problems.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual(problems, [])

    def test_pattern_detects_a_literal(self):
        self.assertTrue(LITERAL.search("if major == 14.0:"))
        self.assertFalse(LITERAL.search("version = 'M.0'"))


if __name__ == "__main__":
    unittest.main()
