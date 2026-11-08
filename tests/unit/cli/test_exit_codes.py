"""TST-009-007 (REQ-REP-005, F-VER-4, F-REP-3): every row of the exit-code table, every --fail-on value, every
precedence combination (4 > 3 > 1 > 0)."""

import copy
import itertools
import unittest

from tests.unit.reporting import _setup  # noqa: F401  (puts src/ first)
from tests.unit.reporting.helpers import golden

SEVERITIES = ("CRITICAL", "WARNING", "INFO")


def model(*, findings=(), statuses=("STATIC_VALIDATED",), rejected=0):
    """Minimal report model: one module per status; findings are (severity, status) on the first module."""
    base = copy.deepcopy(golden("static_validated"))
    template = base["modules"][0]
    modules = []
    for i, status in enumerate(statuses):
        m = copy.deepcopy(template)
        m.update(name=f"m{i}", status=status, findings=[], rejections=[])
        modules.append(m)
    for n, (severity, status) in enumerate(findings):
        modules[0]["findings"].append({"id": f"f{n}", "rule_id": "r", "path": "a.py", "line": 1, "column": 0,
                                       "severity": severity, "message": "m", "suggestion": "", "evidence": [],
                                       "status": status})
    base["modules"] = modules
    base["summary"]["edits"] = {"applied": 0, "rejected": rejected}
    return base


def code(report, fail_on="critical", fail_on_status=None, write_mode=False):
    from odooflux.cli.exit_codes import ExitPolicy, exit_code
    return exit_code(report, ExitPolicy(fail_on=fail_on, fail_on_status=fail_on_status), write_mode=write_mode)


class ExitTableTests(unittest.TestCase):
    def test_constants(self):
        from odooflux.cli import exit_codes as e
        self.assertEqual((e.OK, e.THRESHOLD, e.USAGE, e.REJECTED, e.BLOCKED), (0, 1, 2, 3, 4))

    def test_row_0_clean(self):
        self.assertEqual(code(model()), 0)
        self.assertEqual(code(model(), fail_on="info"), 0)

    def test_row_1_threshold_matrix(self):
        """Open finding of each severity against each --fail-on value."""
        expect = {  # (fail_on, severity) -> code
            ("none", "CRITICAL"): 0, ("none", "WARNING"): 0, ("none", "INFO"): 0,
            ("critical", "CRITICAL"): 1, ("critical", "WARNING"): 0, ("critical", "INFO"): 0,
            ("warning", "CRITICAL"): 1, ("warning", "WARNING"): 1, ("warning", "INFO"): 0,
            ("info", "CRITICAL"): 1, ("info", "WARNING"): 1, ("info", "INFO"): 1,
        }
        for (fail_on, severity), want in expect.items():
            for status in ("OPEN", "NEEDS_REVIEW"):
                self.assertEqual(code(model(findings=[(severity, status)]), fail_on=fail_on), want,
                                 (fail_on, severity, status))

    def test_f_ver_4_info_never_fails_by_default(self):
        self.assertEqual(code(model(findings=[("INFO", "OPEN")] * 50)), 0)
        self.assertEqual(code(model(findings=[("INFO", "OPEN")] * 50), fail_on="warning"), 0)

    def test_fixed_and_rejected_findings_are_not_open(self):
        self.assertEqual(code(model(findings=[("CRITICAL", "FIXED"), ("CRITICAL", "REJECTED")]), fail_on="info"), 0)

    def test_failed_module_status_default_and_none(self):
        failed = model(statuses=("FAILED",))
        self.assertEqual(code(failed), 1)                      # default fail_on critical includes FAILED
        self.assertEqual(code(failed, fail_on="warning"), 1)
        self.assertEqual(code(failed, fail_on="none"), 0)      # none disables code 1
        self.assertEqual(code(failed, fail_on="none", fail_on_status=("FAILED",)), 1)  # explicit wins
        self.assertEqual(code(failed, fail_on_status=()), 0)   # explicit empty disables status rule

    def test_needs_review_only_when_asked(self):
        nr = model(statuses=("NEEDS_REVIEW",))
        self.assertEqual(code(nr), 0)
        self.assertEqual(code(nr, fail_on_status=("FAILED", "NEEDS_REVIEW")), 1)

    def test_row_3_rejected_edits_only_in_write_mode(self):
        self.assertEqual(code(model(rejected=2), write_mode=True), 3)
        self.assertEqual(code(model(rejected=2), write_mode=False), 0)
        self.assertEqual(code(model(rejected=0), write_mode=True), 0)

    def test_row_4_blocked_regardless_of_fail_on(self):
        for fail_on in ("none", "critical", "warning", "info"):
            self.assertEqual(code(model(statuses=("BLOCKED",)), fail_on=fail_on), 4, fail_on)

    def test_precedence_4_over_3_over_1_over_0(self):
        blocked_rejected_critical = model(statuses=("BLOCKED", "FAILED"), rejected=1,
                                          findings=[("CRITICAL", "OPEN")])
        self.assertEqual(code(blocked_rejected_critical, write_mode=True), 4)
        rejected_critical = model(rejected=1, findings=[("CRITICAL", "OPEN")])
        self.assertEqual(code(rejected_critical, write_mode=True), 3)
        self.assertEqual(code(rejected_critical, write_mode=False), 1)
        self.assertEqual(code(model(findings=[("CRITICAL", "OPEN")])), 1)

    def test_exhaustive_combination_table(self):
        statuses = ("STATIC_VALIDATED", "NEEDS_REVIEW", "FAILED", "BLOCKED")
        for status, fail_on, sev, rej, write in itertools.product(
                statuses, ("none", "critical", "warning", "info"), (None,) + SEVERITIES, (0, 1), (False, True)):
            findings = [(sev, "OPEN")] if sev else []
            got = code(model(statuses=(status,), findings=findings, rejected=rej), fail_on=fail_on, write_mode=write)
            rank = {"CRITICAL": 3, "WARNING": 2, "INFO": 1}
            threshold = {"none": 99, "critical": 3, "warning": 2, "info": 1}[fail_on]
            if status == "BLOCKED":
                want = 4
            elif write and rej:
                want = 3
            elif (sev and rank[sev] >= threshold) or (status == "FAILED" and fail_on != "none"):
                want = 1
            else:
                want = 0
            self.assertEqual(got, want, (status, fail_on, sev, rej, write))

    def test_row_2_usage_errors(self):
        from odooflux.cli.exit_codes import ExitPolicy, UsageError, parse_fail_on_status
        with self.assertRaises(UsageError):
            ExitPolicy(fail_on="bogus")
        with self.assertRaises(UsageError):
            parse_fail_on_status("FAILED,BROKEN")
        self.assertEqual(parse_fail_on_status("FAILED,NEEDS_REVIEW"), ("FAILED", "NEEDS_REVIEW"))
        self.assertEqual(parse_fail_on_status("none"), ())
        self.assertIsNone(parse_fail_on_status(None))

    def test_tool_error_maps_to_4(self):
        from odooflux.cli.exit_codes import code_for_exception, BLOCKED
        self.assertEqual(code_for_exception(RuntimeError("x")), BLOCKED)

    def test_unavailable_l3_is_blocked_not_success(self):
        self.assertEqual(code(golden("blocked")), 4)
        self.assertEqual(code(golden("mixed"), write_mode=True), 4)


class CliWiringTests(unittest.TestCase):
    def test_fail_on_status_option_accepted(self):
        from odooflux.cli.main import build_parser
        args = build_parser().parse_args(["migrate", "--from-version", "16", "--fail-on-status", "FAILED,NEEDS_REVIEW"])
        self.assertEqual(args.fail_on_status, "FAILED,NEEDS_REVIEW")
        args = build_parser().parse_args(["migrate", "--from-version", "16"])
        self.assertIsNone(args.fail_on_status)


if __name__ == "__main__":
    unittest.main()
