"""TST-011-044 (REQ-KAP-013): file accounting (states, invariant, independent count).

Every changed file of a snapshot pair ends in exactly one state. The invariant `sum(totals) == len(files) ==
independent_count` is tested here, and `finalize` refuses while any file is PENDING. Snapshots are in-memory dicts
with the SourceSnapshot shape (`entries` of `{path, sha256, size, kind}`).
"""

import copy
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.extract import accounting as acc
from odooflux.knowledge.extract.accounting import AccountingError, FileAccounting, changed_paths
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SNAP_FROM = {"snapshot_id": "ss-" + "ab" * 6, "entries": []}
SNAP_TO = {"snapshot_id": "ss-" + "cd" * 6, "entries": []}


def _e(path, digest, size=10):
    return {"path": path, "sha256": digest * 64, "size": size, "kind": "python"}


def _pair():
    """Five changed files and one unchanged file: modified, removed, added, one out-of-scope, one unsupported."""
    from_entries = [_e("addons/a/models/x.py", "1"), _e("addons/a/models/gone.py", "2"), _e("addons/a/same.py", "3")]
    to_entries = [_e("addons/a/models/x.py", "9"), _e("addons/a/models/new.py", "4"), _e("addons/a/same.py", "3"),
                  _e("addons/a/static/app.js", "5"), _e("addons/a/data/big.csv", "6")]
    return ({**SNAP_FROM, "entries": from_entries}, {**SNAP_TO, "entries": to_entries})


def _schema():
    import json
    return json.loads((KNOWLEDGE_ROOT / "schemas" / "file_accounting.schema.json").read_text(encoding="utf-8"))


class AccountingTests(unittest.TestCase):
    def test_changed_paths_is_path_level_and_sorted(self):
        src, dst = _pair()
        self.assertEqual(changed_paths(src["entries"], dst["entries"]), {
            "addons/a/data/big.csv": "added",
            "addons/a/models/gone.py": "removed",
            "addons/a/models/new.py": "added",
            "addons/a/models/x.py": "modified",
            "addons/a/static/app.js": "added",
        })

    def test_invariant_sum_equals_files(self):
        src, dst = _pair()
        fa = FileAccounting.for_pair("17-01", src, dst)
        self.assertEqual(fa.independent_count, 5)
        fa.set_state("addons/a/models/x.py", "ANALYZED", domain="python_orm", parser="python-ast")
        fa.set_state("addons/a/models/gone.py", "ANALYZED", domain="python_orm", parser="python-ast")
        fa.set_state("addons/a/models/new.py", "FAILED", reason_code="PARSE_ERROR", domain="python_orm",
                     parser="python-ast", error="SyntaxError line 3")
        fa.set_state("addons/a/static/app.js", "UNSUPPORTED", reason_code="NO_JS_ADAPTER")
        fa.set_state("addons/a/data/big.csv", "EXCLUDED", reason_code="OUT_OF_SCOPE_GLOB")
        doc = fa.finalize()
        totals = doc["totals"]
        self.assertEqual(sum(totals.values()), len(doc["files"]))
        self.assertEqual(len(doc["files"]), doc["independent_count"])
        self.assertEqual(totals, {"PENDING": 0, "ANALYZED": 2, "EXCLUDED": 1, "UNSUPPORTED": 1, "FAILED": 1})
        self.assertEqual(acc.check_document(doc), [])
        self.assertEqual(v.check(doc, _schema()), [])
        # a document whose totals drift from its files is caught
        drifted = copy.deepcopy(doc)
        drifted["totals"]["ANALYZED"] += 1
        self.assertTrue(acc.check_document(drifted))
        # a file that disappears from the list is caught by the independent count
        dropped = copy.deepcopy(doc)
        dropped["files"].pop()
        self.assertTrue(acc.check_document(dropped))

    def test_pending_blocks_finalize(self):
        src, dst = _pair()
        fa = FileAccounting.for_pair("17-01", src, dst)
        fa.set_state("addons/a/models/x.py", "ANALYZED", domain="python_orm", parser="python-ast")
        self.assertEqual(len(fa.pending()), 4)
        with self.assertRaises(AccountingError):
            fa.finalize()
        for path in fa.pending():
            fa.set_state(path, "EXCLUDED", reason_code="OTHER", error="test fixture")
        doc = fa.finalize()
        self.assertEqual(doc["totals"]["PENDING"], 0)

    def test_reason_required_for_excluded_unsupported(self):
        src, dst = _pair()
        fa = FileAccounting.for_pair("17-01", src, dst)
        path = "addons/a/static/app.js"
        for state in ("EXCLUDED", "UNSUPPORTED", "FAILED"):
            with self.subTest(state=state):
                with self.assertRaises(AccountingError):
                    fa.set_state(path, state)
                with self.assertRaises(AccountingError):
                    fa.set_state(path, state, reason_code="NOT_A_CODE")
        with self.assertRaises(AccountingError):
            fa.set_state(path, "EXCLUDED", reason_code="OTHER")  # free text is required for OTHER
        with self.assertRaises(AccountingError):
            fa.set_state(path, "ANALYZED", reason_code="BINARY")  # analyzed files carry no reason
        with self.assertRaises(AccountingError):
            fa.set_state(path, "PENDING")
        with self.assertRaises(AccountingError):
            fa.set_state("addons/a/unknown.py", "ANALYZED")  # files are never added silently
        fa.set_state(path, "UNSUPPORTED", reason_code="NO_JS_ADAPTER")
        with self.assertRaises(AccountingError):
            fa.set_state(path, "ANALYZED")  # exactly one terminal state per file
        # the stored document carries the reason, and a record without one is caught by the checker
        doc = copy.deepcopy(fa.document())
        rec = next(f for f in doc["files"] if f["path"] == path)
        self.assertEqual(rec["reason_code"], "NO_JS_ADAPTER")
        rec["reason_code"] = None
        self.assertTrue(acc.check_document(doc))

    def test_independent_count_override_is_checked(self):
        src, dst = _pair()
        fa = FileAccounting.for_pair("17-01", src, dst, independent_count=4)
        for path in list(fa.pending()):
            fa.set_state(path, "EXCLUDED", reason_code="OTHER", error="fixture")
        with self.assertRaises(AccountingError):
            fa.finalize()


if __name__ == "__main__":
    unittest.main()
