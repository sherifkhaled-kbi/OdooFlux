"""Additive report-model fields for feature 009 (summary, ai_usage, provisional, L4/L5 and runtime pass-through).

Backwards compatible: schema_version stays 1.0.0 and the original keys are unchanged (FR-001, REQ-REP-001)."""

import unittest

from ._setup import SRC  # noqa: F401
from . import fixtures
from .helpers import build


def _raw_counts(name):
    """Independent recount straight from the stored issues (not through the model)."""
    state, _ = fixtures.scenarios()[name]
    out = {"open": 0, "fixed": 0, "rejected": 0, "needs_review": 0}
    sev = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    open_sev = dict(sev)
    for m in state["modules"]:
        for i in m["report"]["issues"]:
            if i["fix_applied"]:
                st = "fixed"
            elif i["rejection_reason"]:
                st = "rejected"
            elif not i["auto_fixable"]:
                st = "needs_review"
            else:
                st = "open"
            out[st] += 1
            sev[i["severity"]] += 1
            if st in ("open", "needs_review"):
                open_sev[i["severity"]] += 1
    return out, sev, open_sev


class SummaryTests(unittest.TestCase):
    def test_summary_matches_independent_recount(self):
        for name in fixtures.scenarios():
            report = build(name)
            by_status, by_sev, open_sev = _raw_counts(name)
            summary = report["summary"]
            self.assertEqual(summary["findings_by_status"], by_status, name)
            self.assertEqual(summary["findings"], {k.lower(): v for k, v in by_sev.items()}, name)
            self.assertEqual(summary["open_findings"], {k.lower(): v for k, v in open_sev.items()}, name)

    def test_module_status_counts_and_edits(self):
        report = build("mixed")
        by = report["summary"]["modules_by_status"]
        self.assertEqual(sum(by.values()), len(report["modules"]))
        self.assertEqual(by["BLOCKED"], 1)
        self.assertEqual(report["summary"]["edits"], {"applied": 1, "rejected": 1})

    def test_original_keys_unchanged(self):
        report = build("static_validated")
        self.assertEqual(report["schema_version"], "1.0.0")
        for key in ("run", "modules", "verification_scope", "recovery", "severities"):
            self.assertIn(key, report)


class OptionalSectionTests(unittest.TestCase):
    def test_ai_usage_always_present_and_flagged(self):
        self.assertEqual(build("static_validated")["ai_usage"]["enabled"], False)
        ai = build("ai_enabled")["ai_usage"]
        self.assertTrue(ai["enabled"])
        self.assertEqual(ai["providers"][0]["requests"], 7)

    def test_provisional_only_when_supplied(self):
        self.assertNotIn("provisional", build("static_validated"))
        prov = build("provisional")["provisional"]
        self.assertTrue(prov["active"])
        self.assertIn("PROVISIONAL", prov["labels"][0])

    def test_evidence_expanded_with_urls_when_known(self):
        findings = build("needs_review")["modules"][0]["findings"]
        evidence = [e for f in findings for e in f["evidence"]]
        self.assertIn({"id": "EV-109", "url": fixtures.EVIDENCE_URLS["EV-109"]}, evidence)
        # unknown ids stay plain ids: a link is never invented
        hostile = build("hostile")["modules"][0]["findings"][0]["evidence"]
        self.assertTrue(any(isinstance(e, dict) and e["id"] == "EV-110" for e in hostile))
        self.assertTrue(any(isinstance(e, str) and e.startswith("EV-<img") for e in hostile))

    def test_runtime_layers_honoured_when_recorded(self):
        report = build("install_verified")
        module = report["modules"][0]
        self.assertEqual(module["status"], "INSTALL_VERIFIED")
        self.assertEqual(module["layers"]["L4"]["outcome"], "PASS")
        self.assertEqual(module["runtime"]["image"], "odoo:18.0")
        self.assertEqual(report["verification_scope"]["layers_run"], [1, 2, 3, 4])

    def test_verified_success_reachable(self):
        module = build("verified_success")["modules"][0]
        self.assertEqual(module["status"], "VERIFIED_SUCCESS")
        self.assertIn("summary", module["behavior"])

    def test_unrun_layers_never_pass(self):
        module = build("static_validated")["modules"][0]
        self.assertNotEqual(module["layers"]["L4"]["outcome"], "PASS")
        self.assertNotEqual(module["layers"]["L5"]["outcome"], "PASS")
        self.assertNotIn("runtime", module)

    def test_module_blocked_before_analysis_shows_no_pass_for_unrun_layers(self):
        layers = build("blocked")["modules"][0]["layers"]
        for layer in ("L1", "L2", "L3", "L4", "L5"):
            self.assertNotEqual(layers[layer]["outcome"], "PASS", layer)
        self.assertEqual(layers["L1"]["reason"], "module_blocked_before_analysis")

    def test_layer_outcome_counts_in_scope(self):
        scope = build("mixed")["verification_scope"]["layer_outcomes"]
        self.assertEqual(scope["L3"]["UNAVAILABLE"], 1)
        self.assertEqual(scope["L3"]["FAIL"], 0)
        self.assertEqual(sum(scope["L1"].values()), 4)

    def test_l3_unavailable_is_not_fail_and_not_pass(self):
        module = build("blocked")["modules"][0]
        self.assertEqual(module["layers"]["L3"]["outcome"], "UNAVAILABLE")
        self.assertEqual(module["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
