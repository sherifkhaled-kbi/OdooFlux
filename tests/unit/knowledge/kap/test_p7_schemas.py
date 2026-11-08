"""TST-011-063 (REQ-KAP-035, REQ-KAP-034): coverage_manifest and gate_result schemas.

Samples are built in code. Each schema must accept its valid sample and reject a missing key, an unknown key, and a
malformed value. The stdlib validator has no conditional keywords (if/then), so two conditional rules are checked here
by `_partial_problems` and `_recall_problems`, which mirror the contract (coverage-and-gates.md). The same rules are
enforced by the decision code in `knowledge/coverage/gates.py` (T066) and `knowledge/coverage/manifest.py` (T067).
"""

import copy
import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SCHEMAS = KNOWLEDGE_ROOT / "schemas"
SHA = "c" * 64
TS = "2026-11-08T10:00:00Z"
METRIC_IDS = [f"M{i}" for i in range(1, 9)]
GATE_IDS = ["G-SRC", "G-FILES", "G-CLASS", "G-DISP", "G-EVID", "G-MANIFEST", "G-RULES", "G-SAFE", "G-XCHECK",
            "G-SECRETS"]


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _gate(gate_id: str = "G-SRC") -> dict:
    return {"gate_id": gate_id, "name": "sources verified", "blocking": True, "status": "PASS",
            "reason_codes": [], "offenders": [], "offenders_total": 0, "checked_at": TS}


def _metric(metric_id: str) -> dict:
    return {"id": metric_id, "name": "metric " + metric_id, "numerator": 1, "denominator": 2,
            "status": "MEASURED", "denominator_definition": "all things", "per_mille": 500, "breakdown": {}}


def _coverage_manifest() -> dict:
    return {
        "declared_scope": {"sources": ["odoo-community-17.0"], "modules": ["sale_demo"], "steps": ["16-17"],
                           "domains": ["python_orm"]},
        "inventory": [{"source_id": "odoo-community-17.0", "file_count": 12, "snapshot_digest": SHA}],
        "file_accounting_summary": [{"step": "16-17", "from_snapshot": "ss-" + "ab" * 6,
                                     "to_snapshot": "ss-" + "cd" * 6,
                                     "totals": {"PENDING": 0, "ANALYZED": 10, "EXCLUDED": 1, "UNSUPPORTED": 1,
                                                "FAILED": 0},
                                     "independent_count": 12}],
        "metrics": [_metric(m) for m in METRIC_IDS],
        "crosschecks": [
            {"id": "XC-UPGRADE", "status": "PASS", "benchmark_id": "upgrade-scripts:16-17", "benchmark_size": 3,
             "detail": "3 of 3 referenced changes found",
             "recall": {"found": 3, "referenced": 3, "benchmark_id": "upgrade-scripts:16-17", "benchmark_size": 3}},
            {"id": "XC-INDEP", "status": "PASS", "benchmark_id": None, "benchmark_size": None,
             "detail": "file counts equal"},
        ],
        "gates": [_gate(g) for g in GATE_IDS],
        "limits": [],
        "completeness": "COMPLETE",
        "tool": {"version": "1.0.0", "schema_versions": {"coverage_manifest": "1"}},
        "manifest_digest": SHA,
    }


def _partial_problems(doc: dict) -> list:
    """Contract rule: PARTIAL needs non-empty limits that name each failed partial gate."""
    if doc.get("completeness") != "PARTIAL":
        return []
    limits = doc.get("limits") or []
    if not limits or any(not str(item).strip() for item in limits):
        return [("/limits", "PARTIAL requires non-empty limits")]
    return []


def _recall_problems(doc: dict) -> list:
    """Contract rule: a recall figure always names its benchmark (checked on the recall object by the schema;
    this helper also rejects a recall attached to a check whose item-level benchmark_id is null)."""
    out = []
    for index, item in enumerate(doc.get("crosschecks") or []):
        if "recall" in item and not item.get("benchmark_id"):
            out.append((f"/crosschecks/{index}", "recall without benchmark_id"))
    return out


class CoverageManifestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load("coverage_manifest")

    def test_valid_samples(self):
        doc = _coverage_manifest()
        self.assertEqual(v.check(doc, self.schema), [])
        self.assertEqual(_partial_problems(doc), [])
        self.assertEqual(_recall_problems(doc), [])

        partial = copy.deepcopy(doc)
        partial["completeness"] = "PARTIAL"
        partial["limits"] = ["G-FILES: 1 file FAILED (PARSE_ERROR) in 16-17"]
        self.assertEqual(v.check(partial, self.schema), [])
        self.assertEqual(_partial_problems(partial), [])

    def test_missing_field_fails(self):
        doc = _coverage_manifest()
        del doc["gates"]
        self.assertTrue(v.check(doc, self.schema))

    def test_unknown_field_fails(self):
        doc = _coverage_manifest()
        doc["overall_score"] = 97
        self.assertTrue(any("unknown key" in m for _, m in v.check(doc, self.schema)))

    def test_metric_id_and_status_closed(self):
        doc = _coverage_manifest()
        doc["metrics"][0]["id"] = "M9"
        self.assertTrue(v.check(doc, self.schema))
        doc = _coverage_manifest()
        doc["metrics"][0]["status"] = "COMPLETE"
        self.assertTrue(v.check(doc, self.schema))

    def test_metric_count_is_eight(self):
        doc = _coverage_manifest()
        doc["metrics"] = doc["metrics"][:7]
        self.assertTrue(v.check(doc, self.schema))

    def test_float_numerator_rejected(self):
        doc = _coverage_manifest()
        doc["metrics"][1]["numerator"] = 0.5
        self.assertTrue(v.check(doc, self.schema))

    def test_partial_requires_limits(self):
        doc = _coverage_manifest()
        doc["completeness"] = "PARTIAL"
        doc["limits"] = []
        self.assertTrue(_partial_problems(doc))
        doc["limits"] = ["   "]
        self.assertTrue(_partial_problems(doc))

    def test_recall_requires_benchmark_id(self):
        doc = _coverage_manifest()
        del doc["crosschecks"][0]["recall"]["benchmark_id"]
        self.assertTrue(v.check(doc, self.schema))

        doc = _coverage_manifest()
        doc["crosschecks"][0]["recall"]["benchmark_id"] = ""
        self.assertTrue(v.check(doc, self.schema))

        doc = _coverage_manifest()
        doc["crosschecks"][0]["benchmark_id"] = None
        self.assertTrue(_recall_problems(doc))


class GateResultSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load("gate_result")

    def test_valid_samples(self):
        self.assertEqual(v.check(_gate("G-FILES"), self.schema), [])
        failed = _gate("G-DISP")
        failed.update({"status": "FAIL", "reason_codes": ["DISP_UNRESOLVED"], "offenders": ["CH-0123456789abcdef"],
                       "offenders_total": 1})
        self.assertEqual(v.check(failed, self.schema), [])

    def test_missing_and_unknown_fail(self):
        doc = _gate()
        del doc["offenders_total"]
        self.assertTrue(v.check(doc, self.schema))
        doc = _gate()
        doc["score"] = 1
        self.assertTrue(v.check(doc, self.schema))

    def test_status_and_gate_id_closed(self):
        doc = _gate()
        doc["status"] = "OK"
        self.assertTrue(v.check(doc, self.schema))
        doc = _gate()
        doc["gate_id"] = "G-NEW"
        self.assertTrue(v.check(doc, self.schema))

    def test_all_gate_ids_accepted(self):
        for gate_id in GATE_IDS:
            self.assertEqual(v.check(_gate(gate_id), self.schema), [], gate_id)


if __name__ == "__main__":
    unittest.main()
