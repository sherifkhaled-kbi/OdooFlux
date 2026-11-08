"""TST-004-004 (contracts/knowledge-cli.md): exit codes 0/1/2 and the sorted output format."""

import unittest

from .helpers import GOLDEN, knowledge_cli


class ValidateCliTests(unittest.TestCase):
    def test_shipped_data_exits_zero_with_summary(self):
        code, out = knowledge_cli(["validate"])
        self.assertEqual(code, 0, out)
        self.assertRegex(out, r"records=\d+ rules=\d+ errors=0 warnings=0")

    def test_invalid_fixture_exits_one_with_sorted_lines(self):
        code, out = knowledge_cli(["validate", "--path", GOLDEN / "invalid" / "E002_url_not_allowlisted"])
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertTrue(any(": E002: url not in allow-list" in l for l in lines))
        self.assertEqual(lines, sorted(lines[:-1]) + [lines[-1]])  # findings sorted, summary last
        self.assertRegex(lines[-1], r"^records=\d+ rules=\d+ errors=\d+ warnings=\d+$")

    def test_warnings_alone_do_not_fail(self):
        code, out = knowledge_cli(["validate", "--path", GOLDEN / "invalid" / "W001_maturity_capped"])
        self.assertEqual(code, 0)
        self.assertIn("W001", out)

    def test_usage_error_exits_two(self):
        code, _ = knowledge_cli(["validate", "--nonsense"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
