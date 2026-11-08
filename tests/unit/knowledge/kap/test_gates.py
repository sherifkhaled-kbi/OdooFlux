"""TST-011-066 (REQ-KAP-034): release gates and the completeness decision.

One test per gate. A blocking gate that fails blocks COMPLETE. PARTIAL is allowed only when every failing blocking gate
is in its allowed-partial set and the limits name each of those gates. A required source is never partial-able.
"""

import unittest

from odooflux.knowledge.coverage import gates as g
from odooflux.knowledge.extract.accounting import FileAccounting

SS_FROM = "ss-" + "ab" * 6
SS_TO = "ss-" + "cd" * 6
TS = "2026-11-08T10:00:00Z"


def _accounting(states, independent_count=None):
    """states: path -> (state, reason_code)."""
    acc = FileAccounting("16-17", SS_FROM, SS_TO, {p: "modified" for p in states}, independent_count=independent_count)
    for path, (state, reason) in states.items():
        if state != "PENDING":  # PENDING is the initial state of every file
            acc.set_state(path, state, reason_code=reason)
    return acc.document()


def _change(cid, path, cls="ADDED", disposition="RULE_CREATED", evidence=("EV-1",), rules=("R-1",)):
    return {"change_id": cid, "class": cls, "disposition": disposition,
            "locations": [{"snapshot_id": SS_TO, "path": path, "line": 1, "sha256": "a" * 64}],
            "disposition_data": {"evidence_ids": list(evidence), "rule_ids": list(rules)}}


def _clean():
    """Inputs under which every blocking gate passes."""
    return {
        "sources": [{"source_id": "odoo-community-17.0", "required": True, "status": "VERIFIED"}],
        "accounting": [_accounting({"a.py": ("ANALYZED", None), "b.py": ("ANALYZED", None)}, independent_count=2)],
        "changes": [_change("CH-0000000000000001", "a.py"), _change("CH-0000000000000002", "b.py",
                                                                 cls="REMOVED", disposition="NO_CUSTOM_MODULE_IMPACT",
                                                                 evidence=(), rules=())],
        "evidence_index": {"EV-1": {"valid": True, "official": True, "origin": "KAP_DETERMINISTIC"}},
        "release_rules": [{"id": "R-1", "in_release_delta": True, "validation_passed": True, "origin": "GENERATED",
                           "maturity": "DETECT_ONLY", "safety_passed": True, "evidence_ids": ["EV-1"]}],
        "manifest": {"unresolved_change_ids": [], "change_count": 2},
        "consistency_findings": [],
        "rule_findings": [],
        "safety_findings": [],
        "redaction_findings": [],
        "crosschecks": [{"id": "XC-INDEP", "status": "PASS", "benchmark_id": None, "benchmark_size": None,
                         "detail": "ok"}],
    }


def _run(data, strict=False):
    return {gate["gate_id"]: gate for gate in g.evaluate_gates(data, checked_at=TS, strict_xcheck=strict)}


class GateTests(unittest.TestCase):
    def test_clean_inputs_pass_and_complete(self):
        gates = _run(_clean())
        for gate_id in ("G-SRC", "G-FILES", "G-CLASS", "G-DISP", "G-EVID", "G-MANIFEST", "G-RULES", "G-SAFE",
                        "G-SECRETS"):
            self.assertEqual(gates[gate_id]["status"], "PASS", gate_id)
            self.assertTrue(gates[gate_id]["blocking"], gate_id)
        self.assertEqual(gates["G-XCHECK"]["status"], "PASS")
        self.assertFalse(gates["G-XCHECK"]["blocking"])
        self.assertEqual(g.decide(list(gates.values()))["completeness"], "COMPLETE")

    def test_gate_g_src(self):
        data = _clean()
        data["sources"] = [{"source_id": "odoo-community-17.0", "required": True, "status": "FAILED"}]
        gate = _run(data)["G-SRC"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("SOURCE_REQUIRED_NOT_VERIFIED", gate["reason_codes"])
        self.assertEqual(gate["offenders"], ["odoo-community-17.0"])
        # an optional source that is not verified is partial-able, a required one is not
        data = _clean()
        data["sources"].append({"source_id": "oca-web-17.0", "required": False, "status": "FAILED"})
        gate = _run(data)["G-SRC"]
        self.assertEqual(gate["reason_codes"], ["OPTIONAL_SOURCE_NOT_VERIFIED"])

    def test_gate_g_files(self):
        data = _clean()
        data["accounting"] = [_accounting({"a.py": ("PENDING", None)}, independent_count=1)]
        gate = _run(data)["G-FILES"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("FILES_PENDING", gate["reason_codes"])

        data = _clean()
        data["accounting"] = [_accounting({"a.py": ("ANALYZED", None)}, independent_count=2)]
        gate = _run(data)["G-FILES"]
        self.assertIn("FILES_INV3", gate["reason_codes"])  # one changed file never accounted for

        data = _clean()
        data["accounting"] = [_accounting({"a.py": ("ANALYZED", None), "b.py": ("UNSUPPORTED", "NO_PARSER")},
                                          independent_count=2)]
        gate = _run(data)["G-FILES"]
        self.assertEqual(gate["reason_codes"], ["FILES_UNSUPPORTED"])

    def test_gate_g_class(self):
        data = _clean()
        data["accounting"] = [_accounting({"a.py": ("ANALYZED", None), "z.py": ("FAILED", "PARSE_ERROR")},
                                          independent_count=2)]
        gate = _run(data)["G-CLASS"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["offenders"], ["z.py"])

        # a FAILED file made visible by an UNKNOWN change is not a hidden classification failure
        data["changes"].append(_change("CH-0000000000000009", "z.py", cls="UNKNOWN", disposition="UNRESOLVED",
                                       evidence=(), rules=()))
        data["manifest"] = {"unresolved_change_ids": ["CH-0000000000000009"], "change_count": 3}
        self.assertEqual(_run(data)["G-CLASS"]["status"], "PASS")

    def test_gate_g_disp(self):
        data = _clean()
        data["changes"].append(_change("CH-0000000000000003", "c.py", disposition="UNRESOLVED", cls="ADDED",
                                       evidence=(), rules=()))
        data["manifest"] = {"unresolved_change_ids": [], "change_count": 3}
        gate = _run(data)["G-DISP"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("DISP_UNRESOLVED_NOT_IN_MANIFEST", gate["reason_codes"])

        data["manifest"] = {"unresolved_change_ids": ["CH-0000000000000003"], "change_count": 2}
        gate = _run(data)["G-DISP"]
        self.assertIn("DISP_COUNT_MISMATCH", gate["reason_codes"])

        data["manifest"] = {"unresolved_change_ids": ["CH-0000000000000003"], "change_count": 3}
        gate = _run(data)["G-DISP"]
        self.assertEqual(gate["reason_codes"], ["DISP_UNRESOLVED"])

    def test_gate_g_evid(self):
        data = _clean()
        data["changes"][0]["disposition_data"]["evidence_ids"] = []
        gate = _run(data)["G-EVID"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["offenders"], ["CH-0000000000000001"])

        # FIX_ENABLED rule whose only evidence is unofficial (or AI) does not pass
        data = _clean()
        data["evidence_index"]["EV-2"] = {"valid": True, "official": False, "origin": "KAP_DETERMINISTIC"}
        data["evidence_index"]["EV-3"] = {"valid": True, "official": True, "origin": "AI_PROPOSED"}
        data["release_rules"] = [{"id": "R-9", "in_release_delta": True, "validation_passed": True,
                                  "origin": "GENERATED", "maturity": "FIX_ENABLED", "safety_passed": True,
                                  "evidence_ids": ["EV-2", "EV-3"]}]
        data["changes"][0]["disposition_data"]["rule_ids"] = ["R-9"]
        gate = _run(data)["G-EVID"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("R-9", gate["offenders"])

    def test_gate_g_manifest(self):
        data = _clean()
        data["consistency_findings"] = ["ledger count 3 differs from manifest count 2"]
        gate = _run(data)["G-MANIFEST"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("MANIFEST_INCONSISTENT", gate["reason_codes"])
        self.assertEqual(gate["offenders_total"], 1)

    def test_gate_g_rules(self):
        data = _clean()
        data["release_rules"][0]["validation_passed"] = False
        gate = _run(data)["G-RULES"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("RULES_VALIDATION_FAILED", gate["reason_codes"])

        data = _clean()
        data["rule_findings"] = [{"rule_id": "R-1", "code": "A002"}]
        self.assertEqual(_run(data)["G-RULES"]["status"], "FAIL")

    def test_gate_g_safe(self):
        data = _clean()
        data["safety_findings"] = [{"rule_id": "R-1", "code": "no-official-evidence"}]
        gate = _run(data)["G-SAFE"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("SAFETY_FINDINGS", gate["reason_codes"])

        # INV-5: a non-builtin FIX_ENABLED rule without passing gates
        data = _clean()
        data["release_rules"].append({"id": "R-7", "in_release_delta": False, "validation_passed": True,
                                      "origin": "GENERATED", "maturity": "FIX_ENABLED", "safety_passed": False,
                                      "evidence_ids": []})
        gate = _run(data)["G-SAFE"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["offenders"], ["R-7"])

    def test_gate_g_secrets(self):
        data = _clean()
        data["redaction_findings"] = ["knowledge/evidence/EV-7.json"]
        gate = _run(data)["G-SECRETS"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["offenders"], ["knowledge/evidence/EV-7.json"])

    def test_gate_g_xcheck_warns_unless_strict(self):
        data = _clean()
        data["crosschecks"] = [{"id": "XC-UPGRADE", "status": "FAIL", "benchmark_id": "upgrade-scripts:16-17",
                                "benchmark_size": 4, "detail": "3 of 4",
                                "recall": {"found": 3, "referenced": 4, "benchmark_id": "upgrade-scripts:16-17",
                                           "benchmark_size": 4}}]
        gates = _run(data)
        self.assertEqual(gates["G-XCHECK"]["status"], "WARN")
        self.assertFalse(gates["G-XCHECK"]["blocking"])
        self.assertEqual(g.decide(list(gates.values()))["completeness"], "COMPLETE")
        strict = _run(data, strict=True)
        self.assertEqual(strict["G-XCHECK"]["status"], "FAIL")
        self.assertTrue(strict["G-XCHECK"]["blocking"])
        self.assertEqual(g.decide(list(strict.values()))["completeness"], "FAILED")

    def test_partial_requires_limits(self):
        data = _clean()
        data["sources"].append({"source_id": "oca-web-17.0", "required": False, "status": "FAILED"})
        gates = list(_run(data).values())
        self.assertEqual(g.decide(gates, limits=[])["completeness"], "FAILED")
        self.assertEqual(g.decide(gates, limits=["something unrelated"])["completeness"], "FAILED")
        decided = g.decide(gates, limits=["G-SRC: optional source oca-web-17.0 not verified"])
        self.assertEqual(decided["completeness"], "PARTIAL")
        self.assertEqual(decided["partial_gates"], ["G-SRC"])

        # a required source is never partial-able, even with limits
        data = _clean()
        data["sources"] = [{"source_id": "odoo-community-17.0", "required": True, "status": "FAILED"}]
        gates = list(_run(data).values())
        self.assertEqual(g.decide(gates, limits=["G-SRC: required source missing"])["completeness"], "FAILED")

    def test_complete_blocked_on_unaccounted_file(self):
        data = _clean()
        data["accounting"] = [_accounting({"a.py": ("ANALYZED", None), "b.py": ("PENDING", None)},
                                          independent_count=2)]
        gates = list(_run(data).values())
        decided = g.decide(gates, limits=["G-FILES: pending file"])
        self.assertNotEqual(decided["completeness"], "COMPLETE")
        self.assertEqual(decided["completeness"], "FAILED")  # PENDING is not partial-able

    def test_not_run_blocking_gate_blocks_complete(self):
        data = _clean()
        del data["consistency_findings"]
        gates = list(_run(data).values())
        self.assertEqual(_run(data)["G-MANIFEST"]["status"], "NOT_RUN")
        self.assertNotEqual(g.decide(gates)["completeness"], "COMPLETE")


if __name__ == "__main__":
    unittest.main()
