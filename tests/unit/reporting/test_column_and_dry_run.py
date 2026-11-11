"""PA-5 (column numbers), PA-6 (dry runs are not reversible and claim no rollback) and the PA-3 cleanups (truthful
rejection wording in the terminal; the patch export keeps the accepted edits of a partial module).

A column is reported only when the source gives one: the legacy scanner records the 1-based start of its regex match.
Knowledge findings, experimental refusals and file-level findings carry no column, so they report UNKNOWN."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from . import fixtures

def _report(modules, mode="dry_run", **kwargs):
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.model.model import build_report
    st = fixtures.state(modules, mode=mode)
    return build_report(st, reports_from_state(st), run_log_path="", **kwargs)


def _findings(report):
    return [f for m in report["modules"] for f in m["findings"]]


def _text(report) -> str:
    from odooflux.reporting.terminal.ansi import render_terminal
    return " ".join(render_terminal(report).split())  # wrapping-independent


class ColumnCaptureTests(unittest.TestCase):
    def _scan(self, content, filepath, from_version, rules):
        from odooflux.rules.shared.legacy_rules import MigrationReport, check_content
        report = MigrationReport(module_path="/w/m", from_version=from_version, to_version=18)
        check_content(content, filepath, rules, from_version, report)
        return report.issues

    def test_legacy_finding_carries_the_one_based_column_of_its_match(self):
        from odooflux.rules.shared.legacy_rules import _compile_rules
        rules = _compile_rules([(0, 0, r"\.attrs\b", "WARNING", "Legacy Attrs", "m", "s", False)])
        (issue,) = self._scan("x = 1\n    y = a.attrs\n", "/w/m/models/a.py", 17, rules)
        self.assertEqual((issue.line, issue.column), (2, 10))  # the '.' is at 0-based index 9

    def test_file_level_finding_has_no_column(self):
        (issue,) = self._scan("{'name': 'x', 'version': '16.0.1.0.0'}\n", "/w/m/__manifest__.py", 16, [])
        self.assertEqual(issue.category, "License Missing")
        self.assertEqual(issue.column, 0)

    def test_known_column_reaches_every_location_field(self):
        report = _report([fixtures.module("kbi_c", [
            fixtures.issue("models/a.py", 2, "WARNING", "17-18.py.attrs", "attr", auto_fixable=False, column=10)])])
        (f,) = _findings(report)
        self.assertEqual(f["column"], 10)
        self.assertEqual(f["location"], {"path": "models/a.py", "line": 2, "column": 10})
        self.assertEqual(f["line"], 2)  # the top-level line stays an integer
        self.assertIn("L2:10", _text(report))

    def test_unknown_column_is_the_literal_unknown_never_a_number(self):
        report = _report([fixtures.module("kbi_u", [
            fixtures.issue("models/a.py", 42, "WARNING", "17-18.py.field", "field", auto_fixable=False),
            fixtures.issue("__manifest__.py", 0, "WARNING", "Version Mismatch", "version", auto_fixable=False)])])
        by_rule = {f["rule_id"]: f for f in _findings(report)}
        self.assertEqual(by_rule["17-18.py.field"]["location"],
                         {"path": "models/a.py", "line": 42, "column": "UNKNOWN"})
        self.assertEqual(by_rule["Version Mismatch"]["location"]["column"], "UNKNOWN")
        self.assertEqual(by_rule["Version Mismatch"]["column"], 0)  # existing integer key: 0 = not known
        self.assertIn("L42:UNKNOWN", _text(report))

    def test_column_is_never_reported_without_a_line(self):
        report = _report([fixtures.module("kbi_l", [
            fixtures.issue("__manifest__.py", 0, "WARNING", "Version Mismatch", "version", auto_fixable=False,
                           column=3)])])
        (f,) = _findings(report)
        self.assertEqual(f["location"]["line"], "UNKNOWN")
        self.assertEqual(f["location"]["column"], "UNKNOWN")

    def test_schema_accepts_integer_and_unknown_columns(self):
        from odooflux.reporting.model.schema_check import validate_report
        report = _report([fixtures.module("kbi_s", [
            fixtures.issue("models/a.py", 2, "WARNING", "17-18.py.a", "a", auto_fixable=False, column=10),
            fixtures.issue("models/a.py", 3, "WARNING", "17-18.py.b", "b", auto_fixable=False)])])
        self.assertEqual(validate_report(report), [])
        self.assertEqual(sorted(str(f["location"]["column"]) for f in _findings(report)), ["10", "UNKNOWN"])

    def test_sarif_region_has_start_column_only_when_known(self):
        from odooflux.reporting.exporters.sarif import export_sarif
        report = _report([fixtures.module("kbi_sa", [
            fixtures.issue("models/a.py", 2, "WARNING", "17-18.py.a", "a", auto_fixable=False, column=10),
            fixtures.issue("models/a.py", 3, "WARNING", "17-18.py.b", "b", auto_fixable=False)])])
        results = {r["ruleId"]: r for r in json.loads(export_sarif(report))["runs"][0]["results"]}
        self.assertEqual(results["17-18.py.a"]["locations"][0]["physicalLocation"]["region"],
                         {"startLine": 2, "startColumn": 10})
        self.assertEqual(results["17-18.py.b"]["locations"][0]["physicalLocation"]["region"], {"startLine": 3})

    def test_legacy_writers_report_the_column_and_unknown_as_unknown(self):
        from odooflux.reporting.model.legacy_json import save_json_report
        from odooflux.reporting.model.model import legacy_unresolved
        from odooflux.rules.shared.legacy_rules import Issue, MigrationReport
        report = MigrationReport(module_path="/w/kbi_l", from_version=17, to_version=18, issues=[
            Issue(file="/w/kbi_l/models/a.py", line=2, severity="WARNING", category="17-18.py.a", message="a",
                  suggestion="fix it", auto_fixable=False, column=10),
            Issue(file="/w/kbi_l/__manifest__.py", line=1, severity="WARNING", category="License Missing",
                  message="no license", suggestion="add one", auto_fixable=False)])
        locations = [f["location"] for f in legacy_unresolved(report, None, "fix")]
        self.assertEqual([loc["column"] for loc in locations], [10, "UNKNOWN"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.json"
            save_json_report(report, out, mode="fix")
            issues = json.loads(out.read_text(encoding="utf-8"))["issues"]
        self.assertEqual([i["column"] for i in issues], [10, 0])
        self.assertEqual(issues[1]["location"]["column"], "UNKNOWN")

    def test_legacy_console_shows_line_and_column(self):
        from odooflux.reporting.model.legacy_terminal import print_report
        from odooflux.rules.shared.legacy_rules import Issue, MigrationReport
        report = MigrationReport(module_path="/w/kbi_l", from_version=17, to_version=18, issues=[
            Issue(file="/w/kbi_l/models/a.py", line=2, severity="WARNING", category="17-18.py.a", message="a",
                  suggestion="fix it", auto_fixable=False, column=10),
            Issue(file="/w/kbi_l/models/a.py", line=5, severity="WARNING", category="17-18.py.b", message="b",
                  suggestion="fix it", auto_fixable=False)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_report(report, no_color=True)
        text = out.getvalue()
        self.assertIn("L2:10", text)
        self.assertIn("L5:UNKNOWN", text)


class DryRunReversibleTests(unittest.TestCase):
    def _module(self, reversible):
        m = fixtures.module("kbi_d", [fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr",
                                                     auto_fixable=True)])
        m["report"]["reversible"] = reversible
        return m

    def test_dry_run_module_is_not_reversible(self):
        report = _report([self._module(True)], mode="dry_run")
        self.assertIs(report["modules"][0]["reversible"], False)

    def test_analyze_module_is_not_reversible(self):
        report = _report([self._module(True)], mode="analyze")
        self.assertIs(report["modules"][0]["reversible"], False)

    def test_fix_run_keeps_its_reversible_value(self):
        self.assertIs(_report([self._module(True)], mode="fix")["modules"][0]["reversible"], True)
        self.assertIs(_report([self._module(False)], mode="fix")["modules"][0]["reversible"], False)  # --no-backup

    def test_dry_run_claims_no_rollback_and_no_applied_edit(self):
        report = _report([self._module(True)], mode="dry_run")
        self.assertIsNone(report["recovery"]["rollback_cmd"])
        self.assertFalse(report["recovery"]["reversible"])
        self.assertEqual(report["summary"]["edits"]["applied"], 0)
        text = _text(report)
        self.assertIn("Roll back: not needed, nothing was written", text)
        self.assertNotIn("odooflux rollback", text)
        self.assertNotIn("NOT reversible", text)  # a dry run is not 'non-reversible' either: nothing to undo

    def test_legacy_json_module_and_html_make_no_rollback_claim_in_dry_run(self):
        from odooflux.reporting.exporters.legacy_json import export_legacy_json
        from odooflux.reporting.html.html import render_html
        report = _report([self._module(True)], mode="dry_run")
        legacy = json.loads(export_legacy_json(report))
        self.assertIs(legacy["summary"]["reversible"], False)
        self.assertNotIn("odooflux rollback", json.dumps(legacy))
        html = render_html(report)
        self.assertNotIn("odooflux rollback", html)
        self.assertIn("nothing was written", html)

    def test_legacy_writer_module_is_not_reversible_in_dry_run(self):
        from odooflux.reporting.model.legacy_json import save_json_report
        from odooflux.rules.shared.legacy_rules import MigrationReport
        report = MigrationReport(module_path="/w/kbi_d", from_version=17, to_version=18, reversible=True)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r.json"
            save_json_report(report, out, mode="dry_run")
            self.assertIs(json.loads(out.read_text(encoding="utf-8"))["summary"]["reversible"], False)


class RejectionWordingTests(unittest.TestCase):
    REASON = "validation_failed:L1-python (IndentationError line 119)"

    def _partial(self, mode):
        return fixtures.module(
            "kbi_part", [fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr", auto_fixable=True),
                         fixtures.issue("models/b.py", 7, "WARNING", "17-18.py.field", "field", auto_fixable=False,
                                        rejection_reason=self.REASON)],
            status="PARTIAL", layer1="FAIL", rejections=[self.REASON],
            edits=[{"path": "/work/kbi_part/models/a.py", "dest": "/work/kbi_part/models/a.py",
                    "spans": [{"start": 0, "end": 1, "before": "x", "after": "y"}]},
                   # b.py: its whole-file change was refused, but its valid stage was kept (salvage)
                   {"path": "/work/kbi_part/models/b.py", "dest": "/work/kbi_part/models/b.py",
                    "spans": [{"start": 0, "end": 1, "before": "x", "after": "y"}]}],
            refused_files={"/work/kbi_part/models/b.py": self.REASON},
            promoted=["/work/kbi_part/models/a.py", "/work/kbi_part/models/b.py"])

    def test_salvaged_file_is_not_called_unchanged(self):
        text = _text(_report([self._partial("fix")], mode="fix"))
        self.assertIn(f"models/b.py: reason: {self.REASON} - refused change not applied; "
                      "valid changes to this file are kept", text)
        self.assertNotIn("models/b.py: reason: " + self.REASON + " - edit refused; original kept", text)
        self.assertNotIn("file left unchanged", text)

    def test_unchanged_refused_file_says_original_kept(self):
        module = fixtures.module(
            "kbi_full", [fixtures.issue("models/b.py", 7, "WARNING", "17-18.py.field", "field", auto_fixable=False,
                                        rejection_reason=self.REASON)],
            status="FAILED", layer1="FAIL", rejections=[self.REASON],
            refused_files={"/work/kbi_full/models/b.py": self.REASON})
        text = _text(_report([module], mode="fix"))
        self.assertIn(f"models/b.py: reason: {self.REASON} - edit refused; original kept", text)
        self.assertNotIn("file left unchanged", text)

    def test_module_record_names_each_refused_file_with_its_kept_state(self):
        (m,) = _report([self._partial("fix")], mode="fix")["modules"]
        self.assertEqual(m["refused_files"], [{"path": "models/b.py", "reason": self.REASON, "changes_kept": True}])
        unchanged = fixtures.module(
            "kbi_full", [], status="FAILED", layer1="FAIL", rejections=[self.REASON],
            refused_files={"/work/kbi_full/models/b.py": self.REASON})
        (full,) = _report([unchanged], mode="fix")["modules"]
        self.assertEqual(full["refused_files"][0]["changes_kept"], False)


class PartialPatchExportTests(unittest.TestCase):
    REASON = "validation_failed:L1-python (IndentationError line 119)"

    def test_partial_module_exports_its_accepted_edit_and_no_refused_file(self):
        from odooflux.reporting.exporters.diff import export_diff
        old = {"a": "x = 1\nfoo = 2\n", "b": "y = 1\nbar = 2\n"}
        root = "/work/kbi_p"

        def reader(module, path):
            return old[Path(path).name.split(".")[0]].encode("utf-8")

        report = {"modules": [{
            "name": "kbi_p", "path": root, "blocked": False, "block_reason": "",
            "rejections": [self.REASON], "findings": [],
            "refused_files": [{"path": "models/b.py", "reason": self.REASON, "changes_kept": False}],
            "edits": [{"path": f"{root}/models/a.py", "dest": f"{root}/models/a.py",
                       "spans": [{"start": 6, "end": 9, "before": "foo", "after": "bar"}]}],
        }]}
        export = export_diff(report, reader)
        self.assertIn("a/kbi_p/models/a.py", export.patch)
        self.assertIn("+bar = 2", export.patch)
        self.assertNotIn("models/b.py", export.patch)
        self.assertEqual([f["path"] for f in export.index["files"]], ["kbi_p/models/a.py"])
        self.assertEqual(export.index["excluded_modules"], [])

    def test_blocked_module_is_still_excluded_whole(self):
        from odooflux.reporting.exporters.diff import export_diff
        root = "/work/kbi_q"
        report = {"modules": [{
            "name": "kbi_q", "path": root, "blocked": True, "block_reason": "backup failed",
            "rejections": [], "findings": [],
            "edits": [{"path": f"{root}/models/a.py", "dest": f"{root}/models/a.py",
                       "spans": [{"start": 0, "end": 1, "before": "x", "after": "y"}]}],
        }]}
        export = export_diff(report, lambda module, path: b"x = 1\n")
        self.assertEqual(export.patch, "")
        self.assertEqual(export.index["excluded_modules"], [{"module": "kbi_q", "reasons": ["backup failed"]}])
