"""TST-003-022 (REQ-REP-001): a model built from a run validates against report.schema.json."""

import copy
import unittest

from odooflux.reporting.model.model import build_report
from odooflux.reporting.model.schema_check import validate_report

from ._setup import SRC  # noqa: F401


def _state():
    issue = {"file": "/m/models/a.py", "line": 3, "severity": "WARNING", "category": "Deprecated Attribute",
             "message": "m", "suggestion": "s", "auto_fixable": True, "fix_applied": False,
             "evidence": ["EV-110"], "rejection_reason": ""}
    return {
        "schema": "odooflux.runstate/1", "run_id": "r1", "mode": "analyze", "status": "COMPLETED",
        "options": {"backup": True, "fail_on": "critical"},
        "plan": {"source": "14.0", "target": "19.0", "steps": ["14.0->15.0"], "status": "READY",
                 "reasons": [], "cycles": [], "allow_unverified": False},
        "modules": [{"name": "m", "path": "/m", "status": "DONE", "layer1": "PASS", "rejections": [],
                     "promoted_files": [], "edits": [],
                     "report": {"module_path": "/m", "from_version": 14, "to_version": 19,
                                "issues": [issue], "fixes_applied": 0, "elapsed_seconds": 0.0,
                                "timestamp": "t", "reversible": True, "blocked": False, "block_reason": "",
                                "actions": [], "planned_files": [], "written_files": []}}],
        "ai_done": False,
    }


class ReportModelTests(unittest.TestCase):
    def _report(self):
        from odooflux.core.orchestrator.run import reports_from_state
        state = _state()
        return build_report(state, reports_from_state(state), run_log_path="/x/log")

    def test_valid_report_passes_schema(self):
        self.assertEqual(validate_report(self._report()), [])

    def test_required_sections_present(self):
        report = self._report()
        for key in ("schema_version", "run", "modules", "verification_scope", "recovery"):
            self.assertIn(key, report)
        self.assertEqual(report["verification_scope"]["layers_unavailable"], [4, 5])

    def test_status_enum_is_enforced(self):
        bad = copy.deepcopy(self._report())
        bad["modules"][0]["status"] = "MAYBE"
        self.assertTrue(validate_report(bad))
        bad2 = copy.deepcopy(self._report())
        bad2["modules"][0]["findings"][0]["status"] = "DONE"
        self.assertTrue(validate_report(bad2))

    def test_result_statuses_are_the_six_defined_values(self):
        report = self._report()
        self.assertIn(report["modules"][0]["status"],
                      {"VERIFIED_SUCCESS", "INSTALL_VERIFIED", "STATIC_VALIDATED", "NEEDS_REVIEW", "FAILED", "BLOCKED"})


if __name__ == "__main__":
    unittest.main()
