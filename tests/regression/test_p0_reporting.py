"""P0 reporting, exit codes, manifest version and artifact placement (FR-008..011, FR-009, FR-010)."""

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import odooflux.ai.providers.legacy_anthropic as legacy_ai
import odooflux.rules.shared.legacy_adapter as adapter
from odooflux.rules.shared.legacy_rules import apply_manifest_fixes

from tests._support.p0 import make_addons, only_run, run_cli, run_main, tree_digest


def _issues(report_path):
    return json.loads(Path(report_path).read_text(encoding="utf-8"))["issues"]


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addons = make_addons(self.tmp)
        self.module = self.addons / "kbi_demo"
        self.state = self.tmp / "state"

    def tearDown(self):
        self._tmp.cleanup()


class FixedCountTests(_Case):
    def test_fixed_count_equals_rescan_delta(self):
        """TST-001-025 / FR-008 / F-REP-1 / SC-004: reported fixed count equals findings present before and
        absent after a re-scan (per category, as in the attribution rule)."""
        before_json = self.tmp / "before.json"
        run_cli(["--module", self.module, "--from-version", "14", "--no-color",
                 "--report", before_json, "--state-dir", self.tmp / "s0"])
        fixed_json = self.tmp / "fixed.json"
        run_cli(["--module", self.module, "--from-version", "14", "--fix", "--no-color",
                 "--report", fixed_json, "--state-dir", self.state])
        after_json = self.tmp / "after.json"
        run_cli(["--module", self.module, "--from-version", "14", "--no-color",
                 "--report", after_json, "--state-dir", self.tmp / "s2"])

        reported_fixed = sum(1 for i in _issues(fixed_json) if i["fix_applied"])
        before = Counter(i["category"] for i in _issues(before_json))
        after = Counter(i["category"] for i in _issues(after_json))
        rescan_delta = sum(max(0, before[c] - after[c]) for c in before)
        self.assertGreater(reported_fixed, 0)
        self.assertEqual(reported_fixed, rescan_delta)


class ManifestVersionTests(unittest.TestCase):
    def test_manifest_version_suffix_preserved(self):
        """TST-001-026 / FR-009 / F-MAN-1: only the major prefix changes; single and double quotes work."""
        out = apply_manifest_fixes("{'version': '14.0.2.3.1'}\n", 14, to_version=19)
        self.assertEqual(out, "{'version': '19.0.2.3.1'}\n")
        out = apply_manifest_fixes('{"version": "14.0.1.0.0"}\n', 14, to_version=19)
        self.assertEqual(out, '{"version": "19.0.1.0.0"}\n')


class ExitCodeTests(_Case):
    """TST-001-028 / TST-001-029 (FR-010, F-REP-3): --fail-on thresholds and exit precedence."""

    def _module(self, name, source):
        path = self.tmp / name
        path.mkdir()
        (path / "models.py").write_text(source, encoding="utf-8")
        return path

    def test_fail_on_thresholds(self):
        warn_only = self._module("warn_mod", "from odoo import fields\nname = fields.Char(size=64)\n")
        info_only = self._module("info_mod", "from odoo import fields\nbody = fields.Html('x')\n")
        expect = {
            # module, fail-on, expected exit code
            (warn_only, "critical"): 0, (warn_only, "warning"): 1,
            (warn_only, "info"): 1, (warn_only, "none"): 0,
            (info_only, "critical"): 0, (info_only, "warning"): 0,
            (info_only, "info"): 1, (info_only, "none"): 0,
        }
        for (module, level), want in expect.items():
            code, out = run_cli(["--module", module, "--from-version", "14", "--no-color",
                                 "--fail-on", level, "--state-dir", self.state])
            self.assertEqual(code, want, f"{module.name} --fail-on {level}: {out}")

    def test_exit_codes_rejected_3_blocked_4(self):
        """Rejected edit in write mode -> 3; blocked module -> 4; 4 takes precedence over 3."""
        with mock.patch.object(adapter, "apply_python_fixes",
                               side_effect=lambda c, *a, **k: "def broken(:\n"):
            code, _ = run_main(["--module", self.module, "--from-version", "14", "--fix",
                                "--no-color", "--state-dir", self.state])
        self.assertEqual(code, 3)

        with mock.patch("shutil.copytree", side_effect=OSError("disk full")):
            code, _ = run_main(["--module", self.module, "--from-version", "14", "--fix",
                                "--no-color", "--state-dir", self.tmp / "s2"])
        self.assertEqual(code, 4)

    def test_state_dir_inside_scan_exit_4(self):
        code, _ = run_cli(["--module", self.module, "--from-version", "14", "--no-color",
                           "--state-dir", self.module / "state"])
        self.assertEqual(code, 4)


class ArtifactPlacementTests(_Case):
    def test_no_tool_artifacts_in_module(self):
        """TST-001-030 / FR-011 / F-AI-6: no debug, draft, or log file lands in the module."""
        # Path 1: AI returns valid JSON that changes a file -> the file is written, nothing else.
        good = json.dumps({"files": {"kbi_demo/demo.py":
                                     (self.module / "models" / "demo.py").read_text("utf-8")
                                     + "\n# reviewed\n"}, "skipped": [], "notes": ""})
        with mock.patch.object(legacy_ai, "_call_claude_api", return_value=good):
            run_main(["--module", self.module, "--from-version", "14", "--fix", "--ai-fix",
                      "--api-key", "k", "--no-color", "--state-dir", self.state])
        # Path 2: AI returns non-JSON -> the raw response goes to the state dir, not the module.
        with mock.patch.object(legacy_ai, "_call_claude_api", return_value="not json at all"):
            run_main(["--module", self.module, "--from-version", "14", "--fix", "--ai-fix",
                      "--api-key", "k", "--no-color", "--state-dir", self.tmp / "s2"])
        names = {p.name for p in self.module.rglob("*")}
        for forbidden in ("ai_response_debug.txt",):
            self.assertNotIn(forbidden, names)
        self.assertFalse(list(self.module.rglob("*.ai_draft")))
        self.assertFalse(list(self.module.rglob("*.log")))
        self.assertTrue(list((self.tmp / "s2").rglob("ai_response_debug.txt")))


if __name__ == "__main__":
    unittest.main()
