"""AF-9 (AD-06, Acceptance Criterion 16): every unresolved issue carries its relative path, exact line (or UNKNOWN),
rule id, description, the reason it was not fixed and the developer action, in every report format.

Unresolved means OPEN, NEEDS_REVIEW or REJECTED. A FIXED finding carries none of the new fields."""

import json
import re
import unittest

from ._setup import SRC  # noqa: F401
from . import fixtures
from .helpers import build

UNRESOLVED = ("OPEN", "NEEDS_REVIEW", "REJECTED")
NO_FIXER_DETECT = "no automatic fixer for this rule (DETECT_ONLY)"


def _report(modules, mode="dry_run", **kwargs):
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.model.model import build_report
    st = fixtures.state(modules, mode=mode)
    return build_report(st, reports_from_state(st), run_log_path="", **kwargs)


def _findings(report, module=None):
    return [f for m in report["modules"] if module is None or m["name"] == module for f in m["findings"]]


def _unresolved(report):
    return [f for f in _findings(report) if f["status"] in UNRESOLVED]


class UnresolvedModelTests(unittest.TestCase):
    def test_relative_path_and_exact_line(self):
        report = _report([fixtures.module("kbi_hr", [
            fixtures.issue("views/hr.xml", 42, "WARNING", "17-18.xml.attrs-removed", "attrs not convertible",
                           auto_fixable=False)])])
        (f,) = _findings(report)
        self.assertEqual(f["path"], "views/hr.xml")
        self.assertEqual(f["location"], {"path": "views/hr.xml", "line": 42, "column": "UNKNOWN"})
        self.assertEqual(f["line"], 42)
        self.assertEqual(f["rule_id"], "17-18.xml.attrs-removed")
        self.assertEqual(f["status"], "NEEDS_REVIEW")
        self.assertEqual(f["reason_not_fixed"], "no automatic fixer for this finding")
        self.assertEqual(f["developer_action"], "Apply the documented replacement")

    def test_line_zero_is_unknown_and_never_invented(self):
        report = _report([fixtures.module("kbi_ver", [
            fixtures.issue("__manifest__.py", 0, "WARNING", "Version Mismatch", "manifest declares 16.x",
                           auto_fixable=False, suggestion="Confirm the source version")])])
        (f,) = _findings(report)
        self.assertEqual(f["location"]["line"], "UNKNOWN")
        self.assertEqual(f["line"], 0)  # the stored integer is kept for existing consumers; location is the contract
        self.assertEqual(f["developer_action"], "Confirm the source version")

    def test_fixed_finding_carries_no_unresolved_fields(self):
        report = _report([fixtures.module("kbi_ok", [
            fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "changed", fix_applied=True)], fixes=1)])
        (f,) = _findings(report)
        self.assertEqual(f["status"], "FIXED")
        for key in ("location", "reason_not_fixed", "developer_action"):
            self.assertNotIn(key, f)

    def test_detect_only_rule_has_no_fixer_reason(self):
        report = _report([fixtures.module("kbi_dm", [
            dict(fixtures.issue("models/a.py", 8, "WARNING", "17-18.py.review", "review me", auto_fixable=False),
                 maturity="DETECT_ONLY")])])
        (f,) = _findings(report)
        self.assertEqual(f["reason_not_fixed"], NO_FIXER_DETECT)

    def test_experimental_refusal_reason_comes_from_its_element_line(self):
        refused_path = "/work/kbi_hr/views/hr.xml"
        report = _report([fixtures.module(
            "kbi_hr", [fixtures.issue("views/hr.xml", 42, "WARNING", "17-18.xml.attrs-removed", "attrs",
                                      auto_fixable=False)],
            experimental=[{"rule_id": "17-18.xml.attrs-removed", "path": refused_path, "converted": [],
                           "refused": [{"line": 42, "element": "attrs", "reason": "domain is not convertible"}]}])])
        (f,) = _findings(report)
        self.assertEqual(f["reason_not_fixed"], "domain is not convertible")
        self.assertEqual(f["location"]["line"], 42)

    def test_validation_failure_reason_for_open_findings_and_the_rejection_itself(self):
        reason = "validation_failed:L1-python (IndentationError line 119)"
        report = _report([dict(fixtures.module(
            "kbi_stock", [
                fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr changed", auto_fixable=True),
                fixtures.issue("models/a.py", 0, "WARNING", "Fix Rejected", "a.py: rejected",
                               auto_fixable=False, rejection_reason=reason,
                               suggestion="Edit this file by hand; its findings stay open"),
            ], status="FAILED", layer1="FAIL", rejections=[reason]),
            refused_files={"/work/kbi_stock/models/a.py": reason})])  # run-state keys are absolute, like the issues'
        by_rule = {f["rule_id"]: f for f in _findings(report)}
        open_finding = by_rule["17-18.py.attrs"]
        self.assertEqual(open_finding["status"], "OPEN")
        # Approved partial-migration policy (PA-3): the refused file's open findings name the refusal; the module's
        # other files are processed and are not described as unwritten.
        self.assertEqual(open_finding["reason_not_fixed"],
                         f"fix rejected by validation ({reason}); the finding stays open")
        rejected = by_rule["Fix Rejected"]
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["reason_not_fixed"], reason)
        self.assertEqual(rejected["location"], {"path": "models/a.py", "line": "UNKNOWN", "column": "UNKNOWN"})
        self.assertEqual(rejected["developer_action"], "Edit this file by hand; its findings stay open")

    def test_run_mode_reasons_for_open_findings(self):
        open_issue = fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr changed")
        dry = _findings(_report([fixtures.module("kbi_a", [open_issue])], mode="dry_run"))[0]
        analyze = _findings(_report([fixtures.module("kbi_a", [open_issue])], mode="analyze"))[0]
        fixed_run = _findings(_report([fixtures.module("kbi_a", [open_issue])], mode="fix"))[0]
        self.assertEqual(dry["reason_not_fixed"], "not applied: a dry run writes no files")
        self.assertEqual(analyze["reason_not_fixed"], "not applied: an analyze run computes no edits")
        self.assertEqual(fixed_run["reason_not_fixed"],
                         "automatic fix not applied: the finding is still present after the fix pass")

    def test_blocked_module_reason(self):
        report = _report([fixtures.module("kbi_b", [
            fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr changed")],
            status="BLOCKED", blocked=True, block_reason="backup failed")], mode="fix")
        (f,) = _findings(report)
        self.assertEqual(f["reason_not_fixed"], "module blocked: backup failed")

    def test_empty_suggestion_gets_the_default_action(self):
        report = _report([fixtures.module("kbi_d", [
            fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.x", "x", auto_fixable=False, suggestion="")])])
        (f,) = _findings(report)
        self.assertEqual(f["developer_action"], "Review this finding and fix it by hand.")

    def test_schema_accepts_the_new_fields(self):
        from odooflux.reporting.model.schema_check import SCHEMA_FILE, validate_report
        from .schema_validator import Validator, load
        report = _report([fixtures.module("kbi_ver", [
            fixtures.issue("__manifest__.py", 0, "WARNING", "Version Mismatch", "m", auto_fixable=False)])])
        self.assertEqual(validate_report(report), [])
        self.assertEqual(Validator(load(SCHEMA_FILE)).errors(report), [])
        report["modules"][0]["findings"][0]["location"]["line"] = 0  # 0 is not a valid line: only UNKNOWN or >= 1
        self.assertTrue(Validator(load(SCHEMA_FILE)).errors(report))


def _terminal_findings(text: str) -> dict:
    """(module/path, location, rule id) -> status for each unresolved finding line of the terminal FINDINGS section."""
    found, heading, in_findings = {}, None, False
    line_re = re.compile(r"^  (\S+)\s+(L\d+(?::(?:\d+|UNKNOWN))?|UNKNOWN)  (.+?)(?: \[(OPEN|NEEDS_REVIEW|REJECTED)\])?$")
    for line in text.splitlines():
        if line.startswith("FINDINGS"):
            in_findings = True
        elif line.startswith(("REJECTED EDITS", "VERIFICATION SCOPE")):
            in_findings = False
        if not in_findings or not line.strip():
            continue
        if not line.startswith(" ") and "/" in line:
            heading = line
            continue
        match = line_re.match(line)
        if match and match.group(4):
            found[(heading, match.group(2), match.group(3))] = match.group(4)
    return found


class UnresolvedAcrossFormatsTests(unittest.TestCase):
    def _assert_same_unresolved(self, model, name):
        from odooflux.reporting.exporters.sarif import export_sarif
        from odooflux.reporting.html.html import esc, render_html
        from odooflux.reporting.options import RendererOptions, sanitize_text
        from odooflux.reporting.terminal.ansi import location_text, render_terminal
        unresolved = [(m, f) for m in model["modules"] for f in m["findings"] if f["status"] in UNRESOLVED]
        html = render_html(model)
        terminal = render_terminal(model, RendererOptions(color="never", width=400, show_fixed=True,
                                                          max_findings_per_file=10000))
        sarif = json.loads(export_sarif(model))["runs"][0]["results"]
        self.assertEqual(sorted(r["partialFingerprints"]["odoofluxFindingId"] for r in sarif),
                         sorted(f["id"] for _, f in unresolved), name)

        expected_terminal = {}
        for module, f in unresolved:
            loc = location_text(f)
            key = (sanitize_text(f"{module['name']}/{f['path']}"), loc, sanitize_text(f["rule_id"]))
            expected_terminal[key] = f["status"]
            reason = sanitize_text(f["reason_not_fixed"])
            action = sanitize_text(f["developer_action"])
            self.assertIn(f"Not fixed: {reason}. Action: {action}", terminal, f"{name}: {f['rule_id']}")
            row = f"<td>{esc(loc)}</td><td><code>{esc(f['rule_id'])}</code></td><td>{esc(f['status'])}</td>"
            self.assertIn(row, html, f"{name}: {f['rule_id']}")
            self.assertIn(esc(f["reason_not_fixed"]), html, name)
            self.assertIn(esc(f["developer_action"]), html, name)
        self.assertEqual(_terminal_findings(terminal), expected_terminal, name)
        return len(unresolved)

    def test_same_unresolved_set_in_json_html_terminal_and_sarif(self):
        for name in fixtures.scenarios():
            self._assert_same_unresolved(build(name), name)

    def test_unknown_lines_are_consistent_across_formats(self):
        report = _report([fixtures.module(
            "kbi_unknown", [
                fixtures.issue("models/a.py", 0, "WARNING", "Fix Rejected", "a.py: rejected", auto_fixable=False,
                               rejection_reason="validation_failed:L1-python (SyntaxError)",
                               suggestion="Edit this file by hand; its findings stay open"),
                fixtures.issue("__manifest__.py", 0, "WARNING", "Version Mismatch", "manifest declares 16.x",
                               auto_fixable=False, suggestion="Confirm the source version"),
                fixtures.issue("models/a.py", 9, "WARNING", "17-18.py.attrs", "attr changed", auto_fixable=True),
            ], status="FAILED", layer1="FAIL", rejections=["validation_failed:L1-python (SyntaxError)"])])
        self.assertEqual(self._assert_same_unresolved(report, "unknown-lines"), 3)
        self.assertEqual(sorted((f["location"]["line"] for f in _unresolved(report)), key=str),
                         sorted([9, "UNKNOWN", "UNKNOWN"], key=str))

    def test_sarif_locations_match_the_model(self):
        from odooflux.reporting.exporters.sarif import export_sarif
        for name in fixtures.scenarios():
            model = build(name)
            results = {r["partialFingerprints"]["odoofluxFindingId"]: r
                       for r in json.loads(export_sarif(model))["runs"][0]["results"]}
            for module in model["modules"]:
                for f in module["findings"]:
                    if f["status"] not in UNRESOLVED:
                        continue
                    physical = results[f["id"]]["locations"][0]["physicalLocation"]
                    if f["location"]["line"] == "UNKNOWN":
                        self.assertNotIn("region", physical, name)
                    else:
                        self.assertEqual(physical["region"]["startLine"], f["location"]["line"], name)
                    self.assertEqual(results[f["id"]]["properties"]["reason_not_fixed"], f["reason_not_fixed"])


if __name__ == "__main__":
    unittest.main()
