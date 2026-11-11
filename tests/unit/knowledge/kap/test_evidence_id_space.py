"""RC fix: a real Odoo pair yields more than 999 evidence rows, so the `EV-NNN` grammar is `EV-` plus at least three
digits. Three-digit ids keep their meaning and file names; `EV-1000` follows `EV-999`."""

import json
import re
import unittest
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.loader import KNOWLEDGE_ROOT


class EvidenceIdSpaceTests(unittest.TestCase):
    def test_ids_continue_past_999(self):
        self.assertEqual(eb.next_evidence_id(["EV-999"]), "EV-1000")
        self.assertEqual(eb.next_evidence_id(["EV-001", "EV-1000", "EV-0500"]), "EV-1001")
        self.assertEqual(eb.next_evidence_id(["EV-998"]), "EV-999")  # unchanged below the old cap
        self.assertEqual(eb.next_evidence_id([]), "EV-001")

    def test_generator_recognises_four_digit_ids(self):
        self.assertTrue(gen._EV_ID.match("EV-1000"))
        self.assertTrue(gen._EV_ID.match("EV-007"))
        self.assertFalse(gen._EV_ID.match("EV-7"))

    def test_every_shipped_schema_pattern_accepts_four_digits_and_rejects_short_ids(self):
        checked = 0
        for path in sorted((KNOWLEDGE_ROOT / "schemas").glob("*.json")):
            for pattern in re.findall(r'"pattern":\s*"(\^EV-[^"]*)"', path.read_text(encoding="utf-8")):
                if "\\\\\\\\d" in pattern:  # a pre-existing literal-backslash pattern, not an id grammar
                    continue
                regex = json.loads(f'"{pattern}"')
                self.assertTrue(re.search(regex, "EV-1000"), f"{path.name}: {regex}")
                self.assertTrue(re.search(regex, "EV-001"), f"{path.name}: {regex}")
                self.assertFalse(re.search(regex, "EV-1"), f"{path.name}: {regex}")
                checked += 1
        self.assertGreaterEqual(checked, 9)

    def test_evidence_schema_validates_a_four_digit_id(self):
        schema = json.loads((KNOWLEDGE_ROOT / "schemas" / "evidence.schema.json").read_text(encoding="utf-8"))
        id_schema = schema["properties"]["id"]
        self.assertEqual(v.check("EV-1000", id_schema), [])
        self.assertTrue(v.check("EV-12", id_schema))


if __name__ == "__main__":
    unittest.main()
