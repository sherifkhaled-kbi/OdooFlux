"""WSE-001 (legacy disposition, retire rows): version windows and precedence over knowledge rules.

Retire rows still run (the legacy tables are unchanged apart from window gating), but a row whose construct is
out of scope for the run must not fire, and a retired category must never suppress a knowledge rule.
"""

import unittest

from .. import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.orchestrator import knowledge_rules as kr
from odooflux.rules.shared import legacy_overlap
from odooflux.rules.shared import legacy_rules as L
from odooflux.rules.shared.legacy_rules import Issue

TABLES = ("PYTHON_RULES", "XML_RULES", "MANIFEST_RULES", "JS_TS_RULES", "CSS_RULES")
# Retire rows whose disposition says "out of scope (pre-12.0)" (legacy_disposition.json, planning document).
PRE_12_CATEGORIES = {"Legacy Namespace", "Legacy Field Definition", "Legacy Defaults", "Import Path",
                     "Python 2 Syntax", "Removed Model", "HTTP Controller Import", "Legacy openerp Import",
                     "Removed Exception: Warning (openerp)"}
SUPPORTED_RUNS = [(v, v + 1) for v in range(12, 19)]


def fired(text: str, path: str, from_version: int, to_version: int) -> set:
    """Categories the legacy tables report for one file and one run."""
    report = L.MigrationReport(module_path="", from_version=from_version, to_version=to_version)
    rules = L._rules_for_file(L.Path(path), to_version=to_version)
    L.check_content(text, path, rules, from_version, report)
    return {issue.category for issue in report.issues}


class PreTwelveWindowTests(unittest.TestCase):
    def test_pre_12_rows_are_gated_to_sources_below_12(self):
        gated = {row[4] for table in TABLES for row in getattr(L, table) if row[0] == 12}
        self.assertEqual(gated, PRE_12_CATEGORIES)

    def test_pre_12_rows_do_not_fire_on_supported_runs(self):
        text = ("from openerp import models\nimport openerp\n"
                "from openerp.tools import html_sanitize\n"
                "class A(models.Model):\n    _columns = {}\n    _defaults = {}\n")
        for from_version, to_version in SUPPORTED_RUNS:
            with self.subTest(run=(from_version, to_version)):
                self.assertFalse(fired(text, "m.py", from_version, to_version) & PRE_12_CATEGORIES)

    def test_pre_12_rows_still_fire_below_12(self):
        text = "from openerp.models import Model\n_columns = {}\n"
        got = fired(text, "m.py", 11, 12)
        self.assertIn("Legacy openerp Import", got)
        self.assertIn("Legacy Field Definition", got)

    def test_retired_rows_in_window_still_fire(self):
        # Page Attrs (retire) is a 17.0 construct: it applies to every run that starts below 17.
        text = '<odoo><form><sheet><page string="x" attrs="{}"/></sheet></form></odoo>\n'
        self.assertIn("Page Attrs", fired(text, "v.xml", 16, 17))
        self.assertIn("Page Attrs", fired(text, "v.xml", 12, 13))
        self.assertNotIn("Page Attrs", fired(text, "v.xml", 17, 18))


class RetiredPrecedenceTests(unittest.TestCase):
    def issue(self, category, line, file="v.xml"):
        return Issue(file=file, line=line, severity="CRITICAL", category=category, message="m", suggestion="s")

    def test_retired_category_does_not_count_as_a_witness(self):
        self.assertFalse(legacy_overlap.covered("16-17.xml.attrs-removed", 3, {"Page Attrs": {3}}))
        self.assertTrue(legacy_overlap.covered("16-17.xml.attrs-removed", 3, {"Attrs Attribute": {3}}))

    def test_knowledge_issue_survives_a_retired_row_on_its_line(self):
        knowledge_id = "16-17.xml.attrs-removed"
        issues = [self.issue("Page Attrs", 3), self.issue(knowledge_id, 3)]
        kept = kr.deduplicate(issues, {knowledge_id})
        self.assertEqual([(i.category, i.line) for i in kept], [(knowledge_id, 3)])

    def test_correct_legacy_witness_still_suppresses_the_knowledge_issue(self):
        knowledge_id = "16-17.xml.attrs-removed"
        issues = [self.issue("Attrs Attribute", 3), self.issue(knowledge_id, 3)]
        kept = kr.deduplicate(issues, {knowledge_id})
        self.assertEqual([(i.category, i.line) for i in kept], [("Attrs Attribute", 3)])

    def test_knowledge_rule_not_applicable_to_the_run_does_not_suppress_anything(self):
        issues = [self.issue("Attrs Attribute", 3), self.issue("16-17.xml.attrs-removed", 3)]
        kept = kr.deduplicate(issues, set())
        self.assertEqual(len(kept), 2)


class RetiredDuplicateTests(unittest.TestCase):
    def test_page_attrs_does_not_double_report_next_to_attrs_attribute(self):
        make = RetiredPrecedenceTests.issue
        issues = [make(None, "Attrs Attribute", 3), make(None, "Page Attrs", 3), make(None, "Page Attrs", 9)]
        kept = kr.deduplicate(issues, {"16-17.xml.attrs-removed"})
        self.assertEqual(sorted((i.category, i.line) for i in kept),
                         [("Attrs Attribute", 3), ("Page Attrs", 9)])


if __name__ == "__main__":
    unittest.main()
