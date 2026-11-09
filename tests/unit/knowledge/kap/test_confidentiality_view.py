"""Feature 012 Wave 3d: the shared confidentiality view (knowledge/release/confidentiality_view.py).

Enterprise status comes only from the verified provenance index (kind GIT_ENTERPRISE or ENTERPRISE_LOCAL). A record's
own `confidentiality` field is forged in these tests and must be ignored.
"""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.release import confidentiality_view as cv

INDEX = {
    "odoo-enterprise-12.0": {"source_id": "odoo-enterprise-12.0", "kind": "GIT_ENTERPRISE", "snapshot_id": "ss-e1e1e1e1e1e1"},
    "odoo-local-ent": {"source_id": "odoo-local-ent", "kind": "ENTERPRISE_LOCAL", "snapshot_id": "ss-e2e2e2e2e2e2"},
    "odoo-community-12.0": {"source_id": "odoo-community-12.0", "kind": "GIT_COMMUNITY", "snapshot_id": "ss-c1c1c1c1c1c1",
                            "confidentiality": "enterprise"},  # forged: the kind decides
    "odoo-forged-ent": {"source_id": "odoo-forged-ent", "kind": "GIT_COMMUNITY", "confidentiality": "public"},
}
ENT = cv.enterprise_source_ids(INDEX)
EVIDENCE = {
    "EV-001": {"id": "EV-001", "source_id": "odoo-enterprise-12.0", "revision": "r1", "match": "SECRET_MATCH",
               "locations": [{"path": "enterprise/secret.py", "match": "SECRET_MATCH"}],
               "url": "https://github.com/odoo/enterprise/blob/r1/secret.py#L1", "description": "SECRET_DESC"},
    "EV-002": {"id": "EV-002", "source_id": "odoo-community-12.0", "revision": "r2", "match": "public match",
               "locations": [{"path": "odoo/api.py", "match": "public match"}]},
    "EV-003": {"id": "EV-003", "source_id": "odoo-forged-ent", "revision": "r3", "confidentiality": "enterprise"},
}


@dataclass(frozen=True)
class _Finding:
    code: str
    file: str
    pointer: str
    message: str
    severity: str = "ERROR"


class EnterpriseIdsTests(unittest.TestCase):
    def test_only_enterprise_kinds_from_the_index(self):
        self.assertEqual(ENT, frozenset({"odoo-enterprise-12.0", "odoo-local-ent"}))

    def test_forged_confidentiality_field_is_ignored(self):
        self.assertNotIn("odoo-community-12.0", ENT)
        self.assertNotIn("odoo-forged-ent", ENT)

    def test_unknown_provenance_gives_no_ids(self):
        self.assertEqual(cv.enterprise_source_ids(None), frozenset())
        self.assertEqual(cv.enterprise_snapshot_ids(None), frozenset())
        self.assertEqual(cv.enterprise_source_ids([]), frozenset())

    def test_snapshot_ids_of_enterprise_entries(self):
        self.assertEqual(cv.enterprise_snapshot_ids(INDEX), frozenset({"ss-e1e1e1e1e1e1", "ss-e2e2e2e2e2e2"}))

    def test_entry_without_source_id_is_skipped(self):
        self.assertEqual(cv.enterprise_source_ids({"x": {"kind": "GIT_ENTERPRISE"}}), frozenset())


class RecordTests(unittest.TestCase):
    def test_evidence_row_by_source_id(self):
        self.assertTrue(cv.is_enterprise_record(EVIDENCE["EV-001"], ENT))
        self.assertFalse(cv.is_enterprise_record(EVIDENCE["EV-002"], ENT))

    def test_forged_field_on_evidence_row_is_ignored(self):
        self.assertFalse(cv.is_enterprise_record(EVIDENCE["EV-003"], ENT))
        public_claim = {**EVIDENCE["EV-001"], "confidentiality": "public"}
        self.assertTrue(cv.is_enterprise_record(public_claim, ENT))

    def test_rule_is_enterprise_through_its_evidence(self):
        rule = {"id": "12-13.python.x", "evidence": ["EV-002", "EV-001"]}
        self.assertTrue(cv.is_enterprise_record(rule, ENT, EVIDENCE))
        self.assertFalse(cv.is_enterprise_record({"id": "r", "evidence": ["EV-002"]}, ENT, EVIDENCE))

    def test_rule_with_unknown_or_no_evidence_is_not_enterprise(self):
        self.assertFalse(cv.is_enterprise_record({"id": "r", "evidence": ["EV-999"]}, ENT, EVIDENCE))
        self.assertFalse(cv.is_enterprise_record({"id": "r", "evidence": []}, ENT, EVIDENCE))
        self.assertFalse(cv.is_enterprise_record({"id": "r", "evidence": ["EV-001"]}, ENT))  # no index: no evidence

    def test_no_ids_means_nothing_is_enterprise(self):
        self.assertFalse(cv.is_enterprise_record(EVIDENCE["EV-001"], frozenset()))
        self.assertFalse(cv.is_enterprise_record(None, ENT))


class StubTests(unittest.TestCase):
    def test_stub_has_only_safe_fields(self):
        stub = cv.redact_evidence_view(EVIDENCE["EV-001"], ENT)
        self.assertEqual(stub, {"id": "EV-001", "source_id": "odoo-enterprise-12.0", "revision": "r1",
                                "confidentiality": "enterprise"})

    def test_stub_leaks_no_location_match_path_or_url(self):
        text = json.dumps(cv.redact_evidence_view(EVIDENCE["EV-001"], ENT))
        for secret in ("SECRET_MATCH", "SECRET_DESC", "enterprise/secret.py", "github.com", "locations", "url", "match"):
            self.assertNotIn(secret, text)

    def test_public_row_comes_back_as_the_same_object(self):
        row = EVIDENCE["EV-002"]
        self.assertIs(cv.redact_evidence_view(row, ENT), row)

    def test_ledger_change_redacts_only_enterprise_locations(self):
        record = {"change_id": "CH-1", "subject_key": "m::f", "detail": {"from": "SECRET_DETAIL"},
                  "locations": [{"snapshot_id": "ss-e1e1e1e1e1e1", "path": "enterprise/x.py", "line": 3,
                                 "sha256": "a" * 64},
                                {"snapshot_id": "ss-c1c1c1c1c1c1", "path": "odoo/y.py", "line": 4,
                                 "sha256": "b" * 64}]}
        view = cv.redact_change_record(record, cv.enterprise_snapshot_ids(INDEX))
        text = json.dumps(view)
        self.assertNotIn("SECRET_DETAIL", text)
        self.assertNotIn("enterprise/x.py", text)
        self.assertIn("odoo/y.py", text)  # the public location is untouched
        self.assertEqual(view["locations"][0]["snapshot_id"], "ss-e1e1e1e1e1e1")
        self.assertIs(record["locations"][0]["path"] == "enterprise/x.py", True)  # input not mutated

    def test_public_ledger_change_is_unchanged(self):
        record = {"change_id": "CH-2", "detail": {"from": "x"}, "locations": [{"snapshot_id": "ss-c1c1c1c1c1c1",
                                                                              "path": "odoo/y.py"}]}
        self.assertIs(cv.redact_change_record(record, cv.enterprise_snapshot_ids(INDEX)), record)


class RefreshAndFindingsTests(unittest.TestCase):
    def test_refresh_candidates_of_enterprise_evidence_are_removed(self):
        report = {"checked": 2, "demoted_evidence": [], "demoted_rules": [], "results": [
            {"id": "EV-001", "location_index": 0, "result": "missing", "old_line": 3, "new_line": None,
             "candidates": ["enterprise/secret.py"]},
            {"id": "EV-002", "location_index": 0, "result": "missing", "old_line": 3, "new_line": None,
             "candidates": ["odoo/api.py"]}]}
        view = cv.redact_refresh_report(report, EVIDENCE, ENT)
        self.assertEqual(view["results"][0]["candidates"], [])
        self.assertEqual(view["results"][1]["candidates"], ["odoo/api.py"])
        self.assertEqual(report["results"][0]["candidates"], ["enterprise/secret.py"])  # input not mutated
        self.assertNotIn("enterprise/secret.py", json.dumps(view))

    def test_refresh_report_without_enterprise_ids_is_unchanged(self):
        report = {"results": [{"id": "EV-001", "candidates": ["enterprise/secret.py"]}]}
        self.assertIs(cv.redact_refresh_report(report, EVIDENCE, frozenset()), report)

    def test_findings_of_enterprise_files_keep_code_file_and_pointer(self):
        findings = [_Finding("E001", "evidence/EV-001.json", "/revision", "'SECRET_MATCH' does not match pattern"),
                    _Finding("E001", "evidence/EV-002.json", "/revision", "public message")]
        out = cv.redact_kb_findings(_KB(), findings, INDEX)
        self.assertEqual((out[0].code, out[0].file, out[0].pointer), ("E001", "evidence/EV-001.json", "/revision"))
        self.assertEqual(out[0].message, cv.WITHHELD_MESSAGE)
        self.assertNotIn("SECRET_MATCH", out[0].message)
        self.assertEqual(out[1], findings[1])

    def test_findings_without_provenance_are_unchanged(self):
        findings = [_Finding("E001", "evidence/EV-001.json", "/x", "m")]
        self.assertIs(cv.redact_kb_findings(_KB(), findings, None), findings)


class _KB:
    evidence = EVIDENCE
    evidence_files = {"EV-001": "evidence/EV-001.json", "EV-002": "evidence/EV-002.json",
                      "EV-003": "evidence/EV-003.json"}


class ActiveReleaseTests(unittest.TestCase):
    def test_no_active_release_means_no_enterprise_snapshots(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(cv.active_enterprise_snapshot_ids(home), frozenset())


if __name__ == "__main__":
    unittest.main()
