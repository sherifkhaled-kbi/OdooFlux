"""AF-9b (AD-06, Acceptance Criterion 16): the legacy outputs name, for every unresolved issue, its relative path, its
exact line (or UNKNOWN), its rule id, its description, the reason it was not fixed and the developer action. The legacy
console and the legacy JSON writers (fed the MigrationReport) and the model-fed legacy exporter must agree. A FIXED
issue carries none of these fields."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from . import fixtures

REFUSED = "domain is not convertible"
NO_FIXER = "no automatic fixer for this finding"
DRY_RUN = "not applied: a dry run writes no files"
FIX_MODE = "automatic fix not applied: the finding is still present after the fix pass"
DEFAULT_ACTION = "Review this finding and fix it by hand."
REJECTION = "validation_failed:L1-python (SyntaxError)"


def _modules():
    refused_path = "/work/kbi_legacy/views/hr.xml"
    return [
        fixtures.module("kbi_legacy", [
            fixtures.issue("views/hr.xml", 42, "WARNING", "17-18.xml.attrs-removed", "attrs not convertible",
                           auto_fixable=False),
            fixtures.issue("models/a.py", 0, "WARNING", "Version Mismatch", "manifest declares 16.x",
                           auto_fixable=False, suggestion=""),
            fixtures.issue("models/a.py", 5, "WARNING", "17-18.py.attrs", "attr changed", fix_applied=True),
            fixtures.issue("models/c.py", 3, "WARNING", "17-18.py.review", "review me", auto_fixable=True),
        ], fixes=1, experimental=[{"rule_id": "17-18.xml.attrs-removed", "path": refused_path, "converted": [],
                                   "refused": [{"line": 42, "element": "attrs", "reason": REFUSED}]}]),
        dict(fixtures.module("kbi_rej", [
            fixtures.issue("models/b.py", 9, "CRITICAL", "17-18.py.field", "protected identifier",
                           auto_fixable=False, rejection_reason=REJECTION),
            fixtures.issue("models/b.py", 11, "WARNING", "17-18.py.attrs", "attr changed", auto_fixable=True),
        ], status="FAILED", layer1="FAIL", rejections=[REJECTION]),
            refused_files={"/work/kbi_rej/models/b.py": REJECTION}),  # run-state keys are absolute, like the issues'
    ]


def _run(mode="fix"):
    from odooflux.core.orchestrator.run import reports_from_state
    st = fixtures.state(_modules(), mode=mode)
    entries = [m for m in st["modules"] if m["report"]]
    return reports_from_state(st), entries


def _console(report, entry, mode, show_fixed=False) -> str:
    from odooflux.reporting.model.legacy_terminal import print_report
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        print_report(report, no_color=True, show_fixed=show_fixed, entry=entry, mode=mode)
    return buf.getvalue()


def _legacy_json(reports, entries, mode, combined=False) -> dict:
    from odooflux.reporting.model.legacy_json import save_combined_json_report, save_json_report
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        out = Path(tmp) / "r.json"
        if combined:
            save_combined_json_report(reports, out, entries=entries, mode=mode)
        else:
            save_json_report(reports[0], out, entry=entries[0], mode=mode)
        return json.loads(out.read_text(encoding="utf-8"))


_HEAD = re.compile(r"^  \[\w+\s*\] (L\d+(?::(?:\d+|UNKNOWN))?|UNKNOWN)\s+(.+?)(?: \[AUTO-FIX\])?$")


def _console_unresolved(text: str) -> dict:
    """{(relative path, line, rule id): (reason, action)} for every issue block that prints a 'Not fixed' line."""
    found, path, lines = {}, None, text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("  FILE: "):
            path = line[len("  FILE: "):]
        match = _HEAD.match(line)
        if not match or path is None:
            continue
        block = lines[idx + 1:idx + 4]
        reason = [b.split("Not fixed: ", 1)[1] for b in block if "Not fixed: " in b]
        action = [b.split("→ ", 1)[1] for b in block if "→ " in b]
        if reason:
            loc = match.group(1)
            found[(path, loc.split(":")[0][1:] if loc != "UNKNOWN" else loc, match.group(2))] = (reason[0], action[0])
    return found


def _json_unresolved(data: dict) -> dict:
    """The same mapping as _console_unresolved, built from a legacy JSON document."""
    issues = [i for m in data["modules"] for i in m["issues"]] if "modules" in data else data["issues"]
    return {(i["location"]["path"], str(i["location"]["line"]), i["category"]):
            (i["reason_not_fixed"], i["developer_action"]) for i in issues if "location" in i}


class LegacyUnresolvedTests(unittest.TestCase):
    def test_path_exact_line_and_reason_from_the_experimental_refusal(self):
        reports, entries = _run("fix")
        json_issues = {i["category"] + "@" + str(i["line"]): i
                       for i in _legacy_json(reports, entries, "fix")["issues"]}
        hr = json_issues["17-18.xml.attrs-removed@42"]
        self.assertEqual(hr["location"], {"path": "views/hr.xml", "line": 42, "column": "UNKNOWN"})
        self.assertEqual(hr["reason_not_fixed"], REFUSED)
        self.assertEqual(hr["developer_action"], "Apply the documented replacement")
        text = _console(reports[0], entries[0], "fix")
        self.assertIn("  FILE: views/hr.xml", text)
        self.assertIn("L42", text)
        self.assertIn(f"Not fixed: {REFUSED}", text)

    def test_line_zero_is_unknown_in_console_and_json_and_never_invented(self):
        reports, entries = _run("fix")
        text = _console(reports[0], entries[0], "fix")
        self.assertIn("UNKNOWN", text)
        self.assertNotIn("L0", text)
        manifest = next(i for i in _legacy_json(reports, entries, "fix")["issues"]
                        if i["category"] == "Version Mismatch")
        self.assertEqual(manifest["location"], {"path": "models/a.py", "line": "UNKNOWN", "column": "UNKNOWN"})
        self.assertEqual(manifest["line"], 0)
        self.assertEqual(manifest["developer_action"], DEFAULT_ACTION)  # empty suggestion: the generic instruction

    def test_fixed_issue_carries_no_unresolved_fields(self):
        reports, entries = _run("fix")
        fixed = next(i for i in _legacy_json(reports, entries, "fix")["issues"] if i["fix_applied"])
        for key in ("location", "reason_not_fixed", "developer_action"):
            self.assertNotIn(key, fixed)
        console = _console(reports[0], entries[0], "fix", show_fixed=True)
        self.assertIn("✓ FIXED", console)
        self.assertNotIn((("models/a.py"), "5", "17-18.py.attrs"), _console_unresolved(console))
        self.assertEqual(len(re.findall(r"Not fixed:", console)), len(_console_unresolved(console)))

    def test_console_and_legacy_json_agree_for_single_and_combined(self):
        reports, entries = _run("fix")
        for module_reports, module_entries, combined in ((reports[:1], entries[:1], False), (reports, entries, True)):
            console = {}
            for report, entry in zip(module_reports, module_entries):
                for key, value in _console_unresolved(_console(report, entry, "fix")).items():
                    console[key] = value
            data = _legacy_json(module_reports, module_entries, "fix", combined=combined)
            self.assertTrue(console)
            self.assertEqual(console, _json_unresolved(data))

    def test_legacy_json_matches_the_model_fed_exporter(self):
        from odooflux.core.orchestrator.run import reports_from_state
        from odooflux.reporting.exporters.legacy_json import export_legacy_json
        from odooflux.reporting.model.model import build_report
        st = fixtures.state(_modules(), mode="fix")
        model = json.loads(export_legacy_json(build_report(st, reports_from_state(st), run_log_path="")))
        reports, entries = _run("fix")
        self.assertEqual(_json_unresolved(model), _json_unresolved(_legacy_json(reports, entries, "fix", True)))

    def test_run_mode_changes_the_reason_identically_in_console_and_json(self):
        for mode, expected in (("dry_run", DRY_RUN), ("fix", FIX_MODE)):
            reports, entries = _run(mode)
            console = _console_unresolved(_console(reports[0], entries[0], mode))
            self.assertEqual(console[("models/c.py", "3", "17-18.py.review")][0], expected, mode)
            data = _json_unresolved(_legacy_json(reports, entries, mode, combined=True))
            self.assertEqual(data[("models/c.py", "3", "17-18.py.review")][0], expected, mode)

    def test_module_rejection_and_rejected_issue_reasons(self):
        reports, entries = _run("fix")
        rej = _json_unresolved(_legacy_json(reports[1:], entries[1:], "fix"))
        self.assertEqual(rej[("models/b.py", "9", "17-18.py.field")], (REJECTION, "Apply the documented replacement"))
        # Approved partial-migration policy (PA-3): only the refused file's open findings name the refusal.
        self.assertEqual(rej[("models/b.py", "11", "17-18.py.attrs")][0],
                         f"fix rejected by validation ({REJECTION}); the finding stays open")

    def test_one_extra_line_per_unresolved_issue_and_no_reason_without_one(self):
        reports, entries = _run("fix")
        text = _console(reports[0], entries[0], "fix")
        self.assertEqual(text.count("Not fixed:"), 3)  # views/hr.xml, models/a.py line 0, models/c.py
        self.assertEqual(len(re.findall(r"^ {11}→ ", text, re.M)), 3)  # the action line (not the title's arrow)


if __name__ == "__main__":
    unittest.main()
