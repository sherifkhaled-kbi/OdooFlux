"""Feature 012 / Wave 3c: the pure renderers in knowledge/update/report.py and their JSON schemas.

Every number asserted in human output is compared with a value taken from the input fields, and the counts use unusual
values (7, 0, 13, ...) so a hard-coded number cannot pass. The JSON produced by the renderers is validated with the
repo's stdlib schema checker (odooflux.knowledge.validator) against the shipped schema files.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_report.py' -t .
"""

import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.update import report
from odooflux.knowledge.update.model import CERTIFICATION_STATEMENT, UPDATE_OUTCOMES, UpdateResult

UPDATE_SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "update_report.schema.json").read_text(encoding="utf-8"))
STATUS_SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "knowledge_status.schema.json").read_text(encoding="utf-8"))
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "d" * 64
PREVIOUS = "rel-previous"
NEW = "rel-new"
UNUSUAL_CHANGES = {"rules_added": 7, "rules_changed": 0, "rules_lost": 2, "rules_superseded": 3,
                   "rules_downgraded": 5, "fix_enabled_added": 13, "detect_only_added": 4}


def source(version, *, status="OK", remote=SHA_A, installed=SHA_B, edition="community"):
    return {"source_id": f"{edition}-{version}", "edition": edition, "version": version, "remote_sha": remote,
            "installed_sha": installed, "status": status, "detail": ""}


def check_block(sources=None, new_versions=(), statuses=("SOURCE_REVISION_AVAILABLE",)):
    if sources is None:
        sources = [source("12.0"), source("13.0", installed=SHA_A), source("14.0", status="UNAVAILABLE", remote=None)]
    return {"schema": "odooflux.knowledge-check/1", "statuses": list(statuses), "sources": sources,
            "new_versions": list(new_versions), "affected_transitions": ["12-13"], "enterprise_freshness": "FRESH",
            "catalog_digest": "c" * 64, "offline": False, "installed_release": PREVIOUS}


def make_result(outcome="ACTIVE", **overrides) -> UpdateResult:
    fields = dict(outcome=outcome, reasons=(), dry_run=outcome == "DRY_RUN", offline=False,
                  previous_release=PREVIOUS, new_release=NEW if outcome == "ACTIVE" else None,
                  release_digest=DIGEST, completeness="COMPLETE", check=check_block(), plan=None, acquisition=None,
                  build={"outcome": "OK", "code": None, "message": "", "release_id": NEW, "completeness": "COMPLETE"},
                  activation={"state": "ACTIVE"}, changes=dict(UNUSUAL_CHANGES), carried_forward=(),
                  enterprise={"status": "OK", "freshness": "FRESH"}, limitations=("first limitation",
                                                                                  "second limitation"),
                  history_seq=4)
    fields.update(overrides)
    return UpdateResult(**fields)


def line_with(text, lines):
    matches = [line for line in lines.splitlines() if line.strip().startswith(text)]
    return matches[0].strip() if matches else None


class RenderUpdateTests(unittest.TestCase):
    def test_render_is_deterministic(self):
        result = make_result()
        self.assertEqual(report.render_update(result), report.render_update(result))

    def test_header_and_outcome_come_from_the_result(self):
        text = report.render_update(make_result("BLOCKED", reasons=("capability regression",)))
        self.assertTrue(text.startswith("OdooFlux Knowledge Update\n"))
        self.assertIn("outcome: BLOCKED", text)
        self.assertIn("reason: capability regression", text)

    def test_change_counts_are_taken_from_changes_fields(self):
        text = report.render_update(make_result())
        self.assertEqual(line_with("new detection rules:", text), "new detection rules: 7")
        self.assertEqual(line_with("updated rules:", text), "updated rules: 0")
        self.assertEqual(line_with("new verified fixes:", text), "new verified fixes: 13")
        self.assertEqual(line_with("removed/superseded rules:", text), "removed/superseded rules: 5")
        self.assertEqual(line_with("unverified fixes:", text), "unverified fixes: 5")

    def test_different_counts_change_the_output(self):
        changes = {"rules_added": 0, "rules_changed": 9, "rules_lost": 0, "rules_superseded": 0,
                   "rules_downgraded": 1, "fix_enabled_added": 2}
        text = report.render_update(make_result(changes=changes))
        self.assertEqual(line_with("new detection rules:", text), "new detection rules: 0")
        self.assertEqual(line_with("updated rules:", text), "updated rules: 9")
        self.assertEqual(line_with("new verified fixes:", text), "new verified fixes: 2")
        self.assertEqual(line_with("removed/superseded rules:", text), "removed/superseded rules: 0")
        self.assertEqual(line_with("unverified fixes:", text), "unverified fixes: 1")

    def test_missing_change_keys_count_as_zero(self):
        text = report.render_update(make_result(changes={"rules_added": 3}))
        self.assertEqual(line_with("new detection rules:", text), "new detection rules: 3")
        self.assertEqual(line_with("new verified fixes:", text), "new verified fixes: 0")

    def test_no_build_means_changes_not_computed(self):
        text = report.render_update(make_result("NOOP", changes=None, activation=None, new_release=None))
        self.assertIn("not computed (no build ran)", text)
        self.assertNotIn("new detection rules:", text)

    def test_source_counts_come_from_the_check_block(self):
        check = check_block(sources=[source("12.0"), source("13.0", installed=SHA_A), source("14.0",
                                                                                              status="AUTH_FAILED",
                                                                                              remote=None)],
                            new_versions=[{"edition": "community", "version": "15.0", "branch": "15.0",
                                           "remote_sha": SHA_A}])
        text = report.render_update(make_result(check=check))
        self.assertEqual(line_with("sources checked:", text), "sources checked: 3 (compared 2)")
        self.assertEqual(line_with("new versions:", text), "new versions: 1 (15.0)")
        self.assertEqual(line_with("updated versions:", text), "updated versions: 1 (12.0)")

    def test_zero_changes_are_zero_not_unavailable(self):
        check = check_block(sources=[source("12.0", installed=SHA_A)], statuses=("NO_UPDATE",))
        text = report.render_update(make_result("NOOP", check=check, changes=None, new_release=None))
        self.assertEqual(line_with("updated versions:", text), "updated versions: 0")
        self.assertNotIn(report.UNAVAILABLE, text)

    def test_unavailable_comparison_is_never_printed_as_zero(self):
        for check in (None, check_block(sources=[], statuses=("CHECK_UNAVAILABLE",))):
            with self.subTest(check=check is None):
                text = report.render_update(make_result("FAILED", check=check, changes=None, activation=None,
                                                        new_release=None))
                self.assertEqual(line_with("sources checked:", text), "sources checked: comparison unavailable")
                self.assertEqual(line_with("new versions:", text), "new versions: comparison unavailable")
                self.assertEqual(line_with("updated versions:", text), "updated versions: comparison unavailable")

    def test_active_release_id_follows_the_outcome(self):
        self.assertIn(f"active release id: {NEW}", report.render_update(make_result("ACTIVE")))
        for outcome in ("BLOCKED", "FAILED", "ROLLED_BACK", "NOOP", "DRY_RUN"):
            with self.subTest(outcome=outcome):
                text = report.render_update(make_result(outcome))
                self.assertIn(f"active release id: {PREVIOUS}", text)

    def test_release_and_enterprise_lines(self):
        text = report.render_update(make_result())
        self.assertIn(f"integrity digest: {DIGEST}", text)
        self.assertIn("activation: ACTIVE", text)
        self.assertIn("completeness: COMPLETE", text)
        self.assertIn("enterprise: OK, freshness FRESH", text)
        empty = report.render_update(make_result(enterprise=None, check=None))
        self.assertIn("enterprise: not checked, freshness UNKNOWN", empty)

    def test_every_limitation_is_listed(self):
        limitations = ("one limitation", "two limitation", "three limitation")
        text = report.render_update(make_result(limitations=limitations))
        for item in limitations:
            self.assertIn(f"  - {item}", text)

    def test_fixed_support_dimension_lines_are_always_present(self):
        for outcome in UPDATE_OUTCOMES:
            with self.subTest(outcome=outcome):
                text = report.render_update(make_result(outcome))
                self.assertIn("production certification: NOT_GRANTED", text)
                self.assertIn("migration support: not established by an update", text)
                for key, value in CERTIFICATION_STATEMENT.items():
                    self.assertIn(f"{key.replace('_', ' ')}: {value}", text)

    def test_json_of_every_outcome_validates_against_the_schema(self):
        for outcome in UPDATE_OUTCOMES:
            with self.subTest(outcome=outcome):
                payload = json.loads(json.dumps(make_result(outcome).to_dict()))
                self.assertEqual(v.check(payload, UPDATE_SCHEMA), [])

    def test_schema_rejects_drift(self):
        payload = make_result().to_dict()
        for label, mutate in (
            ("unknown outcome", lambda p: p.update(outcome="MAYBE")),
            ("granted production", lambda p: p["support_dimensions"].update(production_certification="GRANTED")),
            ("extra key", lambda p: p.update(surprise=1)),
            ("missing key", lambda p: p.pop("limitations")),
        ):
            with self.subTest(label=label):
                broken = json.loads(json.dumps(payload))
                mutate(broken)
                self.assertTrue(v.check(broken, UPDATE_SCHEMA))

    def test_schema_outcome_enum_matches_the_model(self):
        self.assertEqual(set(UPDATE_SCHEMA["properties"]["outcome"]["enum"]), set(UPDATE_OUTCOMES))
        self.assertEqual(set(UPDATE_SCHEMA["properties"]["support_dimensions"]["required"]),
                         set(CERTIFICATION_STATEMENT))


class RenderStatusTests(unittest.TestCase):
    def payload(self, **overrides):
        fields = dict(release_id=None, digest="e" * 64, completeness=None, steps={}, revisions={},
                      rules_by_maturity={"DETECT_ONLY": 4, "FIX_ENABLED": 2}, certification_governed=1,
                      last_successful=None)
        fields.update(overrides)
        return report.status_payload(**fields)

    def test_builtin_payload_validates_and_states_limitations(self):
        payload = self.payload()
        self.assertEqual(payload["schema"], "odooflux.knowledge-status/1")
        self.assertEqual(payload["kind"], "built-in")
        self.assertEqual(v.check(json.loads(json.dumps(payload)), STATUS_SCHEMA), [])
        self.assertEqual(payload["limitations"], report.status_limitations(None))
        self.assertNotIn("knowledge completeness is PARTIAL", " ".join(payload["limitations"]))

    def test_counts_come_from_the_rule_maturities(self):
        payload = self.payload(rules_by_maturity={"DETECT_ONLY": 7, "FIX_ENABLED": 13, "SKELETON": 0},
                               certification_governed=6)
        self.assertEqual(payload["rules"]["total"], 20)
        self.assertEqual(payload["rules"]["fix_enabled"], 13)
        self.assertEqual(payload["rules"]["certification_governed"], 6)
        text = report.render_status(payload)
        self.assertIn("detection rules: 20 (DETECT_ONLY=7, FIX_ENABLED=13, SKELETON=0)", text)
        self.assertIn("fix-enabled rules: 13", text)
        self.assertIn("certification-governed rules: 6", text)

    def test_partial_completeness_adds_a_limitation(self):
        payload = self.payload(release_id="rel-x", completeness="PARTIAL", steps={"12-13": "COMPLETE"},
                               revisions={"community-12.0": SHA_A})
        self.assertIn("knowledge completeness is PARTIAL: some pipeline steps are not covered by the active release",
                      payload["limitations"])
        text = report.render_status(payload)
        self.assertIn("active release: rel-x", text)
        self.assertIn("steps covered: 12-13 (COMPLETE)", text)
        self.assertIn(f"  community-12.0: {SHA_A}", text)
        self.assertEqual(v.check(json.loads(json.dumps(payload)), STATUS_SCHEMA), [])

    def test_last_successful_update_is_shown_when_present(self):
        last = {"seq": 3, "timestamp": "2026-11-01T00:00:00Z", "new_release": "rel-x"}
        text = report.render_status(self.payload(release_id="rel-x", last_successful=last))
        self.assertIn("last successful update: 2026-11-01T00:00:00Z (release rel-x, seq 3)", text)
        self.assertIn("last successful update: none recorded", report.render_status(self.payload()))

    def test_render_status_is_deterministic(self):
        payload = self.payload(release_id="rel-x", completeness="COMPLETE")
        self.assertEqual(report.render_status(payload), report.render_status(payload))

    def test_status_schema_rejects_unknown_kind(self):
        payload = json.loads(json.dumps(self.payload()))
        payload["kind"] = "custom"
        self.assertTrue(v.check(payload, STATUS_SCHEMA))


class RenderHistoryTests(unittest.TestCase):
    def entries(self):
        newest_blocked = {"seq": 3, "ts": "2026-11-03T00:00:00Z", "prev_hash": "0" * 64, "entry_hash": "1" * 64,
                          "outcome": "BLOCKED", "fingerprint": None, "previous_release": PREVIOUS,
                          "new_release": None, "source_revisions": {"community-12.0": SHA_A},
                          "reason": "capability regression"}
        active = {"seq": 2, "ts": "2026-11-02T00:00:00Z", "prev_hash": "0" * 64, "entry_hash": "2" * 64,
                  "outcome": "ACTIVE", "fingerprint": None, "previous_release": PREVIOUS, "new_release": NEW,
                  "source_revisions": {"community-12.0": SHA_B}, "reason": None,
                  "details": {"changes": {"rules_added": 7, "fix_enabled_added": 13},
                              "activation": {"state": "ACTIVE"}}}
        noop = {"seq": 1, "ts": "2026-11-01T00:00:00Z", "prev_hash": "0" * 64, "entry_hash": "3" * 64,
                "outcome": "NOOP", "fingerprint": None, "previous_release": PREVIOUS, "new_release": None,
                "source_revisions": {}, "reason": "nothing changed"}
        return [newest_blocked, active, noop]

    def test_rows_keep_input_order_and_carry_fields(self):
        rows = report.history_rows(self.entries())
        self.assertEqual([row["seq"] for row in rows], [3, 2, 1])
        self.assertEqual(rows[0]["failure_reason"], "capability regression")
        self.assertIsNone(rows[1]["failure_reason"])
        self.assertEqual(rows[1]["changes"], {"rules_added": 7, "fix_enabled_added": 13})
        self.assertEqual(rows[1]["activation"], {"state": "ACTIVE"})
        self.assertIsNone(rows[2]["changes"])

    def test_text_lists_newest_first_and_counts_from_details(self):
        text = report.render_history(report.history_rows(self.entries()))
        self.assertLess(text.index("#3 "), text.index("#2 "))
        self.assertLess(text.index("#2 "), text.index("#1 "))
        self.assertIn("changes: fix_enabled_added=13, rules_added=7", text)
        self.assertIn("activation: ACTIVE", text)
        self.assertIn("failure reason: capability regression", text)
        self.assertIn("chain: verified", text)

    def test_empty_history(self):
        text = report.render_history([])
        self.assertIn("no update history recorded", text)
        self.assertEqual(report.history_payload([]), {"schema": "odooflux.knowledge-history/1", "chain": "verified",
                                                      "entries": []})


if __name__ == "__main__":
    unittest.main()
