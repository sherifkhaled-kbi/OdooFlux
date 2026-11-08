"""TST-009-006 (REQ-REP-004): SARIF output validates against the vendored SARIF 2.1.0 schema and maps per
contracts/sarif-and-diff.md."""

import json
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import all_goldens, golden
from .schema_validator import sarif_validator


def sarif(model, **kw):
    from odooflux.reporting.exporters.sarif import export_sarif
    return json.loads(export_sarif(model, **kw))


class SarifTests(unittest.TestCase):
    def test_validates_against_sarif_2_1_0_for_every_golden(self):
        validator = sarif_validator()
        for name, model in all_goldens().items():
            for kw in ({}, {"include_fixed": True}, {"exit_code": 1}):
                self.assertEqual(validator.errors(sarif(model, **kw)), [], f"{name} {kw}")

    def test_validator_rejects_a_broken_document(self):
        doc = sarif(golden("mixed"))
        del doc["runs"][0]["tool"]["driver"]["name"]
        self.assertTrue(sarif_validator().errors(doc))

    def test_driver_and_version(self):
        doc = sarif(golden("mixed"))
        self.assertEqual(doc["version"], "2.1.0")
        driver = doc["runs"][0]["tool"]["driver"]
        self.assertEqual(driver["name"], "OdooFlux")
        self.assertRegex(driver["version"], r"^\d+\.\d+\.\d+")

    def test_level_mapping(self):
        results = sarif(golden("mixed"))["runs"][0]["results"]
        level = {r["properties"]["status"] + r["ruleId"]: r["level"] for r in results}
        self.assertEqual(level["NEEDS_REVIEW17-18.py.api"], "error")       # CRITICAL
        self.assertEqual(level["NEEDS_REVIEW17-18.xml.attrs-removed"], "warning")
        self.assertEqual(level["NEEDS_REVIEW17-18.xml.note"], "note")      # INFO

    def test_fixed_omitted_by_default_and_pass_kind_when_included(self):
        model = golden("static_validated")
        default = sarif(model)["runs"][0]["results"]
        self.assertTrue(all(r["properties"]["status"] != "FIXED" for r in default))
        included = sarif(model, include_fixed=True)["runs"][0]["results"]
        fixed = [r for r in included if r["properties"]["status"] == "FIXED"]
        self.assertEqual(len(fixed), 3)
        for r in fixed:
            self.assertEqual(r["kind"], "pass")
            self.assertEqual(r["level"], "none")

    def test_locations_are_relative_to_module_parent_and_one_based(self):
        r = next(r for r in sarif(golden("needs_review"))["runs"][0]["results"])
        loc = r["locations"][0]["physicalLocation"]
        self.assertEqual(loc["artifactLocation"]["uri"], "kbi_hr_extension/views/hr.xml")
        self.assertEqual(loc["region"]["startLine"], 42)

    def test_line_zero_has_no_region(self):
        model = golden("needs_review")
        model["modules"][0]["findings"][0]["line"] = 0
        r = sarif(model)["runs"][0]["results"][0]
        self.assertNotIn("region", r["locations"][0]["physicalLocation"])

    def test_fingerprints_equal_finding_ids_and_are_stable(self):
        model = golden("mixed")
        first = sarif(model)["runs"][0]["results"]
        second = sarif(model)["runs"][0]["results"]
        self.assertEqual(first, second)
        ids = {f["id"] for m in model["modules"] for f in m["findings"] if f["status"] != "FIXED"}
        self.assertEqual({r["partialFingerprints"]["odoofluxFindingId"] for r in first}, ids)

    def test_rules_one_per_rule_id_with_help_uri_and_evidence(self):
        driver = sarif(golden("needs_review"))["runs"][0]["tool"]["driver"]
        rules = {r["id"]: r for r in driver["rules"]}
        self.assertEqual(len(rules), len(driver["rules"]))
        rule = rules["17-18.xml.attrs-removed"]
        self.assertEqual(rule["helpUri"], "https://www.odoo.com/documentation/18.0/developer/reference/backend/views.html")
        self.assertEqual(rule["properties"]["evidence"], ["EV-109", "EV-110"])
        self.assertTrue(rule["shortDescription"]["text"])
        for result in sarif(golden("needs_review"))["runs"][0]["results"]:
            self.assertEqual(driver["rules"][result["ruleIndex"]]["id"], result["ruleId"])

    def test_no_help_uri_invented_without_evidence_url(self):
        model = golden("mixed")
        rules = sarif(model)["runs"][0]["tool"]["driver"]["rules"]
        for rule in rules:
            if "helpUri" in rule:
                self.assertTrue(rule["helpUri"].startswith("https://"))

    def test_rejection_reason_in_properties(self):
        results = sarif(golden("failed"))["runs"][0]["results"]
        rejected = [r for r in results if r["properties"]["status"] == "REJECTED"]
        self.assertEqual(len(rejected), 1)
        self.assertIn("protected_identifier_changed", rejected[0]["properties"]["rejection_reason"])
        self.assertEqual(rejected[0]["properties"]["module"], "kbi_stock_custom")

    def test_invocation_exit_code_and_blocked_notification(self):
        doc = sarif(golden("blocked"), exit_code=4)
        invocation = doc["runs"][0]["invocations"][0]
        self.assertEqual(invocation["exitCode"], 4)
        self.assertFalse(invocation["executionSuccessful"])
        self.assertEqual(invocation["toolExecutionNotifications"][0]["level"], "error")
        self.assertIn("kbi_old_portal", invocation["toolExecutionNotifications"][0]["message"]["text"])
        self.assertNotIn("exitCode", sarif(golden("mixed"))["runs"][0]["invocations"][0])

    def test_verification_scope_and_provisional_in_run_properties(self):
        props = sarif(golden("provisional"))["runs"][0]["properties"]
        self.assertEqual(props["verificationScope"]["layersRun"], [1, 2, 3])
        self.assertTrue(props["provisional"]["active"])
        self.assertNotIn("provisional", sarif(golden("static_validated"))["runs"][0]["properties"])

    def test_untrusted_text_is_neutralised_and_uri_encoded(self):
        text = json.dumps(sarif(golden("hostile")))
        self.assertNotIn("\\u001b", text)
        uri = sarif(golden("hostile"))["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        self.assertNotIn("<", uri)
        self.assertIn("%3Cb%3E", uri)


if __name__ == "__main__":
    unittest.main()
