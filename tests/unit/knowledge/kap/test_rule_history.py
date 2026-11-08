"""TST-011-021 (REQ-KAP-021): rule history sidecar keeps the creator, appends only, and detects chain tampering.

Sidecars live at `<tree>/history/rules/<rule-id>.json`; each entry hashes the previous one (see contract
manual-rule-cli, Preservation, and data-model RuleHistory).
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.release.canonical import canonical_bytes

RULE_ID = "17-18.manual.example-check"
SHA_A = "a" * 64
SHA_B = "b" * 64


class RuleHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _create(self, actor="alice", at="2026-11-08T10:00:00Z"):
        return h.create_history(self.tree, RULE_ID, actor=actor, at=at, rule_sha256=SHA_A,
                                summary="created", validation_status="NOT_RUN")

    def _edit(self, actor="bob", at="2026-11-08T11:00:00Z", sha=SHA_B):
        return h.append_entry(self.tree, RULE_ID, actor=actor, at=at, action="edit", rule_sha256=sha,
                              summary="edited", validation_status="PASSED")

    def _path(self) -> Path:
        return self.tree / "history" / "rules" / f"{RULE_ID}.json"

    def test_creator_preserved(self):
        self._create(actor="alice", at="2026-11-08T10:00:00Z")
        self._edit(actor="bob", at="2026-11-08T11:00:00Z")
        doc = h.load_history(self.tree, RULE_ID)
        self.assertEqual(doc["created_by"], "alice")
        self.assertEqual(doc["created_at"], "2026-11-08T10:00:00Z")
        self.assertEqual(doc["entries"][0]["actor"], "alice")
        self.assertEqual(doc["entries"][1]["actor"], "bob")
        self.assertEqual([e["rev"] for e in doc["entries"]], [1, 2])
        self.assertIsNone(doc["entries"][0]["prev_hash"])
        self.assertEqual(doc["entries"][1]["prev_hash"], h.entry_hash(doc["entries"][0]))

    def test_chain_tamper_detected(self):
        self._create()
        self._edit()
        self._edit(actor="carol", at="2026-11-08T12:00:00Z")
        original = json.loads(self._path().read_text(encoding="utf-8"))

        def mutate(doc, step):
            step(doc)
            return doc

        cases = {
            "summary_changed": lambda d: d["entries"][1].__setitem__("summary", "rewritten"),
            "middle_entry_removed": lambda d: d["entries"].pop(1),
            "rev_renumbered": lambda d: d["entries"][2].__setitem__("rev", 9),
            "creator_changed": lambda d: d.__setitem__("created_by", "mallory"),
            "hash_field_forged": lambda d: d["entries"][2].__setitem__("prev_hash", SHA_B),
        }
        for name, step in cases.items():
            with self.subTest(case=name):
                self._path().write_text(json.dumps(mutate(copy.deepcopy(original), step), indent=2) + "\n",
                                        encoding="utf-8")
                with self.assertRaises(h.HistoryError):
                    h.load_history(self.tree, RULE_ID)
                with self.assertRaises(h.HistoryError):
                    h.append_entry(self.tree, RULE_ID, actor="dave", at="2026-11-08T13:00:00Z", action="edit",
                                   rule_sha256=SHA_A, summary="after tamper", validation_status="NOT_RUN")
        self._path().write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(h.load_history(self.tree, RULE_ID)["entries"][1]["summary"], "edited")

    def test_append_only(self):
        self._create()
        before = h.load_history(self.tree, RULE_ID)["entries"]
        first_bytes = canonical_bytes(before[0])
        self._edit()
        after = h.load_history(self.tree, RULE_ID)["entries"]
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(canonical_bytes(after[0]), first_bytes)
        self.assertEqual(after[: len(before)], before)
        # creating over an existing history is refused and leaves the file untouched
        bytes_on_disk = self._path().read_bytes()
        with self.assertRaises(h.HistoryError):
            self._create(actor="mallory")
        self.assertEqual(self._path().read_bytes(), bytes_on_disk)
        # the sidecar is a regular file under history/rules/ and an unknown or unsafe rule id is refused
        self.assertTrue(self._path().is_file())
        with self.assertRaises(h.HistoryError):
            h.load_history(self.tree, "../escape")


if __name__ == "__main__":
    unittest.main()
