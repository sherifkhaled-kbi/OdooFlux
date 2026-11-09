"""Feature 012, Addendum F3: the automatic FIX prover and certifier (`knowledge/autofix.py`), with synthetic inputs.

`prove_entry` refuses an unsound or unevidenced pair with a coded reason and never proposes an AI pair; `plan_pair` offers
only the eligible classes; the bound fixer and detector names are the ones the certified fix templates bind; certification
refuses a row that is not a pending FIX rule. Synthetic only: the texts are invented and the blobs live in a temp store.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import autofix
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from tests.unit.knowledge.kap.test_accept import AT, DATA_DIRS, _draft, _ledger

HELPERS_FROM = '''"""From."""


def old_round(value):
    """Round to two places."""
    return round(value, 2)
'''
HELPERS_TO = '''"""To."""


def new_round(value):
    """Round to two places. Replaces ``old_round``."""
    return round(value, 2)
'''
PATH = "odoo/tools/helpers.py"
REVISION = "a" * 40
STEP = "16-17"


class ProverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.store = self.base / "store"
        self.store.mkdir()
        store = BlobStore(self.store)
        self.from_digest = store.put(HELPERS_FROM.encode("utf-8"))
        self.to_digest = store.put(HELPERS_TO.encode("utf-8"))
        source = {"source_id": "odoo-community-17.0", "official": True, "url": f"https://github.com/odoo/odoo/tree/{REVISION}",
                  "repository": "odoo/odoo", "revision": REVISION, "branch": "17.0"}
        self.sides = {
            "from": {"source_id": "odoo-community-16.0", "snapshot_id": "ss-000000000001", "revision": REVISION,
                     "verified": True, "official": True, "entries": {PATH: self.from_digest}, "source": source},
            "to": {"source_id": "odoo-community-17.0", "snapshot_id": "ss-000000000002", "revision": REVISION,
                   "verified": True, "official": True, "entries": {PATH: self.to_digest}, "source": source},
        }
        self.inputs = autofix.ProofInputs(tree=self.base / "tree", store=self.store, sides=self.sides,
                                          checked_on="2026-11-09", reserved=frozenset())

    def _entry(self, **changes):
        entry = {"change_id": "CH-0000000000000001", "step": STEP, "domain": "python_orm", "kind": "function",
                 "subject_key": "odoo.old_round", "class": "REPLACEMENT_CANDIDATE",
                 "detail": {"from": "odoo.old_round", "to": "odoo.new_round", "source": "docs"},
                 "locations": [{"snapshot_id": "ss-000000000001", "path": PATH, "sha256": self.from_digest, "line": 4},
                               {"snapshot_id": "ss-000000000002", "path": PATH, "sha256": self.to_digest, "line": 4}],
                 "proposed_by": "DETERMINISTIC", "confirmed": False, "disposition": "UNRESOLVED",
                 "disposition_data": {}, "history": []}
        entry.update(changes)
        return entry

    def _refusal(self, entry, inputs=None):
        with self.assertRaises(autofix.Refusal) as raised:
            autofix.prove_entry(entry, inputs or self.inputs)
        return raised.exception.code

    def test_a_documented_identical_replacement_is_proven(self):
        out = autofix.prove_entry(self._entry(), self.inputs)
        self.assertEqual(out["confirmation"]["derived_class"], "REPLACEMENT_CONFIRMED")
        self.assertEqual(out["candidate"]["rule"]["params"], {"module": "odoo.tools.helpers", "old": "old_round",
                                                              "new": "new_round"})
        self.assertEqual(out["candidate"]["rule"]["maturity"], "DETECT_ONLY")
        self.assertIsNone(out["candidate"]["rule"]["fixer_ref"])
        self.assertEqual(out["evidence"]["id"], out["candidate"]["rule"]["evidence"][0])

    def test_an_ai_proposed_pair_is_never_proven(self):
        self.assertEqual(self._refusal(self._entry(proposed_by="AI_PROPOSED")), "ENTRY_PROPOSER")

    def test_a_confirmed_entry_is_never_proven(self):
        self.assertEqual(self._refusal(self._entry(confirmed=True)), "ENTRY_CONFIRMED")

    def test_an_unverified_source_is_never_proven(self):
        self.sides["to"]["verified"] = False
        self.assertEqual(self._refusal(self._entry()), "SOURCE_NOT_PINNED")

    def test_an_unpinned_revision_is_never_proven(self):
        self.sides["from"]["revision"] = "main"
        self.assertEqual(self._refusal(self._entry()), "SOURCE_NOT_PINNED")

    def test_a_pair_without_a_store_is_refused(self):
        self.assertEqual(self._refusal(self._entry(), autofix.ProofInputs(tree=self.base, store=None, sides=self.sides,
                                                                           checked_on="", reserved=frozenset())),
                         "NO_STORE")

    def test_a_blob_missing_from_the_store_is_refused(self):
        self.sides["to"]["entries"] = {PATH: "b" * 64}  # a digest the store does not hold
        self.assertEqual(self._refusal(self._entry()), "BLOB_MISSING")

    def test_a_replacement_without_a_docs_hint_is_not_a_replacement(self):
        entry = self._entry(detail={"from": "odoo.old_round", "to": "odoo.new_round", "source": "similarity"})
        self.assertEqual(self._refusal(entry), "LEDGER_SOURCE")

    def test_a_changed_name_pair_is_refused(self):
        # The ledger names a symbol the new source does not bind: the proof refuses it (no name is guessed).
        entry = self._entry(detail={"from": "odoo.old_round", "to": "odoo.other_round", "source": "docs"})
        self.assertEqual(self._refusal(entry), "BINDING_CONFLICT")

    def test_a_method_is_out_of_scope(self):
        self.assertEqual(self._refusal(self._entry(kind="method")), "ENTRY_SUBJECT")

    def test_a_refused_pair_writes_nothing_and_its_error_is_coded(self):
        before = _tree_bytes(self.base)
        self.assertEqual(self._refusal(self._entry(detail={})), "ENTRY_NAMES")
        self.assertEqual(_tree_bytes(self.base), before)


class PlanPairTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = Path(self._tmp.name) / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")

    def test_only_the_eligible_classes_are_offered_to_the_prover(self):
        ledger = _ledger([_draft("res.partner::field::alpha", "field", "REMOVED"),
                          _draft("res.partner::field::gamma", "field", "ADDED")])
        offered = []

        def prover(record, inputs):
            offered.append(record["class"])
            raise autofix.Refusal("NOT_PROVEN", "fixture")

        out = autofix.plan_pair(ledger, self.tree, prove=prover, store=None, author="alice", at=AT)
        self.assertEqual(offered, ["REMOVED"])
        self.assertEqual([r["code"] for r in out["refused"]], ["NOT_PROVEN"])

    def test_a_prover_fault_refuses_one_change_only(self):
        ledger = _ledger([_draft("res.partner::field::alpha", "field", "REMOVED")])

        def prover(record, inputs):
            raise RuntimeError("boom")

        out = autofix.plan_pair(ledger, self.tree, prove=prover, store=None, author="alice", at=AT)
        self.assertEqual(out["accepted"], [])
        self.assertEqual([r["code"] for r in out["refused"]], [autofix.PROVER_FAULT])


class BindingTests(unittest.TestCase):
    def test_the_bound_fixers_and_detectors_are_the_certified_template_names(self):
        from odooflux.transformers import fix_templates as ft
        rewrite = ft.template("python.rewrite_imported_symbol")
        remove = ft.template("python.remove_imported_decorator")
        for derived in ("REPLACEMENT_CONFIRMED", "DELEGATING_ALIAS"):
            detector, fixer = autofix.RULE_BINDING[derived]
            self.assertEqual(fixer, rewrite.fixer_ref)
            self.assertIn(detector, rewrite.detector_refs)
        detector, fixer = autofix.RULE_BINDING["IDENTITY_DECORATOR_REMOVED"]
        self.assertEqual(fixer, remove.fixer_ref)
        self.assertIn(detector, remove.detector_refs)

    def test_the_prover_is_named_for_the_build_fingerprint(self):
        self.assertEqual(autofix.prove_entry.policy_name, "machine-confirmation/1")


class CertifyRowTests(unittest.TestCase):
    def test_a_row_that_is_not_a_pending_fix_rule_is_never_certified(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "knowledge"
            tree.mkdir()
            with self.assertRaises(autofix.Refusal) as raised:
                autofix.certify_row(tree, "16-17.python_orm.fix-00000000", blob_root=None, author="a", at=AT)
            self.assertEqual(raised.exception.code, "RULE_MISSING")


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


if __name__ == "__main__":
    unittest.main()
