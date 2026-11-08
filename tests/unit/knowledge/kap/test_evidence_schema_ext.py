"""TST-011-055 (REQ-KAP-015, REQ-KAP-005): evidence.schema.json extended with optional KAP fields only.

Record level: `origin` (LEGACY_BUILTIN, KAP_DETERMINISTIC, KAP_MANUAL), `source_id`, `change_ids`, `official`.
Location level: `content_sha256`, `snapshot_ref`. All optional; `additionalProperties: false` is kept. AI_PROPOSED is
never an origin for evidence (REQ-KAP-017). The 200 built-in records must still validate unchanged.
"""

import copy
import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "evidence.schema.json").read_text(encoding="utf-8"))
EVIDENCE_DIR = KNOWLEDGE_ROOT / "evidence"
NEW_RECORD_FIELDS = ("origin", "source_id", "change_ids", "official")
NEW_LOCATION_FIELDS = ("content_sha256", "snapshot_ref")
SHA = "e" * 64


def _builtin() -> dict:
    return json.loads((EVIDENCE_DIR / "EV-001.json").read_text(encoding="utf-8"))


def _kap_record() -> dict:
    record = _builtin()
    record.update({
        "origin": "KAP_DETERMINISTIC",
        "source_id": "odoo-community-17.0",
        "change_ids": ["CH-0123456789abcdef"],
        "official": True,
    })
    record["locations"][0].update({"content_sha256": SHA, "snapshot_ref": "ss-abababababab"})
    return record


class EvidenceSchemaExtTests(unittest.TestCase):
    def test_builtin_evidence_unchanged(self):
        files = sorted(EVIDENCE_DIR.glob("*.json"))
        self.assertEqual(len(files), 200)
        for path in files:
            with self.subTest(file=path.name):
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(v.check(record, SCHEMA), [])
                self.assertFalse(set(NEW_RECORD_FIELDS) & set(record), "built-in records gain no KAP fields")
                for loc in record["locations"]:
                    self.assertFalse(set(NEW_LOCATION_FIELDS) & set(loc))

    def test_new_fields_valid(self):
        self.assertEqual(v.check(_kap_record(), SCHEMA), [])
        for origin in ("LEGACY_BUILTIN", "KAP_DETERMINISTIC", "KAP_MANUAL"):
            with self.subTest(origin=origin):
                record = _kap_record()
                record["origin"] = origin
                self.assertEqual(v.check(record, SCHEMA), [])
        official_false = _kap_record()
        official_false["official"] = False  # OCA and OpenUpgrade derived evidence
        self.assertEqual(v.check(official_false, SCHEMA), [])

    def test_ai_origin_rejected(self):
        bad = _kap_record()
        bad["origin"] = "AI_PROPOSED"
        self.assertTrue(v.check(bad, SCHEMA), "AI cannot create evidence")
        bad = _kap_record()
        bad["change_ids"] = ["CH-XYZ"]
        self.assertTrue(v.check(bad, SCHEMA))
        bad = _kap_record()
        bad["official"] = "yes"
        self.assertTrue(v.check(bad, SCHEMA))
        bad = _kap_record()
        bad["locations"][0]["content_sha256"] = "E" * 64  # canonical lowercase only
        self.assertTrue(v.check(bad, SCHEMA))
        bad = _kap_record()
        bad["locations"][0]["snapshot_ref"] = "snap-1"
        self.assertTrue(v.check(bad, SCHEMA))
        bad = _kap_record()
        bad["proposed_by"] = "AI"  # unknown keys are still refused
        self.assertIn("/proposed_by", [p for p, _ in v.check(bad, SCHEMA)])


if __name__ == "__main__":
    unittest.main()
