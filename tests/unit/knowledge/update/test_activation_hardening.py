"""Feature 012 hardening (review item 3): activation runs L2 wherever a machine confirmation or a certified fixer is in play.

L2 (`safety.source_problems`) re-proves the retained blobs of a machine confirmation. Before the fix it ran only for a
GENERATED row with an approval, so a MANUAL row bound to a certified fixer (or carrying a confirmation file) skipped it.
Without a blob store L2 cannot run; the conservative choice is to refuse such a rule, not to accept it on L1 alone.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.update import activation
from tests.unit.knowledge.kap import test_certified_fix_trust as base

RULE_ID = base.RULE_ID
FIX_IDS = {RULE_ID}


class ActivationL2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        base.composition_root.build_context()

    def tearDown(self):
        self._tmp.cleanup()

    def release(self, name, row, *, confirmation=None):
        """A release directory `<root>/<name>` whose knowledge tree holds `row` (and a confirmation when given)."""
        new_dir = self.root / name
        tree = base.write_tree(new_dir, [row], [base.make_evidence()])
        if confirmation is not None:
            path = tree / "confirmations" / f"{RULE_ID}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(confirmation), encoding="utf-8")
        return new_dir

    def test_certified_fixer_without_a_blob_store_is_refused_not_accepted_on_l1_alone(self):
        new_dir = self.release("no-blobs", base.make_row())
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])):
            problems = activation._fix_rule_problems(new_dir, FIX_IDS, blob_root=None)
        self.assertEqual([rid for rid, _ in problems], [RULE_ID])
        self.assertIn("L1 only", problems[0][1])

    def test_a_manual_row_with_a_confirmation_file_runs_l2(self):
        # origin MANUAL and no approval: the old condition (GENERATED + approval) skipped L2 here
        new_dir = self.release("confirmed", base.make_row(), confirmation={"schema": "x"})
        store = self.root / "store"
        store.mkdir()
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])), \
                mock.patch.object(activation.safety, "source_problems",
                                  return_value=[("blob-missing", "from blob is not in the blob store")]) as l2:
            problems = activation._fix_rule_problems(new_dir, FIX_IDS, blob_root=store)
        l2.assert_called_once()
        self.assertEqual(problems, [(RULE_ID, "blob-missing: from blob is not in the blob store")])

    def test_a_certified_fixer_runs_l2_even_without_a_confirmation_file(self):
        new_dir = self.release("certified", base.make_row())
        store = self.root / "store2"
        store.mkdir()
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])), \
                mock.patch.object(activation.safety, "source_problems", return_value=[]) as l2:
            self.assertEqual(activation._fix_rule_problems(new_dir, FIX_IDS, blob_root=store), [])
        l2.assert_called_once()

    def test_a_rule_already_activated_from_this_kb_is_accepted_without_a_blob_store(self):
        # the previous installed release carries the same row and the same record bytes: a prior verified build
        row = base.make_row()
        evidence = [base.make_evidence()]
        record = base.certify(row, evidence)
        prev = self.release("prev-same", row)
        base.store_record(prev / "knowledge", RULE_ID, record)
        new = self.release("new-same", row)
        base.store_record(new / "knowledge", RULE_ID, record)
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])):
            self.assertEqual(activation._fix_rule_problems(new, FIX_IDS, blob_root=None, prev_dir=prev), [])

    def test_a_different_previous_row_is_not_prior_verified_provenance(self):
        row = base.make_row()
        evidence = [base.make_evidence()]
        record = base.certify(row, evidence)
        prev = self.release("prev-other", base.make_row(message="changed"))
        base.store_record(prev / "knowledge", RULE_ID, record)
        new = self.release("new-other", row)
        base.store_record(new / "knowledge", RULE_ID, record)
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])):
            problems = activation._fix_rule_problems(new, FIX_IDS, blob_root=None, prev_dir=prev)
        self.assertEqual([rid for rid, _ in problems], [RULE_ID])

    def test_a_plain_manual_row_with_no_certified_refs_and_no_blob_store_is_unchanged(self):
        row = base.make_row(fixer_ref="odooflux.rules.python.other:fix", detector_ref="odooflux.rules.python.other:d")
        new_dir = self.release("plain", row)
        with mock.patch.object(activation, "fix_row_trusted", return_value=(True, [])):
            self.assertEqual(activation._fix_rule_problems(new_dir, FIX_IDS, blob_root=None), [])


if __name__ == "__main__":
    unittest.main()
