"""TST-011-020 (REQ-KAP-019, REQ-KAP-021, REQ-KAP-005): additive rule schema fields and the rule history schema.

The 91 committed rules must keep validating unchanged. `origin` and `rev` are optional and accepted only with the
documented values; `rule_history.schema.json` checks the append-only sidecar shape.
"""

import copy
import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SCHEMAS = KNOWLEDGE_ROOT / "schemas"
COMPAT = KNOWLEDGE_ROOT / "compatibility"
SHA_A = "a" * 64
TS = "2026-11-08T10:00:00Z"


def _load(name: str):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _builtin_rules() -> list:
    rules = []
    for path in sorted(COMPAT.glob("*.rules.json")):
        rules.extend(json.loads(path.read_text(encoding="utf-8")))
    return rules


def _sample_rule() -> dict:
    return copy.deepcopy(_builtin_rules()[0])


def _history() -> dict:
    first = {
        "rev": 1, "at": TS, "actor": "tester", "action": "create", "summary": "created",
        "rule_sha256": SHA_A, "provenance": {"source": "manual"}, "validation_status": "PASSED", "prev_hash": None,
    }
    second = dict(first, rev=2, action="edit", summary="edited", prev_hash=SHA_A, validation_status="NOT_RUN")
    return {"rule_id": "17-18.manual.example-check", "created_by": "tester", "created_at": TS,
            "entries": [first, second]}


class RuleSchemaExtTests(unittest.TestCase):
    def test_builtin_rules_still_valid(self):
        rules = _builtin_rules()
        self.assertEqual(len(rules), 91)
        self.assertEqual(v.check(rules, _load("rule_metadata")), [])

    def test_new_fields_accepted(self):
        schema = _load("rule_metadata")
        rule = _sample_rule()
        rule["origin"] = "MANUAL"
        rule["rev"] = 3
        self.assertEqual(v.check([rule], schema), [])
        for origin in ("BUILTIN", "GENERATED"):
            with self.subTest(origin=origin):
                self.assertEqual(v.check([dict(rule, origin=origin)], schema), [])
        for bad in ({"origin": "AI_PROPOSED"}, {"origin": "manual"}, {"rev": 0}, {"rev": "3"}, {"rev": 1.5}):
            with self.subTest(bad=bad):
                self.assertNotEqual(v.check([dict(rule, **bad)], schema), [])
        # unknown keys stay rejected (additionalProperties false is unchanged)
        self.assertNotEqual(v.check([dict(rule, owner="x")], schema), [])

    def test_history_schema(self):
        schema = _load("rule_history")
        self.assertEqual(v.check(_history(), schema), [])
        missing = _history()
        del missing["entries"][1]["prev_hash"]
        self.assertNotEqual(v.check(missing, schema), [])
        bad_action = _history()
        bad_action["entries"][0]["action"] = "rewrite"
        self.assertNotEqual(v.check(bad_action, schema), [])
        bad_status = _history()
        bad_status["entries"][0]["validation_status"] = "MAYBE"
        self.assertNotEqual(v.check(bad_status, schema), [])
        extra = _history()
        extra["entries"][0]["note"] = "x"
        self.assertNotEqual(v.check(extra, schema), [])
        bad_hash = _history()
        bad_hash["entries"][1]["prev_hash"] = "not-a-hash"
        self.assertNotEqual(v.check(bad_hash, schema), [])


if __name__ == "__main__":
    unittest.main()
