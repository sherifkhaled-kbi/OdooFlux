"""WS-E (006 T085, FR-017, ADR-018): per-step selection of knowledge rules for the migrate pipeline.

Unit layer: which metadata rows a (source, target) plan selects, how they bind, and how overlap with the legacy
tables is declared. No file is scanned here.
"""

import json
import unittest

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.orchestrator import knowledge_rules as kr
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared import legacy_overlap
from odooflux.rules.shared import legacy_rules

ROWS = load_knowledge().rules


class StepKeyTests(unittest.TestCase):
    def test_plan_step_ids_become_rule_step_keys(self):
        self.assertEqual(kr.step_keys(["17.0->18.0", "18.0->19.0"]), ["17-18", "18-19"])

    def test_range_fallback(self):
        self.assertEqual(kr.step_keys_for_range(15, 18), ["15-16", "16-17", "17-18"])


class SelectionTests(unittest.TestCase):
    def ids(self, steps):
        return {r["id"] for r in kr.select_rows(ROWS, BINDABLE_MODULES, steps)}

    def test_step_specific_rules_follow_the_plan_window(self):
        got = self.ids(["17-18"])
        self.assertIn("17-18.python.name-get-removed", got)
        self.assertNotIn("18-19.python.sql-constraints-unsupported", got)
        self.assertNotIn("16-17.python.name-get-deprecated", got)

    def test_two_steps_select_both_windows(self):
        got = self.ids(["17-18", "18-19"])
        self.assertIn("17-18.xml.cron-numbercall-removed", got)
        self.assertIn("18-19.python.sql-constraints-unsupported", got)

    def test_shared_rules_apply_to_every_plan(self):
        for steps in (["12-13"], ["17-18"], ["18-19"]):
            self.assertIn("*.manifest.not-installable", self.ids(steps))

    def test_run_input_rules_stay_opt_in(self):
        self.assertNotIn("*.manifest.version-prefix", self.ids(["17-18"]))

    def test_draft_and_retired_rules_never_run(self):
        draft = {r["id"] for r in ROWS if r["maturity"] in ("DRAFT", "RETIRED")}
        self.assertTrue(draft)
        self.assertFalse(draft & self.ids(["12-13", "14-15", "15-16", "16-17", "17-18", "18-19"]))

    def test_every_selected_row_is_detect_only_or_fix_enabled(self):
        for row in kr.select_rows(ROWS, BINDABLE_MODULES, ["17-18"]):
            self.assertIn(row["maturity"], ("DETECT_ONLY", "FIX_ENABLED"))

    def test_unknown_step_selects_only_shared_rules(self):
        got = kr.select_rows(ROWS, BINDABLE_MODULES, ["99-100"])
        self.assertTrue(got)
        self.assertTrue(all(r["step"] == "*" for r in got))


class BindTests(unittest.TestCase):
    def test_bind_keeps_maturity_review_flag_and_evidence(self):
        rules, gaps = kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {"target": "18.0"}, ["17-18"])
        by_id = {r.key: r for r in rules}
        rule = by_id["17-18.python.name-get-removed"]
        self.assertEqual((rule.maturity, rule.review_required), ("DETECT_ONLY", True))
        self.assertTrue(rule.evidence)
        self.assertFalse(rule.fixes)
        self.assertTrue(by_id["17-18.python.group-operator-renamed"].fixes)
        self.assertEqual(gaps, [])

    def test_kb_row_maturities_are_unchanged(self):
        counts = {}
        for row in ROWS:
            counts[row["maturity"]] = counts.get(row["maturity"], 0) + 1
        self.assertEqual(len(ROWS), 91)
        self.assertEqual(counts, {"DETECT_ONLY": 78, "FIX_ENABLED": 10, "DRAFT": 3})


class OverlapTests(unittest.TestCase):
    def test_overlap_names_real_rules_and_real_legacy_categories(self):
        ids = {r["id"] for r in ROWS}
        categories = set()
        for name in dir(legacy_rules):
            if name.isupper() and isinstance(getattr(legacy_rules, name), list) and not name.endswith("_C"):
                categories |= {row[4] for row in getattr(legacy_rules, name) if isinstance(row, tuple) and len(row) == 8}
        for rule_id, cats in legacy_overlap.LEGACY_CATEGORIES.items():
            self.assertIn(rule_id, ids)
            self.assertTrue(set(cats) <= categories, (rule_id, set(cats) - categories))

    def test_overlap_agrees_with_the_legacy_disposition(self):
        path = load_knowledge().root / "compatibility" / "legacy_disposition.json"
        listed = {rid for e in json.loads(path.read_text(encoding="utf-8")) for rid in e["new_rule_ids"]}
        self.assertTrue(set(legacy_overlap.LEGACY_CATEGORIES) <= listed)


class DedupAndTransformTests(unittest.TestCase):
    def issue(self, category, line, file="a.xml"):
        return legacy_rules.Issue(file=file, line=line, severity="WARNING", category=category, message="m",
                                  suggestion="s")

    def test_knowledge_issue_on_a_legacy_covered_line_is_dropped(self):
        issues = [self.issue("Tree Tag Renamed", 3), self.issue("17-18.xml.tree-to-list", 3),
                  self.issue("17-18.xml.tree-to-list", 9)]
        kept = kr.deduplicate(issues, {"17-18.xml.tree-to-list"})
        self.assertEqual([(i.category, i.line) for i in kept],
                         [("Tree Tag Renamed", 3), ("17-18.xml.tree-to-list", 9)])

    def test_other_file_or_unrelated_legacy_category_does_not_suppress(self):
        issues = [self.issue("Tree Tag Renamed", 3, "b.xml"), self.issue("17-18.xml.tree-to-list", 3),
                  self.issue("Attrs Attribute", 4), self.issue("17-18.xml.tree-to-list", 4)]
        kept = kr.deduplicate(issues, {"17-18.xml.tree-to-list"})
        self.assertEqual(len(kept), 4)

    def test_legacy_issues_are_never_dropped(self):
        issues = [self.issue("Tree Tag Renamed", 3), self.issue("Tree Tag Renamed", 3)]
        self.assertEqual(len(kr.deduplicate(issues, set())), 2)

    def test_transform_applies_only_fix_enabled_rules_and_only_for_the_file_kind(self):
        rules, _ = kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {"target": "18.0"}, ["17-18"])
        transform = kr.fixing_transform(rules, ["17-18"])
        text = "class A:\n    x = fields.Float(group_operator='sum')\n    def name_get(self):\n        pass\n"
        out = transform("m.py", text)
        self.assertIn("aggregator='sum'", out)
        self.assertIn("def name_get", out)  # DETECT_ONLY: untouched
        self.assertEqual(transform("m.txt", text), text)

    def test_no_detect_only_rule_has_a_fixer(self):
        rules, _ = kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {"target": "19.0"},
                                           ["12-13", "14-15", "15-16", "16-17", "17-18", "18-19"])
        self.assertTrue(rules)
        for rule in rules:
            self.assertEqual(rule.fixes, rule.maturity == "FIX_ENABLED", rule.key)
            if rule.review_required:
                self.assertFalse(rule.fixes, rule.key)


if __name__ == "__main__":
    unittest.main()
