"""WS-E (006 T086-T089; FR-017, ADR-018, SC-005, SC-006): knowledge rules run in the real ``migrate`` pipeline.

Integration layer, through the CLI on a copy of the PROVISIONAL 17.0 fixture. The fixture is provisional validation
material, not approved migration truth (ADR-019); these tests check wiring, not migration correctness.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests._support import fixtures

from .helpers import REPO

DETECT_ONLY_17_18 = {
    "17-18.python.name-get-removed": "def name_get",
    "17-18.python.name-search-to-search-display-name": "_name_search",
    "17-18.python.user-has-groups-removed": "user_has_groups",
    "17-18.xml.cron-numbercall-removed": 'name="numbercall"',
    "17-18.xml.kanban-box-deprecated": "kanban-box",
}


def _cli(args):
    proc = subprocess.run([sys.executable, str(REPO / "odooflux.py"), *map(str, args)],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
                          env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    return proc.returncode, proc.stdout


def _migrate(work: Path, module: Path, frm: str, to: str, *extra):
    report = work / "report.json"
    code, out = _cli(["--module", module, "--from-version", frm, "--to-version", to, "--report-format", "json",
                      "--report", report, "--state-dir", work / "state", *extra])
    data = json.loads(report.read_text(encoding="utf-8"))
    return code, out, [f for m in data["modules"] for f in m["findings"]]


class KnowledgeFindingsThroughCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.module = fixtures.copy_fixture("17.0/kbi_demo", self.work / "in")

    def tearDown(self):
        self._tmp.cleanup()

    def test_17_to_18_reports_knowledge_rule_findings_with_evidence(self):
        _code, out, found = _migrate(self.work, self.module, "17", "18")
        by_rule = {}
        for f in found:
            by_rule.setdefault(f["rule_id"], []).append(f)
        for rule_id in DETECT_ONLY_17_18:
            self.assertIn(rule_id, by_rule, out)
            for f in by_rule[rule_id]:
                self.assertTrue(f["evidence"], rule_id)
                self.assertEqual(f["maturity"], "DETECT_ONLY")
                self.assertIs(f["review_required"], rule_id != "17-18.xml.kanban-box-deprecated")
                self.assertEqual(f["status"], "NEEDS_REVIEW")
        self.assertIn("17-18.python.group-operator-renamed", by_rule)
        self.assertEqual(by_rule["17-18.python.group-operator-renamed"][0]["maturity"], "FIX_ENABLED")

    def test_steps_outside_the_plan_do_not_report(self):
        _code, _out, found = _migrate(self.work, self.module, "17", "18")
        self.assertFalse([f for f in found if f["rule_id"].startswith(("18-19.", "16-17."))])

    def test_17_to_19_adds_the_18_19_step_rules(self):
        _code, _out, found = _migrate(self.work, self.module, "17", "19")
        ids = {f["rule_id"] for f in found}
        self.assertIn("17-18.python.name-get-removed", ids)
        self.assertTrue(any(i.startswith("18-19.") for i in ids), sorted(ids))

    def test_sql_constraints_and_api_returns_report_for_17_to_19(self):
        """006 quickstart smoke: _sql_constraints and @api.returns findings on the 17 -> 19 path."""
        (self.module / "models" / "extra.py").write_text(
            "from odoo import api, models\n\n\nclass Extra(models.Model):\n    _name = 'kbi.extra'\n"
            "    _sql_constraints = [('name_uniq', 'unique(name)', 'Name must be unique')]\n\n"
            "    @api.returns('self')\n    def copy(self, default=None):\n        return super().copy(default)\n",
            encoding="utf-8")
        _code, _out, found = _migrate(self.work, self.module, "17", "19")
        ids = {f["rule_id"] for f in found}
        self.assertIn("18-19.python.sql-constraints-unsupported", ids)
        self.assertTrue(ids & {"18-19.python.api-returns-removed", "Deprecated Decorator"}, sorted(ids))

    def test_detect_only_constructs_survive_fix_mode(self):
        """SC-005: --fix edits nothing for DETECT_ONLY rules; the flagged constructs remain byte-for-byte."""
        _code, out, found = _migrate(self.work, self.module, "17", "18", "--fix", "--no-backup")
        detect_only = {f["rule_id"] for f in found if f.get("maturity") == "DETECT_ONLY"}
        self.assertTrue(set(DETECT_ONLY_17_18) <= detect_only, out)
        for f in found:
            if f.get("maturity") == "DETECT_ONLY":
                self.assertNotEqual(f["status"], "FIXED", f["rule_id"])
        for rule_id, needle in DETECT_ONLY_17_18.items():
            hit = [p for p in self.module.rglob("*") if p.is_file() and p.suffix in (".py", ".xml")
                   and needle in p.read_text(encoding="utf-8")]
            self.assertTrue(hit, f"{rule_id}: {needle} was edited")

    def test_fix_enabled_knowledge_rule_edits_through_validated_path(self):
        _code, out, found = _migrate(self.work, self.module, "17", "18", "--fix", "--no-backup")
        text = (self.module / "models" / "demo.py").read_text(encoding="utf-8")
        self.assertNotIn("group_operator", text, out)
        self.assertIn("aggregator='avg'", text)
        fixed = [f for f in found if f["rule_id"] == "17-18.python.group-operator-renamed"]
        self.assertTrue(fixed)
        self.assertTrue(all(f["status"] == "FIXED" for f in fixed), fixed)

    def test_each_construct_is_reported_once(self):
        """Dedup: a rule kept in both the legacy table and the knowledge base emits once per file and line."""
        (self.module / "views" / "extra.xml").write_text(
            '<odoo>\n<record id="v" model="ir.ui.view"><field name="arch" type="xml">\n'
            '<tree><field name="name"/></tree>\n</field></record>\n</odoo>\n', encoding="utf-8")
        _code, _out, found = _migrate(self.work, self.module, "17", "18")
        tree_lines = [f for f in found if f["path"] == "views/extra.xml" and f["line"] == 3]
        self.assertEqual(len(tree_lines), 1, tree_lines)
        self.assertEqual(tree_lines[0]["rule_id"], "Tree Tag Renamed")
        keys = [(f["rule_id"], f["path"], f["line"]) for f in found]
        self.assertEqual(len(keys), len(set(keys)))

    def test_largest_golden_module_analysis_is_fast(self):
        """006 SC-006: the largest golden module analyses in under 10 s."""
        sizes = {}
        for item in fixtures.load_index():
            module = fixtures.module_dir(item)
            if module.is_dir():
                sizes[item["id"]] = sum(p.stat().st_size for p in module.rglob("*")
                                        if p.is_file() and "expected" not in p.parts)
        biggest = max(sizes, key=sizes.get)
        module = fixtures.copy_fixture(biggest, self.work / "big")
        frm = fixtures.entry(biggest)["source_version"].split(".")[0]
        start = time.monotonic()
        code, out, _found = _migrate(self.work, module, frm, "19")
        self.assertLess(time.monotonic() - start, 10.0, out)


if __name__ == "__main__":
    unittest.main()
