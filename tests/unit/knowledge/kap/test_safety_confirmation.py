"""Feature 012, Addendum F2/F3: the change class of a certified row is DERIVED from a verified machine confirmation.

`safety.confirmed_class` runs L1 (`machine_confirmation.verify`) on the release's `confirmations/<rule_id>.json`; it never
reads the record's own `change_class`. `safety.source_problems` is L2 (the blobs re-prove to the same witness). Synthetic
records only; the real verifier is exercised here, and the verdict is patched only where a test says so.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.release import safety
from odooflux.knowledge.update import machine_confirmation as mc

RULE_ID = "16-17.python_orm.fix-abcdef12"
EVIDENCE = {"id": "EV-001", "official": True, "rule_ids": [RULE_ID]}


def _rule(**changes):
    row = {"id": RULE_ID, "step": "16-17", "category": "python_orm", "severity": "WARNING",
           "maturity": "FIX_ENABLED", "review_required": False, "risk": "MEDIUM", "origin": "GENERATED",
           "evidence": ["EV-001"], "detector_ref": "odooflux.rules.python.certified:flag_imported_symbol",
           "fixer_ref": "odooflux.rules.python.certified:rewrite_imported_symbol",
           "params": {"module": "odoo.tools.helpers", "old": "old_round", "new": "new_round"}, "tests": {},
           "message": "m", "suggestion": "s", "rev": 2}
    row.update(changes)
    return row


class ConfirmedClassTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name) / "release" / "knowledge"
        (self.tree / "confirmations").mkdir(parents=True)
        self.kb = SimpleNamespace(evidence={"EV-001": EVIDENCE})

    def _write(self, text, rule_id=RULE_ID):
        (self.tree / "confirmations" / f"{rule_id}.json").write_text(text, encoding="utf-8")

    def _confirmed(self, rule=None):
        return safety.confirmed_class(rule or _rule(), self.tree, self.kb, None, None)

    def test_no_confirmation_establishes_no_class(self):
        change_class, findings = self._confirmed()
        self.assertIsNone(change_class)
        self.assertEqual([f["code"] for f in findings], [safety.CONFIRMATION_MISSING])

    def test_an_id_that_cannot_name_a_file_establishes_nothing(self):
        self.assertIsNone(safety.confirmation_path(self.tree, "../escape"))
        change_class, findings = safety.confirmed_class(_rule(id="../escape"), self.tree, self.kb, None, None)
        self.assertIsNone(change_class)
        self.assertEqual([f["code"] for f in findings], [safety.CONFIRMATION_MISSING])

    def test_unreadable_or_non_object_confirmation_is_refused(self):
        self._write("{not json")
        self.assertEqual([f["code"] for f in self._confirmed()[1]], [safety.CONFIRMATION_UNREADABLE])
        self._write("[]")
        self.assertEqual([f["code"] for f in self._confirmed()[1]], [safety.CONFIRMATION_UNREADABLE])

    def test_a_confirmation_that_does_not_verify_establishes_no_class(self):
        self._write(json.dumps({"schema": "odooflux.machine-confirmation/1", "change_class": "REPLACEMENT_CONFIRMED"}))
        change_class, findings = self._confirmed()
        self.assertIsNone(change_class)
        self.assertEqual([f["code"] for f in findings], [safety.CONFIRMATION_INVALID])

    def test_the_class_is_the_derived_one_never_the_records_own(self):
        # The record declares REMOVED; the verifier derives DELEGATING_ALIAS from the witness. Trust uses the derived one.
        self._write(json.dumps({"schema": mc.RECORD_SCHEMA, "change_class": "REMOVED"}))
        verdict = mc.Verdict(True, "DELEGATING_ALIAS", [])
        with mock.patch.object(mc, "verify", return_value=verdict) as verify:
            change_class, findings = self._confirmed()
        self.assertEqual((change_class, findings), ("DELEGATING_ALIAS", []))
        self.assertEqual(verify.call_args.kwargs["rule_row"]["id"], RULE_ID)
        self.assertIsNone(verify.call_args.kwargs.get("ledger_entry"))  # the release ships no ledger


class SourceProblemsTests(unittest.TestCase):
    """L2 (build step 9 and update pre-activation): the blobs of a confirmation must be in the blob store and re-prove."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.tree = self.base / "release" / "knowledge"
        (self.tree / "confirmations").mkdir(parents=True)
        self.store = self.base / "store"
        self.store.mkdir()

    def _confirmation(self, sources):
        record = {"schema": mc.RECORD_SCHEMA, "rule_id": RULE_ID, "sources": sources}
        (self.tree / "confirmations" / f"{RULE_ID}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_no_confirmation_has_nothing_to_re_prove(self):
        self.assertEqual(safety.source_problems(self.tree, RULE_ID, self.store)[0][0], "confirmation-missing")

    def test_a_confirmation_without_sources_is_unreadable(self):
        (self.tree / "confirmations" / f"{RULE_ID}.json").write_text('{"schema": "x"}', encoding="utf-8")
        self.assertEqual(safety.source_problems(self.tree, RULE_ID, self.store)[0][0], "confirmation-unreadable")

    def test_a_missing_blob_is_a_problem(self):
        self._confirmation([{"side": "to", "blob_sha256": "a" * 64}])
        problems = safety.source_problems(self.tree, RULE_ID, self.store)
        self.assertEqual(problems, [("blob-missing", "to blob is not in the blob store")])

    def test_a_present_blob_is_re_proved_against_the_witness(self):
        digest = BlobStore(self.store).put(b"def old_round(x):\n    return x\n")
        self._confirmation([{"side": "to", "blob_sha256": digest}])
        verdict = mc.Verdict(False, None, [("reprove", "S1_GLOBAL_REF")])
        with mock.patch.object(mc, "verify_sources", return_value=verdict):
            self.assertEqual(safety.source_problems(self.tree, RULE_ID, self.store), [("reprove", "S1_GLOBAL_REF")])
        with mock.patch.object(mc, "verify_sources", return_value=mc.Verdict(True, "REMOVED", [])):
            self.assertEqual(safety.source_problems(self.tree, RULE_ID, self.store), [])


if __name__ == "__main__":
    unittest.main()
