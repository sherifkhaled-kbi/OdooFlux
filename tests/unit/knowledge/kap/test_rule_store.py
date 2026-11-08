"""TST-011-023 (REQ-KAP-019): rule store keeps untouched rows byte-identical, writes atomically, and rolls back.

Tests copy a committed rules file into a temporary directory and never modify the repository copy.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.authoring import rule_store as rs
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SOURCE = KNOWLEDGE_ROOT / "compatibility" / "17-18.rules.json"
NEW_ID = "17-18.manual.example-check"


def _raw_elements(text: str) -> dict:
    """Map rule id -> exact source text of its top-level element (as the store slices it)."""
    spans, _, _ = rs.split_elements(text)
    out = {}
    for start, end in spans:
        out[json.loads(text[start:end])["id"]] = text[start:end]
    return out


class RuleStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "17-18.rules.json"
        shutil.copyfile(SOURCE, self.path)
        self.original_bytes = self.path.read_bytes()
        self.original_text = self.original_bytes.decode("utf-8")
        self.rows = json.loads(self.original_text)

    def tearDown(self):
        self._tmp.cleanup()

    def _new_row(self) -> dict:
        row = json.loads(json.dumps(self.rows[0]))
        row["id"] = NEW_ID
        return row

    def _leftover_temp_files(self):
        return [p.name for p in self.dir.iterdir() if p.name != self.path.name]

    def test_untouched_rows_byte_identical(self):
        target = self.rows[0]["id"]
        edited = json.loads(json.dumps(self.rows[0]))
        edited["message"] = "edited by the rule store"
        rs.update_rule_file(self.path, replace={target: edited}, append=[self._new_row()])

        new_text = self.path.read_text(encoding="utf-8")
        before = _raw_elements(self.original_text)
        after = _raw_elements(new_text)
        for rule_id, raw in before.items():
            if rule_id == target:
                self.assertNotIn(raw, new_text)
                continue
            with self.subTest(rule_id=rule_id):
                self.assertEqual(after[rule_id], raw)
        self.assertIn(NEW_ID, after)
        # ids and order: original order kept, new row last, everything else parses to the expected values
        parsed = json.loads(new_text)
        self.assertEqual([r["id"] for r in parsed], [r["id"] for r in self.rows] + [NEW_ID])
        self.assertEqual(parsed[0]["message"], "edited by the rule store")
        # key order of a rendered row follows the given dict order
        self.assertEqual(list(parsed[-1].keys()), list(self._new_row().keys()))

    def test_atomic_write(self):
        edited = json.loads(json.dumps(self.rows[0]))
        edited["message"] = "never lands"
        with mock.patch("odooflux.utils.atomic.os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                rs.update_rule_file(self.path, replace={self.rows[0]["id"]: edited})
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(self._leftover_temp_files(), [])

    def test_rollback_on_error(self):
        bad_maturity = self._new_row()
        bad_maturity["maturity"] = "BOGUS"  # schema violation: nothing may be written
        with self.assertRaises(rs.RuleStoreError):
            rs.update_rule_file(self.path, append=[bad_maturity])
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

        with self.assertRaises(rs.RuleStoreError):
            rs.update_rule_file(self.path, replace={"17-18.no.such-rule": self.rows[0]})
        self.assertEqual(self.path.read_bytes(), self.original_bytes)

        good = self._new_row()
        with self.assertRaises(rs.RuleStoreError):
            rs.update_rule_file(self.path, append=[good, good])  # duplicate id inside one call
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        self.assertEqual(self._leftover_temp_files(), [])

        # a valid call afterwards still works on the untouched file
        rs.update_rule_file(self.path, append=[good])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))[-1]["id"], NEW_ID)


if __name__ == "__main__":
    unittest.main()
