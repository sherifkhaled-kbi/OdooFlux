"""Activation decision and recording (feature 012, plan section 5, addendum C3).

Releases here are real: a knowledge tree with a `write_release_manifest` manifest, installed under a kb-home where
needed. The shipped built-in FIX_ENABLED row is copied byte for byte to exercise the byte-identity trust path.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.cli import kap_release
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.store import KbLock, build_pointer, ensure_layout, read_active, set_release_state, \
    utc_now, write_active
from odooflux.knowledge.update import activation
from odooflux.knowledge.update.activation import (CAPABILITY_DOWNGRADED, CAPABILITY_LOST, COMPLETENESS_FAILED,
                                                   ENTERPRISE_COMPAT, FIX_NOT_TRUSTED, INTEGRITY, PARTIAL_WARNING,
                                                   activate_release, block, evaluate)
from odooflux.knowledge.update.history import UpdateHistory
from tests.unit.knowledge.kap import test_certified_fix_trust as ctf

META = {
    "label": "activation-test",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [{"step": "16-17", "completeness": "COMPLETE", "ledger_digest": "ab" * 32}],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
FIRST_SHIPPED_FIX_ROW = next(r for r in load_knowledge(KNOWLEDGE_ROOT).rules if r.get("maturity") == "FIX_ENABLED")


def _row(rid, maturity="DETECT_ONLY", **extra):
    row = {"id": rid, "step": "16-17", "category": "python_runtime", "file_kinds": ["python"], "severity": "WARNING",
           "maturity": maturity, "risk": "LOW", "evidence": [], "detector_ref": "pkg.mod:detect",
           "fixer_ref": None, "params": {"callee": "x"}, "tests": {"positive": "T", "negative": "T",
                                                                  "idempotence": "T"},
           "message": "m", "suggestion": "s"}
    row.update(extra)
    return row


def _manual_fix_row(rid="16-17.python.manual-fix"):
    return _row(rid, "FIX_ENABLED", origin="MANUAL", evidence=[])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / "kb-home"
        self.home.mkdir()
        self._n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _tree(self, rows, name=None, *, state=None) -> Path:
        """Build a release tree with a real manifest under base/<name>. Returns the release directory."""
        self._n += 1
        root = self.base / (name or f"tree{self._n}")
        (root / "knowledge" / "compatibility").mkdir(parents=True)
        (root / "knowledge" / "compatibility" / "16-17.rules.json").write_text(json.dumps(rows) + "\n",
                                                                               encoding="utf-8")
        self._manifest = write_release_manifest(root, META)
        return root

    def _install(self, rows, state=ReleaseState.INSTALLED) -> tuple:
        """Build a release and move it into kb-home/releases/<id>. Returns (release_id, release_dir)."""
        ensure_layout(self.home)
        tree = self._tree(rows, name=f"staged{self._n}")
        rid = self._manifest["release_id"]
        target = self.home / "releases" / rid
        tree.rename(target)
        set_release_state(self.home, rid, state)
        return rid, target


class EvaluateTests(_Base):
    def test_clean_release_is_allowed_with_no_blocking_or_warnings(self):
        prev = self._tree([_row("16-17.python.a")])
        new = self._tree([_row("16-17.python.a"), _row("16-17.python.new")])
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking, ())
        self.assertEqual(decision.warnings, ())
        self.assertEqual(decision.diff["added"], ["16-17.python.new"])

    def test_completeness_failed_blocks_in_isolation(self):
        rows = [_row("16-17.python.a")]
        decision = evaluate(self._tree(rows), self._tree(rows), completeness="FAILED")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.codes, (COMPLETENESS_FAILED,))

    def test_not_covered_is_treated_as_failed_completeness(self):
        rows = [_row("16-17.python.a")]
        decision = evaluate(self._tree(rows), self._tree(rows), completeness="NOT_COVERED")
        self.assertEqual(decision.codes, (COMPLETENESS_FAILED,))

    def test_partial_is_allowed_with_warning(self):
        rows = [_row("16-17.python.a")]
        decision = evaluate(self._tree(rows), self._tree(rows), completeness="PARTIAL")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.blocking, ())
        self.assertIn("incomplete coverage; unsupported transitions remain", PARTIAL_WARNING)
        self.assertEqual(decision.warnings, (PARTIAL_WARNING,))

    def test_partial_with_a_lost_rule_is_not_allowed(self):
        prev = self._tree([_row("16-17.python.a"), _row("16-17.python.b")])
        new = self._tree([_row("16-17.python.a")])
        decision = evaluate(prev, new, completeness="PARTIAL")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.codes, (CAPABILITY_LOST,))

    def test_failed_is_never_allowed_even_when_everything_else_is_clean(self):
        rows = [_row("16-17.python.a")]
        decision = evaluate(self._tree(rows), self._tree(rows), completeness="FAILED")
        self.assertFalse(decision.allowed)

    def test_lost_rule_blocks_in_isolation(self):
        prev = self._tree([_row("16-17.python.a"), _row("16-17.python.b")])
        new = self._tree([_row("16-17.python.a")])
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertEqual(decision.codes, (CAPABILITY_LOST,))
        self.assertIn("16-17.python.b", decision.blocking[0]["detail"])

    def test_downgrade_blocks_in_isolation(self):
        prev = self._tree([_row("16-17.python.a", "DETECT_ONLY")])
        new = self._tree([_row("16-17.python.a", "DRAFT")])
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertEqual(decision.codes, (CAPABILITY_DOWNGRADED,))

    def test_supersede_lets_only_the_named_id_pass(self):
        prev = self._tree([_row("16-17.python.x"), _row("16-17.python.y")])
        new = self._tree([])
        only_x = evaluate(prev, new, completeness="COMPLETE", supersede=("16-17.python.x",))
        self.assertFalse(only_x.allowed)
        self.assertEqual(only_x.codes, (CAPABILITY_LOST,))
        self.assertIn("16-17.python.y", only_x.blocking[0]["detail"])
        self.assertTrue(any("16-17.python.x" in w for w in only_x.warnings))
        both = evaluate(prev, new, completeness="COMPLETE", supersede=("16-17.python.x", "16-17.python.y"))
        self.assertTrue(both.allowed)

    def test_supersede_does_not_clear_fix_not_trusted(self):
        prev = self._tree([])
        new = self._tree([_manual_fix_row("16-17.python.fix")])
        decision = evaluate(prev, new, completeness="COMPLETE", supersede=("16-17.python.fix",))
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))

    def test_enterprise_compat_blocks_in_isolation(self):
        rows = [_row("16-17.python.a")]
        decision = evaluate(self._tree(rows), self._tree(rows), completeness="COMPLETE",
                            carried_inventory_findings=[{"module": "ent_sale", "missing": ["ent_base"]}])
        self.assertEqual(decision.codes, (ENTERPRISE_COMPAT,))
        self.assertIn("ent_sale", decision.blocking[0]["detail"])

    def test_integrity_failure_blocks_in_isolation(self):
        rows = [_row("16-17.python.a")]
        prev = self._tree(rows)
        new = self._tree(rows)
        (new / "notes.txt").write_text("added after the manifest was written\n", encoding="utf-8")
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertEqual(decision.codes, (INTEGRITY,))
        self.assertIn("notes.txt", decision.blocking[0]["detail"])

    def test_release_not_installed_under_kb_home_blocks_in_isolation(self):
        rows = [_row("16-17.python.a")]
        prev = self._tree(rows)
        new = self._tree(rows)  # no state.json: STAGED, not loadable
        decision = evaluate(prev, new, completeness="COMPLETE", kb_home=self.home)
        self.assertEqual(decision.codes, (INTEGRITY,))
        self.assertIn("STAGED", decision.blocking[0]["detail"])

    def test_changed_detect_only_rule_warns_without_blocking(self):
        prev = self._tree([_row("16-17.python.a", detector_ref="pkg.mod:old")])
        new = self._tree([_row("16-17.python.a", detector_ref="pkg.mod:new")])
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertTrue(decision.allowed)
        self.assertEqual(len(decision.warnings), 1)
        self.assertIn("16-17.python.a", decision.warnings[0])
        self.assertIn("detector_ref", decision.warnings[0])

    def test_non_builtin_fix_enabled_row_without_certification_is_not_trusted(self):
        decision = evaluate(None, self._tree([_manual_fix_row()]), completeness="COMPLETE")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))
        self.assertIn("16-17.python.manual-fix", decision.blocking[0]["detail"])

    def test_byte_identical_shipped_fix_enabled_row_is_trusted(self):
        shipped = copy.deepcopy(FIRST_SHIPPED_FIX_ROW)
        prev = self._tree([shipped])
        new = self._tree([shipped])
        decision = evaluate(prev, new, completeness="COMPLETE")
        self.assertTrue(decision.allowed, decision.to_dict())
        self.assertEqual(decision.codes, ())

    def test_modified_shipped_fix_enabled_row_is_not_trusted(self):
        tampered = copy.deepcopy(FIRST_SHIPPED_FIX_ROW)
        tampered["params"] = dict(tampered["params"], new_value="jsonrpc-modified")
        decision = evaluate(None, self._tree([tampered]), completeness="COMPLETE")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))

    def test_changed_previously_fix_enabled_row_must_pass_the_same_test(self):
        shipped = copy.deepcopy(FIRST_SHIPPED_FIX_ROW)
        changed = copy.deepcopy(shipped)
        changed["params"] = dict(changed["params"], new_value="jsonrpc-modified")
        decision = evaluate(self._tree([shipped]), self._tree([changed]), completeness="COMPLETE")
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))
        self.assertEqual(decision.diff["changed"], [{"id": shipped["id"], "fields": ["detector_params",
                                                                                   "fixer_params"]}])

    def test_decision_to_dict_shape(self):
        rows = [_row("16-17.python.a")]
        data = evaluate(self._tree(rows), self._tree(rows), completeness="PARTIAL").to_dict()
        self.assertEqual(set(data), {"allowed", "blocking", "warnings", "diff"})
        self.assertEqual(data["diff"]["unchanged"], 1)


class ActivateTests(_Base):
    def setUp(self):
        super().setUp()
        self.prev_id, self.prev_dir = self._install([_row("16-17.python.a")], ReleaseState.ACTIVE)
        with KbLock(self.home):
            write_active(self.home, build_pointer(None, self.prev_id, self._digest(self.prev_dir), utc_now()))
        self.new_id, self.new_dir = self._install([_row("16-17.python.a"), _row("16-17.python.b")])
        self.history = UpdateHistory(self.home)

    def _digest(self, release_dir) -> str:
        return json.loads((release_dir / "release.json").read_text(encoding="utf-8"))["release_digest"]

    def _active(self):
        return read_active(self.home)["release_id"]

    def test_success_swaps_pointer_and_records_active(self):
        result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id,
                                  fingerprint="a" * 64, source_revisions={"community": "b" * 40},
                                  build_inputs={"plan": "x"})
        self.assertEqual(result["state"], "ACTIVE")
        self.assertIsNone(result["history_error"])
        self.assertEqual(self._active(), self.new_id)
        self.assertEqual(read_active(self.home)["previous"][0]["release_id"], self.prev_id)
        entry = self.history.read(limit=1)[0]
        self.assertEqual(entry["outcome"], "ACTIVE")
        self.assertEqual(entry["new_release"], self.new_id)
        self.assertEqual(entry["details"], {"build_inputs": {"plan": "x"}})
        self.assertEqual(self.history.verify(), (True, []))

    def test_fault_at_audit_keeps_previous_active_and_records_rolled_back(self):
        result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id,
                                  fault_at="audit")
        self.assertEqual(result["state"], "ROLLED_BACK")
        self.assertIn("injected fault", result["reason"])
        self.assertEqual(self._active(), self.prev_id)
        entry = self.history.read(limit=1)[0]
        self.assertEqual(entry["outcome"], "ROLLED_BACK")
        self.assertEqual(self.history.verify(), (True, []))

    def test_fault_at_pointer_keeps_previous_active(self):
        result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id,
                                  fault_at="pointer")
        self.assertEqual(result["state"], "ROLLED_BACK")
        self.assertEqual(self._active(), self.prev_id)

    def test_fault_at_verify_keeps_previous_active(self):
        result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id,
                                  fault_at="verify")
        self.assertEqual(result["state"], "ROLLED_BACK")
        self.assertEqual(self._active(), self.prev_id)

    def test_unreadable_pointer_after_failure_is_recorded_failed(self):
        with mock.patch.object(kap_release, "activate", side_effect=RuntimeError("boom")), \
                mock.patch.object(activation, "read_active", side_effect=RuntimeError("unreadable")):
            result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id)
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(self.history.read(limit=1)[0]["outcome"], "FAILED")

    def test_blocked_decision_appends_blocked_and_leaves_pointer_alone(self):
        before = (self.home / "active.json").read_bytes()
        decision = evaluate(self.prev_dir, self.new_dir, completeness="FAILED")
        entry = block(self.history, decision, previous_release=self.prev_id, new_release=self.new_id,
                      fingerprint="c" * 64, source_revisions={})
        self.assertEqual(entry["outcome"], "BLOCKED")
        self.assertIn(COMPLETENESS_FAILED, entry["reason"])
        self.assertEqual((self.home / "active.json").read_bytes(), before)
        self.assertEqual(self._active(), self.prev_id)
        self.assertEqual(self.history.verify(), (True, []))

    def test_block_refuses_an_allowed_decision(self):
        decision = evaluate(self.prev_dir, self.new_dir, completeness="COMPLETE")
        self.assertTrue(decision.allowed)
        with self.assertRaises(ValueError):
            block(self.history, decision, previous_release=self.prev_id, new_release=self.new_id)

    def test_evaluate_then_activate_over_installed_releases(self):
        decision = evaluate(self.prev_dir, self.new_dir, completeness="COMPLETE", kb_home=self.home)
        self.assertTrue(decision.allowed, decision.to_dict())
        result = activate_release(self.home, self.new_id, history=self.history, previous_release=self.prev_id,
                                  fingerprint=None, source_revisions={})
        self.assertEqual(result["state"], "ACTIVE")
        self.assertEqual(self._active(), self.new_id)
        outcomes = [entry["outcome"] for entry in reversed(self.history.read())]
        self.assertEqual(outcomes, ["ACTIVE"])
        self.assertEqual(self.history.verify(), (True, []))



class CertifiedFixActivationTests(ctf.ComposedTestCase):
    """An automatically certified FIX_ENABLED row is trusted at activation only while its record verifies (Wave 3c)."""

    def _release(self, name, rules, evidence, record=None) -> Path:
        tree = ctf.write_tree(self.base / name, rules, evidence)
        if record is not None:
            ctf.store_record(tree, ctf.RULE_ID, record)
        write_release_manifest(self.base / name, META)
        return self.base / name

    def test_auto_certified_row_with_a_valid_record_is_trusted_at_activation(self):
        # CHANGED (review item 3): a certified fixer runs L2 wherever a blob store exists. With no blob store and no prior
        # verified build the row is refused (L1 only is not enough); the record itself still verifies (no cert-* code).
        evidence = [ctf.make_evidence()]
        record = ctf.certify(ctf.make_row(), evidence)
        new = self._release("valid", [ctf.make_row()], evidence, record)
        decision = evaluate(None, new, completeness="COMPLETE")
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,), decision.to_dict())
        self.assertIn("confirmation-l2-unavailable", decision.blocking[0]["detail"])
        self.assertNotIn("cert-verify-failed", decision.blocking[0]["detail"])

    def test_auto_certified_row_with_a_tampered_record_is_fix_not_trusted(self):
        evidence = [ctf.make_evidence()]
        record = ctf.certify(ctf.make_row(), evidence)
        record["outputs"]["positive_output_digest"] = "0" * 64  # stored digest changed, record not re-issued
        new = self._release("tampered", [ctf.make_row()], evidence, record)
        decision = evaluate(None, new, completeness="COMPLETE")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))
        self.assertIn(ctf.RULE_ID, decision.blocking[0]["detail"])
        self.assertIn("cert-verify-failed", decision.blocking[0]["detail"])

    def test_auto_certified_row_without_its_record_is_fix_not_trusted(self):
        evidence = [ctf.make_evidence()]
        approval = "auto-cert:1:" + "a" * 64
        new = self._release("norecord", [ctf.make_row(approval=approval)], evidence)
        decision = evaluate(None, new, completeness="COMPLETE")
        self.assertEqual(decision.codes, (FIX_NOT_TRUSTED,))


if __name__ == "__main__":
    unittest.main()
