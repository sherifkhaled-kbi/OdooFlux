"""Experimental registry and binder (roadmap T1, AD-1): the registry fixer is bound to the existing detector only when
asked, the row keeps DETECT_ONLY, and the ordinary "fixer_ref requires FIX_ENABLED" check still holds.
"""

import copy
import unittest

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.orchestrator import knowledge_rules as kr
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.experimental import registry
from odooflux.rules.experimental import xml_modifiers
from odooflux.rules.shared import legacy_rules
from odooflux.rules.shared.loader import BindingError, bind_rule

ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"
ROWS = load_knowledge().rules
ROW = {r["id"]: r for r in ROWS}


def row(rule_id):
    return copy.deepcopy(ROW[rule_id])


class RegistryTests(unittest.TestCase):
    def test_registry_holds_the_two_shipped_attrs_and_states_rules(self):
        self.assertEqual(sorted(registry.ENTRIES), sorted([ATTRS, STATES]))

    def test_every_registry_fixer_ref_resolves_through_the_registry_modules(self):
        modules = {**BINDABLE_MODULES, **registry.MODULES}
        for rule_id, entry in registry.ENTRIES.items():
            with self.subTest(rule=rule_id):
                bound = bind_rule({**row(rule_id), "fixer_ref": None}, modules, experimental=entry)
                self.assertIsNotNone(bound.fixer)
                self.assertEqual(bound.fixer.__name__, entry.fixer_ref.split(":")[1])

    def test_registry_modules_are_not_bindable_by_plain_rows(self):
        # a plain row cannot reach the experimental module: it is not in the bindable table
        self.assertNotIn("odooflux.rules.experimental.xml_modifiers", BINDABLE_MODULES)

    def test_registry_entries_carry_a_description(self):
        for entry in registry.ENTRIES.values():
            self.assertTrue(entry.description)


class BindRuleTests(unittest.TestCase):
    def test_plain_bind_of_a_detect_only_row_still_has_no_fixer(self):
        bound = bind_rule(row(ATTRS), BINDABLE_MODULES)
        self.assertIsNone(bound.fixer)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertFalse(bound.experimental)

    def test_experimental_bind_attaches_the_fixer_and_keeps_detect_only(self):
        meta = row(ATTRS)
        before = copy.deepcopy(meta)
        bound = bind_rule(meta, {**BINDABLE_MODULES, **registry.MODULES}, experimental=registry.ENTRIES[ATTRS])
        self.assertIs(bound.fixer, xml_modifiers.convert_attrs)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.experimental)
        self.assertEqual(meta, before, "the metadata row must not be mutated")

    def test_experimental_fixer_on_a_fix_enabled_row_is_refused(self):
        fix_enabled = {**row(ATTRS), "maturity": "FIX_ENABLED",
                       "fixer_ref": "odooflux.rules.xml.generic:remove_attribute"}
        with self.assertRaisesRegex(BindingError, "experimental fixer requires DETECT_ONLY"):
            bind_rule(fix_enabled, {**BINDABLE_MODULES, **registry.MODULES}, experimental=registry.ENTRIES[ATTRS])

    def test_experimental_fixer_on_a_row_that_already_has_a_fixer_is_refused(self):
        meta = {**row(ATTRS), "fixer_ref": "odooflux.rules.xml.generic:remove_attribute"}
        with self.assertRaisesRegex(BindingError, "already has a fixer_ref"):
            bind_rule(meta, {**BINDABLE_MODULES, **registry.MODULES}, experimental=registry.ENTRIES[ATTRS])

    def test_ordinary_fixer_ref_on_detect_only_is_still_refused(self):
        meta = {**row(ATTRS), "fixer_ref": "odooflux.rules.xml.generic:remove_attribute"}
        with self.assertRaisesRegex(BindingError, "fixer_ref requires FIX_ENABLED maturity"):
            bind_rule(meta, BINDABLE_MODULES)

    def test_experimental_module_is_not_reachable_without_the_registry(self):
        meta = {**row(ATTRS), "fixer_ref": "odooflux.rules.experimental.xml_modifiers:convert_attrs"}
        with self.assertRaisesRegex(BindingError, "does not resolve"):
            bind_rule(meta, BINDABLE_MODULES)

    def test_experimental_bind_of_a_review_required_row_is_refused(self):
        meta = {**row(ATTRS), "review_required": True}
        with self.assertRaisesRegex(BindingError, "review_required rule must not have a fixer_ref"):
            bind_rule(meta, {**BINDABLE_MODULES, **registry.MODULES}, experimental=registry.ENTRIES[ATTRS])


class SelectionAndKnowledgeRuleTests(unittest.TestCase):
    def bind(self, experimental):
        fixers = None if experimental is None else kr.ExperimentalFixers(entries=experimental,
                                                                         modules=registry.MODULES)
        return kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {}, ["16-17"], fixers)

    def test_flag_off_binds_both_rules_without_a_fixer(self):
        rules, _gaps = self.bind(None)
        by_id = {r.key: r for r in rules}
        self.assertFalse(by_id[ATTRS].fixes)
        self.assertFalse(by_id[STATES].fixes)
        self.assertFalse(by_id[ATTRS].experimental)

    def test_flag_off_is_the_same_as_an_omitted_argument(self):
        omitted, _ = kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {}, ["16-17"])
        explicit, _ = self.bind(None)
        self.assertEqual([(r.key, r.maturity, r.fixes, r.experimental) for r in omitted],
                         [(r.key, r.maturity, r.fixes, r.experimental) for r in explicit])

    def test_flag_on_fixes_the_two_rules_as_experimental_and_keeps_maturity(self):
        rules, gaps = self.bind(registry.ENTRIES)
        by_id = {r.key: r for r in rules}
        for rule_id in (ATTRS, STATES):
            with self.subTest(rule=rule_id):
                self.assertTrue(by_id[rule_id].fixes)
                self.assertTrue(by_id[rule_id].experimental)
                self.assertEqual(by_id[rule_id].maturity, "DETECT_ONLY")
                self.assertEqual(by_id[rule_id].fix_class, "experimental")
        self.assertEqual([g for g in gaps if ATTRS in g or STATES in g], [])

    def test_kb_rows_are_unchanged_after_binding_with_the_flag_on(self):
        before = copy.deepcopy(ROWS)
        self.bind(registry.ENTRIES)
        self.assertEqual(ROWS, before)
        for rule_id in (ATTRS, STATES):
            self.assertEqual(ROW[rule_id]["maturity"], "DETECT_ONLY")
            self.assertIsNone(ROW[rule_id]["fixer_ref"])

    def test_certified_rows_keep_their_class(self):
        rules, _ = self.bind(registry.ENTRIES)
        for rule in rules:
            if rule.key not in registry.ENTRIES:
                self.assertFalse(rule.experimental, rule.key)

    def test_experimental_transform_converts_and_logs_the_element(self):
        rules, _ = self.bind(registry.ENTRIES)
        log = []
        transform = kr.fixing_transform(rules, ["16-17"], log)
        text = '<form>\n  <field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/>\n</form>\n'
        out = transform("v.xml", text)
        self.assertIn('invisible="x == 1"', out)
        self.assertNotIn("attrs=", out)
        converted = [e for e in log if e["rule_id"] == ATTRS]
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["converted"][0]["line"], 2)
        self.assertEqual(converted[0]["refused"], [])

    def test_flag_off_transform_leaves_attrs_alone(self):
        rules, _ = self.bind(None)
        text = '<form><field name="a" attrs="{\'invisible\': [(\'x\', \'=\', 1)]}"/></form>'
        transform = kr.fixing_transform(rules, ["16-17"])
        self.assertTrue(transform is None or transform("v.xml", text) == text)


class DeduplicateTests(unittest.TestCase):
    def issue(self, category, line, maturity="", auto_fixable=False):
        return legacy_rules.Issue(file="v.xml", line=line, severity="CRITICAL", category=category, message="m",
                                  suggestion="s", auto_fixable=auto_fixable, maturity=maturity)

    def test_handled_experimental_finding_supersedes_the_legacy_duplicate_on_its_line(self):
        issues = [self.issue("Attrs Attribute", 3), self.issue(ATTRS, 3, "DETECT_ONLY", True)]
        kept = kr.deduplicate(issues, {ATTRS, STATES}, {("v.xml", 3, ATTRS)})
        self.assertEqual([i.category for i in kept], [ATTRS])

    def test_without_handled_lines_the_legacy_row_still_wins(self):
        issues = [self.issue("Attrs Attribute", 3), self.issue(ATTRS, 3, "DETECT_ONLY")]
        kept = kr.deduplicate(issues, {ATTRS, STATES})
        self.assertEqual([i.category for i in kept], ["Attrs Attribute"])

    def test_unhandled_experimental_finding_follows_the_ordinary_rule(self):
        # the legacy layer already converted this states=: the experimental rule saw nothing, so legacy stays
        issues = [self.issue("States Attribute", 3, auto_fixable=True), self.issue(STATES, 3, "DETECT_ONLY")]
        kept = kr.deduplicate(issues, {ATTRS, STATES}, {("v.xml", 9, STATES)})
        self.assertEqual([i.category for i in kept], ["States Attribute"])

    def test_other_lines_keep_their_legacy_row(self):
        issues = [self.issue("Attrs Attribute", 4), self.issue(ATTRS, 3, "DETECT_ONLY", True)]
        kept = kr.deduplicate(issues, {ATTRS}, {("v.xml", 3, ATTRS)})
        self.assertEqual(sorted(i.category for i in kept), sorted(["Attrs Attribute", ATTRS]))

    def test_handled_lines_come_from_converted_and_refused_records(self):
        log = [{"rule_id": ATTRS, "path": "v.xml", "converted": [{"line": 2}], "refused": [{"line": 5}]}]
        self.assertEqual(kr.handled_lines(log, "v.xml"), frozenset({("v.xml", 2, ATTRS), ("v.xml", 5, ATTRS)}))
        self.assertEqual(kr.handled_lines([], "v.xml"), frozenset())

if __name__ == "__main__":
    unittest.main()
