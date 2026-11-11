"""Effective maturity at read time (AF-3, owner decision AD-02).

FIX_ENABLED means executable availability: a DETECT_ONLY row whose experimental registry entry is offered for its step
and binds with a fixer reads as FIX_ENABLED. The stored row is never changed (no certification is fabricated and no
historical metadata is rewritten). DRAFT and RETIRED rows never execute, so they never change.
"""

import copy
import unittest

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.orchestrator import knowledge_rules as kr
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.experimental import registry

ATTRS = "16-17.xml.attrs-removed"
STATES = "16-17.xml.states-attribute-removed"
PLAIN_DETECT = "16-17.xml.act-window-tag"  # DETECT_ONLY with no registry entry
ROWS = load_knowledge().rules
ROW = {r["id"]: r for r in ROWS}
EXPERIMENTAL = kr.ExperimentalFixers(entries=registry.ENTRIES, modules=registry.MODULES)


def row(rule_id, **changes):
    return {**copy.deepcopy(ROW[rule_id]), **changes}


class RegistryStepTests(unittest.TestCase):
    def test_every_registry_entry_declares_the_step_it_converts(self):
        for rule_id, entry in registry.ENTRIES.items():
            with self.subTest(rule_id):
                self.assertEqual(entry.step, "16-17")
                self.assertEqual(ROW[rule_id]["step"], entry.step)


class EffectiveMaturityTests(unittest.TestCase):
    def test_bound_registry_entry_reads_fix_enabled(self):
        for rule_id in (ATTRS, STATES):
            with self.subTest(rule_id):
                self.assertEqual(ROW[rule_id]["maturity"], "DETECT_ONLY")
                self.assertEqual(kr.effective_maturity(row(rule_id), BINDABLE_MODULES, EXPERIMENTAL), "FIX_ENABLED")

    def test_effective_maturity_does_not_change_the_stored_row(self):
        stored = row(ATTRS)
        self.assertEqual(kr.effective_maturity(stored, BINDABLE_MODULES, EXPERIMENTAL), "FIX_ENABLED")
        self.assertEqual(stored, ROW[ATTRS])
        self.assertEqual(stored["maturity"], "DETECT_ONLY")

    def test_detect_only_row_without_a_registry_entry_stays_detect_only(self):
        self.assertNotIn(PLAIN_DETECT, registry.ENTRIES)
        self.assertEqual(kr.effective_maturity(row(PLAIN_DETECT), BINDABLE_MODULES, EXPERIMENTAL), "DETECT_ONLY")

    def test_without_a_registry_the_stored_maturity_is_used(self):
        self.assertEqual(kr.effective_maturity(row(ATTRS), BINDABLE_MODULES, None), "DETECT_ONLY")

    def test_draft_row_never_executes_even_with_a_registry_entry(self):
        self.assertEqual(kr.effective_maturity(row(ATTRS, maturity="DRAFT"), BINDABLE_MODULES, EXPERIMENTAL),
                         "DRAFT")

    def test_retired_row_stays_retired(self):
        self.assertEqual(kr.effective_maturity(row(ATTRS, maturity="RETIRED"), BINDABLE_MODULES, EXPERIMENTAL),
                         "RETIRED")

    def test_entry_is_not_offered_to_a_row_of_another_step(self):
        self.assertEqual(kr.effective_maturity(row(ATTRS, step="17-18"), BINDABLE_MODULES, EXPERIMENTAL),
                         "DETECT_ONLY")

    def test_review_required_row_is_not_promoted(self):
        self.assertEqual(kr.effective_maturity(row(ATTRS, review_required=True), BINDABLE_MODULES, EXPERIMENTAL),
                         "DETECT_ONLY")

    def test_row_that_does_not_bind_stays_detect_only(self):
        broken = row(ATTRS, detector_ref="odooflux.rules.xml.generic:no_such_function")
        self.assertEqual(kr.effective_maturity(broken, BINDABLE_MODULES, EXPERIMENTAL), "DETECT_ONLY")

    def test_effective_count_agrees_with_the_binder(self):
        rules, _ = kr.bind_knowledge_rules(ROWS, BINDABLE_MODULES, {}, ["16-17"], EXPERIMENTAL)
        bound = {r.key for r in rules if r.experimental and r.fixes}
        promoted = {r["id"] for r in ROWS if r["maturity"] == "DETECT_ONLY" and r["step"] == "16-17"
                    and kr.effective_maturity(r, BINDABLE_MODULES, EXPERIMENTAL) == "FIX_ENABLED"}
        self.assertEqual(promoted, bound)
        self.assertEqual(promoted, {ATTRS, STATES})


if __name__ == "__main__":
    unittest.main()
