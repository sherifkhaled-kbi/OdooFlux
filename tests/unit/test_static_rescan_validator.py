"""TST-003-019 (REQ-VAL-002): L2 re-scan attaches post-fix findings per file."""

import unittest

from odooflux.core.contracts.records import Finding
from odooflux.validation.static.rescan import RescanValidator, attach_post_fix

from ._setup import SRC  # noqa: F401


class StaticRescanTests(unittest.TestCase):
    def test_l2_reports_pass_and_attaches_post_fix_findings(self):
        validator = RescanValidator()
        self.assertEqual(validator.layer, 2)
        self.assertEqual(validator.validate("m.py", "x = 1\n").outcome, "PASS")
        post = [Finding(rule_id="B", path="m.py", line=9, severity="WARNING", message="m"),
                Finding(rule_id="A", path="m.py", line=2, severity="CRITICAL", message="m")]
        record = attach_post_fix("m.py", post)
        self.assertEqual([f.rule_id for f in record["findings"]], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
