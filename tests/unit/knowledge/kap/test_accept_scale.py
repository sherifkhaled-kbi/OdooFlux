"""RC performance fix: accepting a candidate must not validate, hash or copy the whole change ledger.

A real 16 to 17 ledger holds ~157k entries. `Ledger.mutate` used to schema-validate and hash every entry on each
mutation, and `accept` deep-copied the whole ledger for its dry run, so one accept took about 60 s. Now a mutation is
validated on the one entry it changes (every other entry is unchanged and was valid when it entered the ledger), and
the dry run uses a one-entry ledger. Decisions, refusals and stored bytes are unchanged.
"""

import copy
import unittest
from unittest import mock

from odooflux.knowledge.authoring import ops
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.ledger import ledger as ledger_mod
from odooflux.knowledge.ledger.ledger import Ledger, LedgerError
from tests.unit.knowledge.kap.test_accept import AT, AcceptTests, _draft, _ledger, _tree_bytes

FILLER = 400


def big_ledger(extra_subject="res.partner::field::foo"):
    drafts = [_draft(f"res.partner::field::filler{i}", "field", "REMOVED") for i in range(FILLER)]
    drafts.append(_draft(extra_subject, "field", "REMOVED"))
    return _ledger(drafts)


class LedgerMutateScaleTests(unittest.TestCase):
    def test_a_mutation_validates_only_the_changed_entry(self):
        ledger = big_ledger()
        cid = ledger.records()[7]["change_id"]
        sizes = []
        real = ledger_mod._schema_problems

        def spy(doc):
            sizes.append(len(doc["entries"]))
            return real(doc)

        with mock.patch.object(ledger_mod, "_schema_problems", spy):
            ledger.append_history(cid, actor="MACHINE:test", action="note", from_value=None, to_value="x")
            ledger.mutate(cid, actor="alice", action="confirm", from_value="a", to_value="b", update={"confirmed": True})
        self.assertEqual(sizes, [1, 1])

    def test_an_invalid_update_is_refused_and_changes_nothing(self):
        ledger = big_ledger()
        cid = ledger.records()[3]["change_id"]
        before = ledger.get(cid)
        with self.assertRaises(LedgerError):
            ledger.mutate(cid, actor="alice", action="confirm", from_value="a", to_value="b",
                          update={"confirmed": "yes"})  # the schema wants a boolean
        with self.assertRaises(LedgerError):
            ledger.mutate(cid, actor="alice", action="x", from_value=None, to_value=None, update={"class": "REMOVED"})
        self.assertEqual(ledger.get(cid), before)

    def test_chain_digest_and_verify_stay_consistent_after_many_mutations(self):
        ledger = big_ledger()
        for record in ledger.records()[:25]:
            ledger.append_history(record["change_id"], actor="MACHINE:test", action="note", from_value=None,
                                  to_value="x")
        self.assertEqual(ledger.verify(), [])
        doc = ledger.to_dict()
        reloaded = Ledger(doc["step"], doc["from"], doc["to"], {e["change_id"]: e for e in doc["entries"]})
        self.assertEqual(reloaded.to_dict()["ledger_digest"], doc["ledger_digest"])


class NoBypassTests(unittest.TestCase):
    """Single-entry validation in `mutate` is sound because every other entry entered through `create` or `load` (whole
    document validated) and `save` validates the whole document again: a ledger corrupted outside `mutate` cannot be
    persisted, whatever else was mutated in between."""

    def test_an_entry_corrupted_outside_mutate_never_reaches_disk(self):
        import tempfile
        from pathlib import Path
        ledger = big_ledger()
        a, b = ledger.records()[0]["change_id"], ledger.records()[1]["change_id"]
        ledger._entries[a]["confirmed"] = "not-a-bool"  # tampering that bypasses mutate
        ledger.append_history(b, actor="MACHINE:test", action="note", from_value=None, to_value="x")  # unrelated, valid
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LedgerError):
                ledger.save(Path(tmp) / "l.json")
            self.assertFalse((Path(tmp) / "l.json").exists())

    def test_mutate_still_cannot_change_an_immutable_field_or_a_missing_entry(self):
        ledger = big_ledger()
        with self.assertRaises(LedgerError):
            ledger.mutate("CH-missing", actor="a", action="x", from_value=None, to_value=None)
        with self.assertRaises(LedgerError):
            ledger.mutate(ledger.records()[0]["change_id"], actor="a", action="x", from_value=None, to_value=None,
                          update={"subject_key": "other"})


class AcceptScaleTests(AcceptTests):
    def test_accept_neither_copies_nor_validates_the_whole_ledger(self):
        ledger = big_ledger()
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        sizes, copied = [], []
        real_check, real_copy = ledger_mod._schema_problems, copy.deepcopy

        def spy_check(doc):
            sizes.append(len(doc["entries"]))
            return real_check(doc)

        def spy_copy(obj, *a, **k):
            copied.append(isinstance(obj, Ledger))
            return real_copy(obj, *a, **k)

        with mock.patch.object(ledger_mod, "_schema_problems", spy_check), \
                mock.patch.object(acc.copy, "deepcopy", spy_copy):
            acc.accept(self.tree, candidate, ledger=ledger, evidence=[
                r for r in result["evidence"] if r["id"] in set(candidate["rule"]["evidence"])], author="alice", at=AT)
        self.assertFalse(any(copied), "the dry run copied the whole ledger")
        self.assertTrue(sizes and max(sizes) == 1, sizes)
        self.assertEqual(ledger.get(candidate["change_id"])["disposition"], "RULE_CREATED")
        self.assertEqual(ledger.verify(), [])

    def test_a_dry_run_refusal_still_writes_nothing(self):
        ledger = big_ledger()
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        ev = [r for r in result["evidence"] if r["id"] in set(candidate["rule"]["evidence"])]
        acc.accept(self.tree, candidate, ledger=ledger, evidence=ev, author="alice", at=AT)
        again = copy.deepcopy(candidate)
        again["status"] = "PROPOSED"
        before_tree, before_ledger = _tree_bytes(self.tree), ledger.to_dict()
        with self.assertRaises(acc.AcceptError):
            acc.accept(self.tree, again, ledger=ledger, evidence=ev, author="alice", at=AT)
        self.assertEqual(_tree_bytes(self.tree), before_tree)
        self.assertEqual(ledger.to_dict(), before_ledger)

    def test_a_failure_halfway_leaves_tree_ledger_and_candidate_untouched(self):
        ledger = big_ledger()
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        ev = [r for r in result["evidence"] if r["id"] in set(candidate["rule"]["evidence"])]
        before_tree, before_ledger = _tree_bytes(self.tree), ledger.to_dict()
        with mock.patch.object(ops, "create_rule", side_effect=RuntimeError("disk full")):
            with self.assertRaises(acc.AcceptError):
                acc.accept(self.tree, candidate, ledger=ledger, evidence=ev, author="alice", at=AT)
        self.assertEqual(candidate["status"], "PROPOSED")
        self.assertEqual(_tree_bytes(self.tree), before_tree)
        self.assertEqual(ledger.to_dict(), before_ledger)


if __name__ == "__main__":
    unittest.main()
