"""TST-004-002 (REQ-EVD-002, REQ-EVD-004): one golden invalid fixture per code, and the valid tree passes."""

import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import load_knowledge

from .helpers import GOLDEN, codes, copy_fixture


class EvidenceValidationTests(unittest.TestCase):
    def test_valid_tree_has_no_findings(self):
        self.assertEqual(validate_knowledge(load_knowledge(GOLDEN / "valid")), [])

    def test_each_fixture_produces_its_code(self):
        expected = {
            "E001_schema": "E001", "E001_verified_without_test_ref": "E001",
            "E001_absent_location_without_scope": "E001", "E002_url_not_allowlisted": "E002",
            "E003_branch_revision": "E003", "E004_duplicate_id": "E004", "E005_rule_missing_evidence": "E005",
            "E006_unknown_evidence": "E006", "E007_registry_ordering": "E007",
            "W001_maturity_capped": "W001", "W002_identical_claim": "W002",
        }
        for name, code in expected.items():
            with self.subTest(name):
                self.assertIn(code, codes(GOLDEN / "invalid" / name))

    def test_stackoverflow_url_is_rejected_with_message(self):
        root = copy_fixture("valid")
        path = root / "evidence" / "EV-001.json"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "https://github.com/odoo/odoo/blob", "https://stackoverflow.com/blob"), encoding="utf-8")
        messages = [f.message for f in validate_knowledge(load_knowledge(root)) if f.code == "E002"]
        self.assertEqual(messages, ["url not in allow-list"])

    def test_revision_message_names_the_rule(self):
        findings = [f for f in validate_knowledge(load_knowledge(GOLDEN / "invalid" / "E003_branch_revision"))
                    if f.code == "E003"]
        self.assertTrue(any("commit SHA or catalogued tag" in f.message for f in findings))

    def test_unknown_sha_not_in_catalogue_is_rejected(self):
        root = copy_fixture("valid")
        path = root / "evidence" / "EV-001.json"
        path.write_text(path.read_text(encoding="utf-8").replace("9ef8d62331b128bcd288528e4639e0901d85fcc8",
                                                                 "1" * 40), encoding="utf-8")
        self.assertIn("E003", codes(root))

    def test_catalogued_tag_is_an_acceptable_revision(self):
        root = copy_fixture("valid")
        path = root / "evidence" / "EV-001.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"revision": "9ef8d62331b128bcd288528e4639e0901d85fcc8"',
                                                                 '"revision": "v17-release"'), encoding="utf-8")
        self.assertNotIn("E003", codes(root))  # tag listed in revisions.json


if __name__ == "__main__":
    unittest.main()
