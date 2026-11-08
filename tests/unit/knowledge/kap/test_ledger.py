"""TST-011-042 (REQ-KAP-014): change ids, ledger core (create, load, save, history chain, verify).

Ledgers are built in memory from synthetic drafts with a fixed clock. Tampering is done on the saved JSON file, the
way a reviewer or attacker would edit it, and must be reported by `verify()`.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.ledger import ids
from odooflux.knowledge.ledger.ledger import Ledger, LedgerError

SNAP_A = {"snapshot_id": "ss-" + "ab" * 6, "snapshot_digest": "ab" * 32}
SNAP_B = {"snapshot_id": "ss-" + "cd" * 6, "snapshot_digest": "cd" * 32}
ZERO = "0" * 64
TS = "2026-11-08T10:00:00Z"


def _clock():
    return TS


def _drafts():
    return [
        {"domain": "python_orm", "kind": "field", "subject_key": "sale.demo.order::field::amount",
         "class": "SIGNATURE_CHANGED", "detail": {"from": "Float", "to": "Monetary"},
         "locations": [{"snapshot_id": SNAP_B["snapshot_id"], "path": "addons/sale_demo/models/order.py",
                        "line": 12, "sha256": "a" * 64}],
         "proposed_by": "DETERMINISTIC"},
        {"domain": "manifest", "kind": "dependency", "subject_key": "sale_demo::depends::base",
         "class": "ADDED", "detail": {}, "locations": [], "proposed_by": "DETERMINISTIC"},
    ]


def _ledger(drafts=None) -> Ledger:
    return Ledger.create("17-01", SNAP_A, SNAP_B, _drafts() if drafts is None else drafts, clock=_clock)


class ChangeIdTests(unittest.TestCase):
    def test_ids_stable(self):
        expected = "CH-" + hashlib.sha256(
            f"{SNAP_A['snapshot_digest']}|{SNAP_B['snapshot_digest']}|python_orm|field|"
            f"sale.demo.order::field::amount".encode("utf-8")).hexdigest()[:16]
        self.assertEqual(ids.change_id(SNAP_A["snapshot_digest"], SNAP_B["snapshot_digest"], "python_orm", "field",
                                       "sale.demo.order::field::amount"), expected)
        forward = _ledger()
        backward = _ledger(list(reversed(_drafts())))
        self.assertEqual(sorted(e["change_id"] for e in forward.to_dict()["entries"]),
                         sorted(e["change_id"] for e in backward.to_dict()["entries"]))
        self.assertEqual(forward.to_dict()["ledger_digest"], backward.to_dict()["ledger_digest"])
        other = ids.change_id(SNAP_A["snapshot_digest"], SNAP_B["snapshot_digest"], "python_orm", "field",
                              "sale.demo.order::field::total")
        self.assertNotEqual(other, expected)
        self.assertRegex(expected, r"^CH-[0-9a-f]{16}$")

    def test_save_load_roundtrip_keeps_digest(self):
        ledger = _ledger()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "17-01.ledger.json"
            ledger.save(path)
            loaded = Ledger.load(path)
        self.assertEqual(loaded.to_dict(), ledger.to_dict())
        self.assertEqual(loaded.verify(), [])


class LedgerCoreTests(unittest.TestCase):
    def test_unresolved_default(self):
        ledger = _ledger()
        entries = ledger.to_dict()["entries"]
        self.assertEqual(len(entries), 2)
        for entry in entries:
            self.assertEqual(entry["disposition"], "UNRESOLVED")
            self.assertEqual(entry["disposition_data"]["rationale"], None)
            self.assertEqual(entry["confirmed"], False)
            self.assertEqual(len(entry["history"]), 1)
            self.assertEqual(entry["history"][0]["prev_hash"], ZERO)
            self.assertEqual(entry["history"][0]["to"], "UNRESOLVED")
        self.assertEqual(sorted(ledger.unresolved()), sorted(e["change_id"] for e in entries))
        self.assertEqual(ledger.verify(), [])

    def test_duplicate_draft_refused(self):
        drafts = _drafts() + [dict(_drafts()[0])]
        with self.assertRaises(LedgerError):
            _ledger(drafts)

    def test_invalid_draft_refused(self):
        bad = _drafts()
        bad[0]["class"] = "RENAMED"
        with self.assertRaises(LedgerError):
            _ledger(bad)

    def test_history_chain_tamper(self):
        ledger = _ledger()
        cid = ledger.unresolved()[0]
        ledger.append_history(cid, actor="MANUAL", action="set_disposition", from_value="UNRESOLVED",
                              to_value="HUMAN_REVIEW")
        ledger.append_history(cid, actor="MANUAL", action="note", from_value="HUMAN_REVIEW",
                              to_value="HUMAN_REVIEW")
        self.assertEqual(ledger.verify(), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "17-01.ledger.json"
            ledger.save(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            target = next(e for e in raw["entries"] if e["change_id"] == cid)

            # 1) rewrite a past history entry
            tampered = json.loads(json.dumps(raw))
            next(e for e in tampered["entries"] if e["change_id"] == cid)["history"][1]["to"] = "RULE_CREATED"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            findings = Ledger.load(path).verify()
            self.assertIn((cid, "HISTORY_CHAIN_BROKEN"), [(f["change_id"], f["code"]) for f in findings])

            # 2) delete a past history entry and renumber
            removed = json.loads(json.dumps(raw))
            hist = next(e for e in removed["entries"] if e["change_id"] == cid)["history"]
            del hist[1]
            path.write_text(json.dumps(removed), encoding="utf-8")
            findings = Ledger.load(path).verify()
            self.assertTrue(any(f["change_id"] == cid and f["code"] in ("HISTORY_CHAIN_BROKEN", "HISTORY_SEQ")
                                for f in findings), findings)

            # 3) untouched file verifies clean
            self.assertEqual(target["history"][0]["prev_hash"], ZERO)
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(Ledger.load(path).verify(), [])

    def test_load_refuses_schema_invalid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.ledger.json"
            path.write_text(json.dumps({"schema": "odooflux.change_ledger/1"}), encoding="utf-8")
            with self.assertRaises(LedgerError):
                Ledger.load(path)

    def test_get_returns_copy(self):
        ledger = _ledger()
        cid = ledger.unresolved()[0]
        record = ledger.get(cid)
        record["disposition"] = "RULE_CREATED"
        self.assertEqual(ledger.get(cid)["disposition"], "UNRESOLVED")
        with self.assertRaises(LedgerError):
            ledger.get("CH-0000000000000000")


if __name__ == "__main__":
    unittest.main()
