"""TST-007-005 (REQ-AI-002, FR-003, FR-013): deterministic-fixable and ineligible findings are never escalated."""

import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.ai.escalation import FindingRef, RuleMeta, select_eligible

EV = ({"id": "EV-1", "excerpt": "claim"},)


def f(rule, line=1):
    return FindingRef(id=f"{rule}:{line}", rule_id=rule, path="a.py", line=line, message="m")


class EligibilityTests(unittest.TestCase):
    def test_only_eligible_without_fix_and_with_evidence(self):
        metas = {
            "ok": RuleMeta("ok", ai_eligible=True, has_fix=False, evidence=EV),
            "fixable": RuleMeta("fixable", ai_eligible=True, has_fix=True, evidence=EV),
            "off": RuleMeta("off", ai_eligible=False, has_fix=False, evidence=EV),
            "noev": RuleMeta("noev", ai_eligible=True, has_fix=False, evidence=()),
        }
        findings = [f("ok"), f("fixable"), f("off"), f("noev"), f("unknown")]
        eligible, skipped = select_eligible(findings, metas)
        self.assertEqual([x.rule_id for x in eligible], ["ok"])
        reasons = {s.finding.rule_id: s.reason for s in skipped}
        self.assertEqual(reasons, {"fixable": "deterministic_fix_available", "off": "not_ai_eligible",
                                   "noev": "no_evidence", "unknown": "no_rule_metadata"})

    def test_already_fixed_findings_are_not_escalated(self):
        metas = {"ok": RuleMeta("ok", ai_eligible=True, has_fix=False, evidence=EV)}
        fixed = FindingRef(id="x", rule_id="ok", path="a.py", line=1, message="m", status="FIXED")
        eligible, skipped = select_eligible([fixed], metas)
        self.assertEqual(eligible, [])
        self.assertEqual(skipped[0].reason, "already_fixed")

    def test_zero_requests_for_no_eligible_findings(self):
        eligible, _ = select_eligible([f("off")], {"off": RuleMeta("off", False, False, EV)})
        self.assertEqual(eligible, [])


if __name__ == "__main__":
    unittest.main()
