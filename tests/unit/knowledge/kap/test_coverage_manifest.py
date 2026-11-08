"""TST-011-067 (REQ-KAP-035, REQ-KAP-034): coverage manifest builder and consistency check.

The fixture uses the real `Ledger` (T042/T043) and `FileAccounting` (T044). The consistency check recomputes metrics,
summaries, cross-checks, gates and the completeness decision from the ledger and accounting, and compares them with the
stored manifest. The manifest digest is part of the release digest (release/manifest.py).
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.coverage import manifest as cm
from odooflux.knowledge.extract.accounting import FileAccounting
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.release.canonical import digest_obj, write_json_file
from odooflux.knowledge.release.manifest import build_manifest

TS = "2026-11-08T10:00:00Z"
SNAP_FROM = {"snapshot_id": "ss-" + "ab" * 6, "snapshot_digest": "ab" * 32,
             "entries": [{"path": "addons/m/a.py", "sha256": "1" * 64, "size": 10, "kind": "python"}]}
SNAP_TO = {"snapshot_id": "ss-" + "cd" * 6, "snapshot_digest": "cd" * 32,
           "entries": [{"path": "addons/m/a.py", "sha256": "2" * 64, "size": 11, "kind": "python"},
                       {"path": "addons/m/b.py", "sha256": "3" * 64, "size": 5, "kind": "python"}]}
META = {
    "label": "community-16.0-17.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": TS, "host_free": True},
}


def _data():
    ledger = Ledger.create("16-17", SNAP_FROM, SNAP_TO, [
        {"domain": "python_orm", "kind": "field", "subject_key": "sale.demo.order::field::amount",
         "class": "SIGNATURE_CHANGED", "detail": {"from": "Float", "to": "Monetary"},
         "locations": [{"snapshot_id": SNAP_TO["snapshot_id"], "path": "addons/m/a.py", "line": 3,
                        "sha256": "2" * 64}],
         "proposed_by": "DETERMINISTIC"},
        {"domain": "manifest", "kind": "dependency", "subject_key": "m::depends::account",
         "class": "ADDED", "detail": {}, "locations": [
             {"snapshot_id": SNAP_TO["snapshot_id"], "path": "addons/m/b.py", "line": 1, "sha256": "3" * 64}],
         "proposed_by": "DETERMINISTIC"},
    ], clock=lambda: TS)
    cids = sorted(ledger.unresolved())
    ledger.mutate(cids[0], actor="MANUAL", action="set_disposition", from_value="UNRESOLVED",
                  to_value="RULE_CREATED",
                  update={"disposition": "RULE_CREATED",
                          "disposition_data": {"rule_ids": ["R-1"], "evidence_ids": ["EV-1"], "rationale": None,
                                               "reviewer": None, "decided_at": TS}})
    ledger.mutate(cids[1], actor="MANUAL", action="set_disposition", from_value="UNRESOLVED",
                  to_value="NO_CUSTOM_MODULE_IMPACT",
                  update={"disposition": "NO_CUSTOM_MODULE_IMPACT",
                          "disposition_data": {"rule_ids": [], "evidence_ids": [], "rationale": "dependency only",
                                               "reviewer": "reviewer", "decided_at": TS}})
    accounting = FileAccounting.for_pair("16-17", SNAP_FROM, SNAP_TO)
    for path in ("addons/m/a.py", "addons/m/b.py"):
        accounting.set_state(path, "ANALYZED")
    return {
        "declared_scope": {"sources": ["odoo-community-16.0"], "modules": ["m"], "steps": ["16-17"],
                           "domains": ["python_orm", "manifest"]},
        "inventory": [{"source_id": "odoo-community-16.0", "file_count": 2, "snapshot_digest": "ab" * 32}],
        "sources": [{"source_id": "odoo-community-16.0", "required": True, "status": "VERIFIED"}],
        "accounting": [accounting.document()],
        "changes": ledger.records(),
        "evidence_index": {"EV-1": {"valid": True, "official": True, "origin": "KAP_DETERMINISTIC"}},
        "release_rules": [{"id": "R-1", "in_release_delta": True, "validation_passed": True, "origin": "GENERATED",
                           "maturity": "DETECT_ONLY", "safety_passed": True, "evidence_ids": ["EV-1"]}],
        "declared_transitions": [{"step": "16-17", "sources_verified": True, "accounting_complete": True,
                                  "ledger_present": True}],
        "rule_findings": [],
        "safety_findings": [],
        "redaction_findings": [],
    }


def _build(data=None, **kwargs):
    return cm.build_coverage_manifest(data or _data(), checked_at=TS, tool_version="1.0.0",
                                      schema_versions={"coverage_manifest": "1"}, **kwargs)


def _resigned(manifest: dict) -> dict:
    """Recompute manifest_digest so only the tampered content is wrong, not the digest."""
    body = {k: v for k, v in manifest.items() if k != "manifest_digest"}
    return {**body, "manifest_digest": digest_obj(body)}


class CoverageManifestTests(unittest.TestCase):
    def test_manifest_counts_match_ledger_and_accounting(self):
        data = _data()
        manifest = _build(data)
        self.assertEqual(manifest["completeness"], "COMPLETE")
        self.assertEqual([g["status"] for g in manifest["gates"] if g["blocking"]], ["PASS"] * 9)

        by_id = {item["id"]: item for item in manifest["metrics"]}
        self.assertEqual(by_id["M3"]["denominator"], len(data["changes"]))
        self.assertEqual(by_id["M4"]["denominator"], len(data["changes"]))
        self.assertEqual(by_id["M2"]["denominator"], sum(len(d["files"]) for d in data["accounting"]))
        self.assertEqual(by_id["M2"]["numerator"], 2)
        self.assertEqual((by_id["M5"]["numerator"], by_id["M5"]["denominator"]), (1, 1))

        summary = manifest["file_accounting_summary"][0]
        self.assertEqual(summary["totals"], data["accounting"][0]["totals"])
        self.assertEqual(summary["independent_count"], data["accounting"][0]["independent_count"])
        self.assertEqual(cm.check_consistency(manifest, data), [])
        self.assertEqual(manifest["manifest_digest"], digest_obj({k: v for k, v in manifest.items()
                                                                  if k != "manifest_digest"}))

    def test_manifest_inconsistency_detected(self):
        data = _data()
        good = _build(data)
        self.assertEqual(cm.check_consistency(good, data), [])

        # a metric numerator changed, digest recomputed so only the content is wrong
        tampered = copy.deepcopy(good)
        tampered["metrics"][1]["numerator"] = 1
        tampered = _resigned(tampered)
        findings = cm.check_consistency(tampered, data)
        self.assertTrue(any("M2" in f for f in findings), findings)

        # a stored completeness that the gates do not support
        forged = copy.deepcopy(good)
        forged["gates"][1]["status"] = "PASS"
        forged["gates"][1]["reason_codes"] = []
        forged["completeness"] = "COMPLETE"
        forged = _resigned(forged)
        data_pending = copy.deepcopy(data)
        data_pending["accounting"][0]["files"][0]["state"] = "PENDING"
        data_pending["accounting"][0]["totals"]["PENDING"] = 1
        data_pending["accounting"][0]["totals"]["ANALYZED"] = 1
        self.assertTrue(cm.check_consistency(forged, data_pending))

        # a digest that does not match the content
        stale = copy.deepcopy(good)
        stale["limits"] = ["edited after the build"]
        self.assertTrue(any("digest" in f for f in cm.check_consistency(stale, data)))

        # a summary that disagrees with the accounting documents
        summary_bad = copy.deepcopy(good)
        summary_bad["file_accounting_summary"][0]["totals"]["ANALYZED"] = 0
        self.assertTrue(cm.check_consistency(_resigned(summary_bad), data))

    def test_manifest_in_release_digest(self):
        data = _data()
        manifest = _build(data)
        later = _build(data, limits=())  # same content
        self.assertEqual(manifest["manifest_digest"], later["manifest_digest"])
        other = _build(data | {"redaction_findings": ["knowledge/evidence/EV-9.json"]})
        self.assertNotEqual(other["manifest_digest"], manifest["manifest_digest"])

        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "kb"
            (tree / "knowledge" / "rules").mkdir(parents=True)
            (tree / "knowledge" / "rules" / "R-1.json").write_text("{}\n", encoding="utf-8")
            coverage_path = tree / "coverage" / "coverage-manifest.json"
            coverage_path.parent.mkdir(parents=True)
            write_json_file(coverage_path, manifest)
            release_a = build_manifest(tree, {**META, "coverage_manifest_digest": manifest["manifest_digest"]})
            self.assertIn("coverage/coverage-manifest.json", [f["path"] for f in release_a["files"]])

            # the coverage manifest digest is a release digest input (meta field) ...
            release_b = build_manifest(tree, {**META, "coverage_manifest_digest": other["manifest_digest"]})
            self.assertNotEqual(release_a["release_digest"], release_b["release_digest"])

            # ... and so are the coverage file bytes themselves
            write_json_file(coverage_path, other)
            release_c = build_manifest(tree, {**META, "coverage_manifest_digest": manifest["manifest_digest"]})
            self.assertNotEqual(release_a["release_digest"], release_c["release_digest"])
            self.assertEqual(json.loads(coverage_path.read_text(encoding="utf-8"))["manifest_digest"],
                             other["manifest_digest"])

    def test_blocking_gate_not_run_fails_build(self):
        data = _data()
        data["redaction_findings"] = None  # G-SECRETS cannot run: blocking NOT_RUN gives FAILED
        self.assertEqual(_build(data)["completeness"], "FAILED")
        data = _data()
        data["sources"] = [{"source_id": "odoo-community-16.0", "required": True, "status": "FAILED"}]
        self.assertEqual(_build(data)["completeness"], "FAILED")

    # M8 (ITEM 2, branch b of the owner correction): reported as a fraction and checked for consistency. No gate reads
    # it, so these tests assert the metric and the tamper check only; the completeness effect is an open question in
    # contracts/coverage-and-gates.md ("Open question (M8)").
    def test_m8_reports_transition_fraction(self):
        data = _data()
        data["declared_transitions"] = [
            {"step": "16-17", "sources_verified": True, "accounting_complete": True, "ledger_present": True},
            {"step": "17-18", "sources_verified": True, "accounting_complete": True, "ledger_present": False}]
        m8 = {item["id"]: item for item in _build(data)["metrics"]}["M8"]
        self.assertEqual((m8["numerator"], m8["denominator"], m8["status"]), (1, 2, "MEASURED"))

    def test_m8_zero_transitions_not_applicable(self):
        data = _data()
        data["declared_transitions"] = []
        m8 = {item["id"]: item for item in _build(data)["metrics"]}["M8"]
        self.assertEqual((m8["denominator"], m8["status"], m8["per_mille"]), (0, "NOT_APPLICABLE", None))

    def test_m8_tampered_numerator_is_inconsistent(self):
        data = _data()
        data["declared_transitions"] = [
            {"step": "16-17", "sources_verified": True, "accounting_complete": True, "ledger_present": True},
            {"step": "17-18", "sources_verified": True, "accounting_complete": True, "ledger_present": False}]
        manifest = _build(data)
        for item in manifest["metrics"]:
            if item["id"] == "M8":
                item["numerator"] = 2
        findings = cm.check_consistency(_resigned(manifest), data)
        self.assertTrue(any(f.startswith("M8 differs") for f in findings), findings)


if __name__ == "__main__":
    unittest.main()
