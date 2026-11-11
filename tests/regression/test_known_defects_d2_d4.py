"""Known, confirmed defects of the legacy layer, pinned as expected failures (2026-11-11 automation audit).

Each test states the CORRECT behaviour and is marked `expectedFailure`: the suite stays green while the defect exists,
and the day it is fixed the test reports an unexpected success, which fails the suite and forces this file to be
updated. The current behaviour is deliberately NOT changed here (certified-mode and report behaviour are preserved
until the owner decides the correction). See specs/012-knowledge-base-auto-update/verification.md, "Known defects".

D2  The legacy `states=` -> `invisible="state not in [...]"` regex runs under plain `--fix` without checking that the
    view's model has a `state` field, so it can produce a view that Odoo 17 rejects. It is a correctness defect of an
    UNCERTIFIED rewrite that plain `--fix` performs.
D3  A `--dry-run` report claims `recovery.reversible: true` and prints a rollback command for a run that wrote nothing.
D4  A 16 -> 17 report flags `<tree>` as "deprecated in v18" (CRITICAL, auto-fixable) although `<tree>` is the valid
    tag for 17.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from odooflux.rules.shared.legacy_rules import apply_xml_fixes, scan_content

REPO = Path(__file__).resolve().parents[2]


class D2StatesWithoutStateField(unittest.TestCase):
    @unittest.expectedFailure
    def test_states_is_left_alone_when_no_state_field_is_verified(self):
        view = '<form><button name="go" states="draft,done"/></form>\n'  # the fixer has no model information
        out = apply_xml_fixes(view, 16, 17)
        self.assertIn('states="draft,done"', out)  # today: rewritten to invisible="state not in ['draft', 'done']"

    def test_current_behaviour_is_pinned(self):
        out = apply_xml_fixes('<form><button name="go" states="draft,done"/></form>\n', 16, 17)
        self.assertIn("state not in ['draft', 'done']", out)  # flips when D2 is corrected: update both tests


class D4TreeFlaggedAsV18On17Target(unittest.TestCase):
    @unittest.expectedFailure
    def test_no_tree_deprecation_finding_for_a_17_target(self):
        found = {i.category for i in scan_content("<form/>\n<tree>\n<field name='a'/>\n</tree>\n", "v.xml", 16, 17)}
        self.assertNotIn("Tree Tag Renamed", found)

    def test_current_behaviour_is_pinned(self):
        found = {i.category for i in scan_content("<tree>\n</tree>\n", "v.xml", 16, 17)}
        self.assertIn("Tree Tag Renamed", found)  # flips when D4 is corrected: update both tests


class D3DryRunClaimsReversible(unittest.TestCase):
    def _dry_run_report(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "addons" / "mod"
            module.mkdir(parents=True)
            (module / "__manifest__.py").write_text('{"name": "m", "version": "16.0.1.0.0", "depends": ["base"]}\n',
                                                    encoding="utf-8")
            (module / "__init__.py").write_text("\n", encoding="utf-8")
            report = Path(tmp) / "report.json"
            env = {k: v for k, v in os.environ.items() if k not in ("ODOOFLUX_KB_HOME", "PYTHONPATH")}
            env.update(PYTHONPATH=str(REPO / "src"), XDG_CACHE_HOME=str(Path(tmp) / "cache"))
            subprocess.run([sys.executable, "-m", "odooflux", "migrate", "--addons-path", str(Path(tmp) / "addons"), "--from-version", "16",
                            "--to-version", "17", "--fix", "--dry-run", "--report", str(report), "--report-format",
                            "json"], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
            return json.loads(report.read_text(encoding="utf-8"))

    @unittest.expectedFailure
    def test_dry_run_is_not_reported_as_reversible(self):
        recovery = self._dry_run_report()["recovery"]
        self.assertFalse(recovery.get("reversible"))  # today: True, with a rollback command

    def test_current_behaviour_is_pinned(self):
        recovery = self._dry_run_report()["recovery"]
        self.assertTrue(recovery.get("reversible"))  # flips when D3 is corrected: update both tests


if __name__ == "__main__":
    unittest.main()
