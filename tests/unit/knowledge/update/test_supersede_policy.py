"""Semantic supersede policy (feature 012, Wave 3c, owner decision A): which removals a recorded policy may approve.

Releases are real trees with a `write_release_manifest` manifest, so the removals come from `diff_releases` exactly as the
build sees them. A removed generated rule is approved only when the new release carries an equal-semantics rule; a removed
BUILTIN, MANUAL or origin-less rule, a RETIRED rule, and a rule without a replacement are never approved. Removed VERIFIED
evidence is approved only when every parent rule that cites it is itself approved.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.diff import diff_releases
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.update.capability import (DETECT_ONLY, DRAFT, FIX_ENABLED, POLICY_NAME, RETIRED,
                                                   semantic_replacements, semantic_supersede_policy)

META = {
    "label": "policy-test", "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1}, "sources": [], "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32, "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
OLD = "16-17.python_orm.cand-aaaaaaaa"
OLD_B = "16-17.python_orm.cand-bbbbbbbb"
NEW = "16-17.python_orm.cand-cccccccc"
NEW_B = "16-17.python_orm.cand-dddddddd"
EV_OLD = "EV-100"


def _gen(rid, *, maturity=DETECT_ONLY, origin="GENERATED", **extra):
    """A generated-looking rule row. Descriptive text (message, suggestion) is part of every row unless overridden."""
    row = {"id": rid, "step": "16-17", "category": "python_orm", "severity": "INFO", "maturity": maturity,
           "risk": "LOW", "evidence": [], "detector_ref": "pkg.mod:flag", "fixer_ref": None,
           "params": {"subject": "sale.demo.order.get_amount_old"}, "review_required": True, "tests": {},
           "message": f"Candidate for {rid}", "suggestion": "Review"}
    if origin is not None:
        row["origin"] = origin
    row.update(extra)
    return row


def _evidence(eid, status="VERIFIED"):
    return {"id": eid, "status": status, "rule_ids": [], "official": False}


class PolicyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self._n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _release(self, rows, evidence=()) -> Path:
        self._n += 1
        root = self.base / f"rel{self._n}"
        (root / "knowledge" / "compatibility").mkdir(parents=True)
        (root / "knowledge" / "compatibility" / "16-17.rules.json").write_text(json.dumps(rows) + "\n",
                                                                               encoding="utf-8")
        if evidence:
            (root / "knowledge" / "evidence").mkdir(parents=True)
            for record in evidence:
                (root / "knowledge" / "evidence" / f"{record['id']}.json").write_text(json.dumps(record) + "\n",
                                                                                      encoding="utf-8")
        write_release_manifest(root, META)
        return root

    def _decide(self, old_rows, new_rows, old_evidence=(), new_evidence=()):
        parent = self._release(old_rows, old_evidence)
        new = self._release(new_rows, new_evidence)
        diff = diff_releases(parent, new)
        return semantic_supersede_policy()(diff, parent, new)


class ReplacementTests(PolicyTestCase):
    def test_generated_rule_replaced_by_equal_semantics_rule_with_new_id_is_approved(self):
        approved = self._decide([_gen(OLD)], [_gen(NEW, message="Candidate reworded")])
        self.assertEqual(approved, {OLD: f"semantic replacement by {NEW}"})

    def test_policy_name_is_stable_and_pinned(self):
        self.assertEqual(semantic_supersede_policy().policy_name, POLICY_NAME)
        self.assertEqual(POLICY_NAME, "semantic-replacement/1")

    def test_builtin_removed_is_never_approved_even_with_an_equal_replacement(self):
        self.assertEqual(self._decide([_gen(OLD, origin="BUILTIN")], [_gen(NEW)]), {})

    def test_manual_removed_is_never_approved_even_with_an_equal_replacement(self):
        self.assertEqual(self._decide([_gen(OLD, origin="MANUAL")], [_gen(NEW)]), {})

    def test_origin_less_removed_row_is_never_approved(self):
        self.assertEqual(self._decide([_gen(OLD, origin=None)], [_gen(NEW)]), {})

    def test_replacement_with_lower_maturity_is_not_approved(self):
        approved = self._decide([_gen(OLD, maturity=FIX_ENABLED)], [_gen(NEW, maturity=DETECT_ONLY)])
        self.assertEqual(approved, {})

    def test_replacement_with_higher_or_equal_maturity_is_approved(self):
        self.assertEqual(self._decide([_gen(OLD, maturity=DRAFT)], [_gen(NEW, maturity=FIX_ENABLED)]),
                         {OLD: f"semantic replacement by {NEW}"})
        self.assertEqual(self._decide([_gen(OLD, maturity=FIX_ENABLED)], [_gen(NEW, maturity=FIX_ENABLED)]),
                         {OLD: f"semantic replacement by {NEW}"})

    def test_retired_removed_rule_is_never_approved(self):
        self.assertEqual(self._decide([_gen(OLD, maturity=RETIRED)], [_gen(NEW)]), {})

    def test_two_removed_rules_to_one_replacement_approve_only_the_first_by_sorted_id(self):
        approved = self._decide([_gen(OLD), _gen(OLD_B)], [_gen(NEW)])
        self.assertEqual(approved, {OLD: f"semantic replacement by {NEW}"})
        self.assertNotIn(OLD_B, approved)

    def test_two_removed_rules_with_two_replacements_are_both_approved_one_to_one(self):
        approved = self._decide([_gen(OLD), _gen(OLD_B)], [_gen(NEW), _gen(NEW_B)])
        self.assertEqual(approved, {OLD: f"semantic replacement by {NEW}",
                                    OLD_B: f"semantic replacement by {NEW_B}"})

    def test_no_replacement_is_not_approved(self):
        self.assertEqual(self._decide([_gen(OLD)], []), {})

    def test_changed_params_mean_no_equivalent(self):
        other = _gen(NEW, params={"subject": "sale.demo.order.something_else"})
        self.assertEqual(self._decide([_gen(OLD)], [other]), {})

    def test_changed_category_means_no_equivalent(self):
        self.assertEqual(self._decide([_gen(OLD)], [_gen(NEW, category="python_runtime")]), {})

    def test_removed_rule_cannot_serve_as_the_replacement_for_another_removed_rule(self):
        # NEW is equal to OLD but is itself removed: the new release has no replacement for either
        self.assertEqual(self._decide([_gen(OLD), _gen(NEW)], []), {})

    def test_replacement_map_is_exposed_for_callers(self):
        parent, new = self._release([_gen(OLD)]), self._release([_gen(NEW)])
        self.assertEqual(semantic_replacements(parent, new), {OLD: NEW})
        self.assertEqual(semantic_replacements(parent, self._release([_gen(OLD, origin="MANUAL")])), {})


class EvidenceTests(PolicyTestCase):
    def test_removed_verified_evidence_cited_only_by_approved_rule_is_approved(self):
        old = [_gen(OLD, evidence=[EV_OLD])]
        approved = self._decide(old, [_gen(NEW)], old_evidence=[_evidence(EV_OLD)])
        self.assertEqual(approved[EV_OLD], f"evidence of replaced rule(s) {OLD}")
        self.assertEqual(approved[OLD], f"semantic replacement by {NEW}")

    def test_evidence_cited_by_a_surviving_rule_is_not_approved(self):
        survivor = _gen("16-17.python_orm.survivor", evidence=[EV_OLD])
        approved = self._decide([_gen(OLD, evidence=[EV_OLD]), survivor], [_gen(NEW), survivor],
                                old_evidence=[_evidence(EV_OLD)])
        self.assertNotIn(EV_OLD, approved)
        self.assertIn(OLD, approved)

    def test_evidence_cited_by_a_removed_rule_that_is_not_approved_is_not_approved(self):
        approved = self._decide([_gen(OLD, evidence=[EV_OLD], origin="MANUAL")], [_gen(NEW)],
                                old_evidence=[_evidence(EV_OLD)])
        self.assertEqual(approved, {})

    def test_evidence_cited_by_no_parent_rule_is_not_approved(self):
        approved = self._decide([_gen(OLD)], [_gen(NEW)], old_evidence=[_evidence("EV-200")])
        self.assertNotIn("EV-200", approved)

    def test_removed_evidence_cited_by_several_approved_rules_is_approved_with_all_named(self):
        old = [_gen(OLD, evidence=[EV_OLD]), _gen(OLD_B, evidence=[EV_OLD])]
        approved = self._decide(old, [_gen(NEW)], old_evidence=[_evidence(EV_OLD)])
        # OLD_B is the second removed rule for the single replacement: it is not approved, so EV_OLD must not be either
        self.assertNotIn(EV_OLD, approved)
        both = self._decide(old, [_gen(NEW), _gen(NEW_B)], old_evidence=[_evidence(EV_OLD)])
        self.assertEqual(both[EV_OLD], f"evidence of replaced rule(s) {OLD}, {OLD_B}")

    def test_removed_evidence_that_is_not_verified_is_not_a_destructive_entry(self):
        old = [_gen(OLD, evidence=[EV_OLD])]
        approved = self._decide(old, [_gen(NEW)], old_evidence=[_evidence(EV_OLD, status="DOCUMENTED_NOT_TESTED")])
        self.assertNotIn(EV_OLD, approved)


if __name__ == "__main__":
    unittest.main()
