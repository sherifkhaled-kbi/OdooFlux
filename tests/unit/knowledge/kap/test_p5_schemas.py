"""TST-011-041 (REQ-KAP-013, REQ-KAP-014): file_accounting and change_ledger schemas.

Samples are built in code. Each schema must accept its valid sample, reject a missing required key and an unknown
key, and keep the class, disposition, state and reason enums closed.

The stdlib validator has no if/then, so "rationale required for NO_CUSTOM_MODULE_IMPACT and HUMAN_REVIEW" and
"reason_code required for EXCLUDED and UNSUPPORTED" are enforced by ledger code (T043) and accounting code (T044).
The schemas here only keep the fields present and typed; `test_rationale_required_conditionally` pins that split.
"""

import copy
import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SCHEMAS = KNOWLEDGE_ROOT / "schemas"
SHA_A = "a" * 64
SNAP_FROM = "ss-" + "ab" * 6
SNAP_TO = "ss-" + "cd" * 6
TS = "2026-11-08T10:00:00Z"
ZERO = "0" * 64

CLASSES = ("ADDED", "REMOVED", "RENAMED_CANDIDATE", "MOVED", "SIGNATURE_CHANGED", "BEHAVIOUR_CHANGED",
           "DEPRECATED", "REPLACEMENT_CANDIDATE", "UNKNOWN")
DISPOSITIONS = ("RULE_CREATED", "EXISTING_RULE_LINKED", "NO_CUSTOM_MODULE_IMPACT", "DETECTION_ONLY",
                "HUMAN_REVIEW", "UNSUPPORTED", "UNRESOLVED")
STATES = ("PENDING", "ANALYZED", "EXCLUDED", "UNSUPPORTED", "FAILED")


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _change() -> dict:
    return {
        "change_id": "CH-0123456789abcdef",
        "step": "17-01",
        "domain": "python_orm",
        "kind": "field",
        "subject_key": "sale.demo.order::field::amount",
        "class": "SIGNATURE_CHANGED",
        "detail": {"from": "Float", "to": "Monetary"},
        "confirmed": False,
        "locations": [{"snapshot_id": SNAP_TO, "path": "addons/sale_demo/models/order.py", "line": 12,
                       "sha256": SHA_A}],
        "disposition": "UNRESOLVED",
        "disposition_data": {"rule_ids": [], "evidence_ids": [], "rationale": None, "reviewer": None,
                             "decided_at": None},
        "proposed_by": "DETERMINISTIC",
        "history": [{"seq": 1, "at": TS, "actor": "DETERMINISTIC", "action": "create", "from": None,
                     "to": "UNRESOLVED", "prev_hash": ZERO}],
    }


def _ledger() -> dict:
    return {
        "schema": "odooflux.change_ledger/1",
        "step": "17-01",
        "from": SNAP_FROM,
        "to": SNAP_TO,
        "entries": [_change()],
        "ledger_digest": "ef" * 32,
    }


def _accounting() -> dict:
    return {
        "pair": {"from_snapshot": SNAP_FROM, "to_snapshot": SNAP_TO, "step": "17-01"},
        "files": [
            {"path": "addons/sale_demo/models/order.py", "change_kind": "modified", "state": "ANALYZED",
             "reason_code": None, "domain": "python_orm", "parser": "python-ast", "error": None},
            {"path": "addons/sale_demo/static/src/x.js", "change_kind": "added", "state": "UNSUPPORTED",
             "reason_code": "NO_JS_ADAPTER", "domain": None, "parser": None, "error": None},
        ],
        "totals": {"PENDING": 0, "ANALYZED": 1, "EXCLUDED": 0, "UNSUPPORTED": 1, "FAILED": 0},
        "independent_count": 2,
    }


SAMPLES = {
    "file_accounting": _accounting,
    "change_ledger": _ledger,
}


class P5SchemaTests(unittest.TestCase):
    def test_valid_samples(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                self.assertEqual(v.check(make(), _load(name)), [])
        # an empty ledger and an empty accounting list are valid
        empty_ledger = _ledger()
        empty_ledger["entries"] = []
        self.assertEqual(v.check(empty_ledger, _load("change_ledger")), [])
        empty_acc = _accounting()
        empty_acc["files"] = []
        empty_acc["totals"] = {"PENDING": 0, "ANALYZED": 0, "EXCLUDED": 0, "UNSUPPORTED": 0, "FAILED": 0}
        self.assertEqual(v.check(empty_acc, _load("file_accounting")), [])
        # a manual, confirmed-by-rationale disposition with every optional field filled is valid
        change = _change()
        change["disposition"] = "HUMAN_REVIEW"
        change["disposition_data"] = {"rule_ids": [], "evidence_ids": ["EV-K00001"],
                                      "rationale": "needs a reviewer", "reviewer": "sherif", "decided_at": TS}
        change["proposed_by"] = "MANUAL"
        ledger = _ledger()
        ledger["entries"] = [change]
        self.assertEqual(v.check(ledger, _load("change_ledger")), [])

    def test_missing_field_fails(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                schema = _load(name)
                for key in schema["required"]:
                    sample = make()
                    del sample[key]
                    problems = v.check(sample, schema)
                    self.assertTrue(any(f"missing required key {key!r}" in msg for _, msg in problems),
                                    f"{name} without {key}: {problems}")
        change_schema = _load("change_ledger")
        for key in change_schema["properties"]["entries"]["items"]["required"]:
            with self.subTest(change_key=key):
                ledger = _ledger()
                del ledger["entries"][0][key]
                self.assertTrue(v.check(ledger, change_schema))
        acc_schema = _load("file_accounting")
        for key in acc_schema["properties"]["files"]["items"]["required"]:
            with self.subTest(file_key=key):
                acc = _accounting()
                del acc["files"][0][key]
                self.assertTrue(v.check(acc, acc_schema))

    def test_additional_property_fails(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                sample = make()
                sample["unexpected_field"] = 1
                self.assertIn("/unexpected_field", [p for p, _ in v.check(sample, _load(name))])
        ledger = _ledger()
        ledger["entries"][0]["extra"] = 1
        self.assertTrue(v.check(ledger, _load("change_ledger")))
        acc = _accounting()
        acc["files"][0]["extra"] = 1
        self.assertTrue(v.check(acc, _load("file_accounting")))

    def test_class_enum_closed(self):
        schema = _load("change_ledger")
        for cls in CLASSES:
            with self.subTest(cls=cls):
                ledger = _ledger()
                ledger["entries"][0]["class"] = cls
                self.assertEqual(v.check(ledger, schema), [])
        for bogus in ("RENAMED", "CHANGED", "", "rename_candidate"):
            with self.subTest(bogus=bogus):
                ledger = _ledger()
                ledger["entries"][0]["class"] = bogus
                self.assertTrue(v.check(ledger, schema))

    def test_disposition_enum_closed(self):
        schema = _load("change_ledger")
        for disp in DISPOSITIONS:
            with self.subTest(disposition=disp):
                ledger = _ledger()
                ledger["entries"][0]["disposition"] = disp
                self.assertEqual(v.check(ledger, schema), [])
        ledger = _ledger()
        ledger["entries"][0]["disposition"] = "AUTO_CONFIRMED"
        self.assertTrue(v.check(ledger, schema))
        acc_schema = _load("file_accounting")
        for state in STATES:
            with self.subTest(state=state):
                acc = _accounting()
                acc["files"][0]["state"] = state
                self.assertEqual(v.check(acc, acc_schema), [])
        acc = _accounting()
        acc["files"][0]["state"] = "SKIPPED"
        self.assertTrue(v.check(acc, acc_schema))

    def test_rationale_required_conditionally(self):
        # The key itself is always present (schema requires it); a present rationale must be non-empty.
        schema = _load("change_ledger")
        ledger = _ledger()
        del ledger["entries"][0]["disposition_data"]["rationale"]
        self.assertTrue(any("rationale" in msg for _, msg in v.check(ledger, schema)))
        ledger = _ledger()
        ledger["entries"][0]["disposition"] = "NO_CUSTOM_MODULE_IMPACT"
        ledger["entries"][0]["disposition_data"]["rationale"] = ""
        self.assertTrue(v.check(ledger, schema), "an empty rationale is rejected")
        ledger["entries"][0]["disposition_data"]["rationale"] = "checked the changed field is unused"
        self.assertEqual(v.check(ledger, schema), [])
        # null is schema-valid; the disposition-dependent requirement is enforced by ledger code (T043).
        ledger["entries"][0]["disposition_data"]["rationale"] = None
        self.assertEqual(v.check(ledger, schema), [])


if __name__ == "__main__":
    unittest.main()
