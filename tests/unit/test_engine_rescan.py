"""TST-003-017 (REQ-TRF-005, FR-016): fixed only when absent after re-scan; moved matches stay open."""

import unittest

from odooflux.core.contracts.records import Finding
from odooflux.core.engine.rescan import resolved_by_rescan, status_by_rescan

from ._setup import SRC  # noqa: F401


def f(rule, line, path="m.py"):
    return Finding(rule_id=rule, path=path, line=line, severity="WARNING", message="m")


class RescanTests(unittest.TestCase):
    def test_absent_after_rescan_is_fixed(self):
        before = [f("R1", 3), f("R2", 9)]
        after = [f("R2", 9)]
        statuses = status_by_rescan(before, after)
        self.assertEqual(statuses[before[0].id], "FIXED")
        self.assertEqual(statuses[before[1].id], "OPEN")

    def test_moved_finding_is_matched_by_rule_and_stays_open(self):
        before = [f("R1", 10)]
        after = [f("R1", 12)]  # an edit above added two lines
        self.assertEqual(status_by_rescan(before, after)[before[0].id], "OPEN")

    def test_nearest_line_accounts_for_one_finding_each(self):
        before = [f("R1", 5), f("R1", 50)]
        after = [f("R1", 51)]
        fixed = resolved_by_rescan(before, after, key=lambda x: x.rule_id)
        self.assertEqual([x.line for x in fixed], [5])


if __name__ == "__main__":
    unittest.main()
