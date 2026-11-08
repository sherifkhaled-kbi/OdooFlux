"""TST-011-054 (REQ-KAP-013, REQ-KAP-012, REQ-KAP-044): the synthetic 16.0 to 17.0 pair, end to end.

Both snapshots come from the git-local adapter reading the synthetic repository (`tests/fixtures/kap`), not from plain
directories. Every change class is expected in the ledger, the accounting reconciles with no PENDING file, the
unparsable file is FAILED and visible in the ledger, a rerun writes identical ledger bytes, and a changed pinned
revision gives a new snapshot digest while the old ledger file stays byte-identical. Offline; git plumbing only.
"""

import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.extract import driver
from odooflux.knowledge.extract.accounting import check_document
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.parsers.javascript import treesitter_adapter
from tests.fixtures.kap.make_synth_repo import ADDON, EXPECTED_CHANGES, build_synth_repo
from odooflux.builtins import build_registries  # composition root: the document adapters the KAP tests inject
REGISTRIES = build_registries()
TOOLKIT = REGISTRIES.extract_toolkit

GIT = shutil.which("git")
SOURCE_ID = "odoo-community-17.0"
ALLOW = ["https://github.com/odoo/odoo/"]
CREATED = "2026-11-08T10:00:00Z"
STEP = "01-02"
CLASSES = {"ADDED", "REMOVED", "SIGNATURE_CHANGED", "BEHAVIOUR_CHANGED", "MOVED", "DEPRECATED",
           "REPLACEMENT_CANDIDATE", "UNKNOWN"}
CHANGED_PATHS = {
    f"{ADDON}/__manifest__.py", f"{ADDON}/models/sale_order.py", f"{ADDON}/models/legacy_utils.py",
    f"{ADDON}/models/sale_utils.py", f"{ADDON}/models/__init__.py",
    f"{ADDON}/models/broken_hooks.py", f"{ADDON}/views/sale_views.xml",
    f"{ADDON}/security/ir.model.access.csv", f"{ADDON}/static/src/js/demo_widget.js",
    f"{ADDON}/migrations/17.0.1.0.0/post-migrate.py",
}
JS_ADAPTER = treesitter_adapter.available()


def _spec(url, revision):
    return {
        "source_id": SOURCE_ID, "kind": "GIT_COMMUNITY", "official": False, "url": url,
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3", "branch": "17.0", "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


def _matches(record, expected) -> bool:
    """The ledger record for an expected change: same domain, and its subject (or the candidate pairing in detail)
    names the expected subject as a whole token."""
    haystack = record["subject_key"] + " " + json.dumps(record["detail"], sort_keys=True)
    pattern = r"(?<!\w)" + re.escape(expected["subject"]) + r"(?![\w])"
    return record["domain"] == expected["domain"] and re.search(pattern, haystack) is not None


@unittest.skipUnless(GIT, "git is not installed; the git-local adapter needs git")
class SynthPairEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.repo = build_synth_repo(cls.base / "synth")
        cls.store = BlobStore(cls.base / "objects")
        cls.adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)
        cls.local = "local:" + cls.repo.path
        cls.from_snap = cls.adapter.snapshot(_spec(cls.local, cls.repo.from_sha), cls.store, created_at=CREATED)
        cls.to_snap = cls.adapter.snapshot(_spec(cls.local, cls.repo.to_sha), cls.store, created_at=CREATED)
        cls.result, cls.ledger = cls._extract(cls.from_snap, cls.to_snap)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _extract(cls, from_snap, to_snap):
        result = driver.extract_pair(from_snap, to_snap, None, full_registry(), store=cls.store, step=STEP, toolkit=TOOLKIT)
        ledger = Ledger.create(STEP, from_snap, to_snap, result.drafts, clock=lambda: CREATED)
        return result, ledger

    def _record(self, expected):
        found = [r for r in self.ledger.records() if _matches(r, expected)]
        return found[0] if found else None

    def _state(self, path):
        return next(f for f in self.result.accounting["files"] if f["path"] == path)

    def test_all_files_accounted(self):
        files = self.result.accounting["files"]
        self.assertEqual({f["path"] for f in files}, CHANGED_PATHS)
        self.assertEqual(check_document(self.result.accounting), [])
        self.assertEqual(self.result.accounting["totals"]["PENDING"], 0)
        self.assertEqual(self.result.accounting["independent_count"], len(files))

    def test_known_file_states(self):
        self.assertEqual((self._state(f"{ADDON}/models/broken_hooks.py")["state"],
                          self._state(f"{ADDON}/models/broken_hooks.py")["reason_code"]),
                         ("FAILED", "PARSE_ERROR"))
        self.assertEqual(self._state(f"{ADDON}/models/sale_order.py")["state"], "ANALYZED")
        self.assertEqual(self._state(f"{ADDON}/migrations/17.0.1.0.0/post-migrate.py")["state"], "ANALYZED")
        js = self._state(f"{ADDON}/static/src/js/demo_widget.js")
        if JS_ADAPTER:
            self.assertEqual(js["state"], "ANALYZED")
        else:
            self.assertEqual((js["state"], js["reason_code"]), ("UNSUPPORTED", "NO_JS_ADAPTER"))

    def test_expected_changes_found(self):
        missing = []
        for expected in EXPECTED_CHANGES:
            if expected["domain"] == "js_owl" and not JS_ADAPTER:
                # without the optional adapter the file is accounted UNSUPPORTED and its change is an UNKNOWN record
                js = self._state(expected["path"])
                record = next((r for r in self.ledger.records() if r["subject_key"] == expected["path"]), None)
                if js["state"] != "UNSUPPORTED" or record is None or record["class"] != "UNKNOWN":
                    missing.append(expected["subject"])
                continue
            if self._record(expected) is None:
                missing.append(f"{expected['domain']}:{expected['subject']}")
        self.assertEqual(missing, [])

    def test_known_class_assignments(self):
        classes = {r["subject_key"]: r["class"] for r in self.ledger.records()}
        self.assertEqual(classes[f"{ADDON}/models/broken_hooks.py"], "UNKNOWN")
        self.assertEqual(classes["sale.demo.order.compute_total"], "SIGNATURE_CHANGED")
        self.assertEqual(classes["sale.demo.order.check_amount"], "BEHAVIOUR_CHANGED")
        self.assertEqual(classes["sale.demo.order.compute_legacy_total"], "DEPRECATED")
        self.assertEqual(classes["sale.demo.order.priority"], "ADDED")
        self.assertEqual(classes["sale.demo.order.get_amount_old"], "REPLACEMENT_CANDIDATE")
        self.assertEqual(classes["sale_demo.format_reference"], "MOVED")
        self.assertEqual(classes["view_sale_demo_form"], "BEHAVIOUR_CHANGED")
        self.assertEqual(classes["access_sale_demo_order_manager"], "ADDED")
        self.assertEqual(classes["depends.account"], "ADDED")

    def test_every_change_class_present(self):
        present = {r["class"] for r in self.ledger.records()}
        # REMOVED is not a final class in this fixture: the only removed method is consumed by its replacement
        # pairing (checked in test_replacement_pairs_removed_method), and no removal is left unpaired.
        self.assertTrue((CLASSES - {"REMOVED"}) <= present, sorted((CLASSES - {"REMOVED"}) - present))

    def test_unsupported_js_record_in_ledger(self):
        if JS_ADAPTER:
            self.skipTest("the JavaScript adapter is present, so the file is analysed")
        path = f"{ADDON}/static/src/js/demo_widget.js"
        records = [r for r in self.ledger.records() if r["subject_key"] == path]
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["class"], records[0]["disposition"], records[0]["domain"]),
                         ("UNKNOWN", "UNRESOLVED", "js_owl"))
        self.assertIn("NO_JS_ADAPTER", records[0]["detail"]["detail"])

    def test_replacement_pairs_removed_method(self):
        record = self.ledger.get(next(r["change_id"] for r in self.ledger.records()
                                      if r["subject_key"] == "sale.demo.order.get_amount_old"))
        self.assertEqual(record["class"], "REPLACEMENT_CANDIDATE")
        self.assertEqual(record["detail"]["to"], "sale.demo.order.get_amount")
        self.assertFalse(record["confirmed"])

    def test_unparsable_file_visible_in_ledger(self):
        path = f"{ADDON}/models/broken_hooks.py"
        state = self._state(path)
        self.assertEqual((state["state"], state["reason_code"]), ("FAILED", "PARSE_ERROR"))
        record = next(r for r in self.ledger.records() if r["subject_key"] == path)
        self.assertEqual(record["class"], "UNKNOWN")
        self.assertEqual(record["detail"]["reason"], "PARSE_FAILURE")

    def test_accounting_reconciles_with_zero_pending(self):
        self.assertEqual(self.ledger.verify(), [])
        records = self.ledger.records()
        self.assertEqual(len(self.ledger.unresolved()), len(records))
        snapshot_ids = {self.from_snap["snapshot_id"], self.to_snap["snapshot_id"]}
        for record in records:
            self.assertTrue({loc["snapshot_id"] for loc in record["locations"]} <= snapshot_ids)

    def test_rerun_identical_ledger_bytes(self):
        _, again = self._extract(self.from_snap, self.to_snap)
        first, second = self.base / "first.ledger.json", self.base / "second.ledger.json"
        self.ledger.save(first)
        again.save(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_changed_revision_new_digest_old_ledger_unchanged(self):
        old_path = self.base / "old.ledger.json"
        self.ledger.save(old_path)
        before = hashlib.sha256(old_path.read_bytes()).hexdigest()
        moved = self.adapter.snapshot(_spec(self.local, self.repo.from_sha), self.store, created_at=CREATED)
        self.assertNotEqual(moved["snapshot_digest"], self.to_snap["snapshot_digest"])
        self.assertNotEqual(moved["snapshot_id"], self.to_snap["snapshot_id"])
        _, new_ledger = self._extract(self.from_snap, moved)
        new_path = self.base / "new.ledger.json"
        new_ledger.save(new_path)
        self.assertEqual(hashlib.sha256(old_path.read_bytes()).hexdigest(), before)
        self.assertEqual(Ledger.load(old_path).verify(), [])
        self.assertNotEqual(Ledger.load(new_path).to_dict()["to"], Ledger.load(old_path).to_dict()["to"])


if __name__ == "__main__":
    unittest.main()
