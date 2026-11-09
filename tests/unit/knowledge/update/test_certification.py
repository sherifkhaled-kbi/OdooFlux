"""Feature 012 automated certification (plan section 4, addendum A4): issue, verify and the adversarial cases.

The real executor is attached the way the app does it (``builtins.build_context`` attaches the process-wide executor).
Tests that need "no executor" detach it with the test-only ``certification._reset_for_tests`` and re-attach in
``tearDown``. ``verify`` recomputes everything, so every tampered record or changed input must produce a finding, and a
valid record must produce none. Stdlib unittest only.
"""

import copy
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins as composition_root
from odooflux.knowledge.release.canonical import canonical_bytes, digest_obj
from odooflux.knowledge.update import certification as cert
from odooflux.transformers import fix_templates as ft
from odooflux.transformers import imported as imp

REPO = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO / "src" / "odooflux" / "knowledge" / "schemas" / "fix_certification.schema.json"
RULE_ID = "1-1.python_orm.sample-rule"
COMMUNITY = "odoo-community"
ENTERPRISE = "odoo-enterprise"
CONFIDENTIALITY = {COMMUNITY: "public", ENTERPRISE: "enterprise"}  # the verified provenance index (caller supplies it)
# template id -> (params, the derived class used at issue; None when the template serves no derived class)
SAMPLES = {
    "python.rewrite_imported_symbol": ({"module": "odoo.tools.helpers", "old": "old_round", "new": "new_round"},
                                       "REPLACEMENT_CONFIRMED"),
    "python.remove_imported_decorator": ({"module": "odoo.api", "name": "multi"}, "IDENTITY_DECORATOR_REMOVED"),
    "python.rename_keyword": ({"callee": "fields.Char", "keyword": "oldkw", "new_keyword": "newkw"}, None),
    "python.remove_keyword": ({"callee": "fields.Char", "keyword": "deprecated"}, None),
}
ENABLED = [t for t in SAMPLES if ft.FIX_TEMPLATES[t].change_classes]
FORBIDDEN_KEYS = ("passed", "status", "ok", "edition")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _attach_real_executor():
    """What the app does: builtins.build_context attaches the one process-wide FixCertifier (a no-op when attached)."""
    composition_root.build_context()


class ComposedTestCase(unittest.TestCase):
    """Starts with the real executor attached and leaves it attached, whatever the test detached."""

    def setUp(self):
        cert._reset_for_tests()
        _attach_real_executor()

    def tearDown(self):
        cert._reset_for_tests()
        _attach_real_executor()


def _bound_template(params):
    """The template whose parameter names ``params`` carries, when it binds a fixer. Rules come from metadata, which
    binds the fixer and detector together with the params, so the test rows do the same."""
    if not isinstance(params, dict):
        return None
    return next((t for t in ft.FIX_TEMPLATES.values() if t.fixer_ref and t.names == frozenset(params)), None)


def _row(params, rule_id=RULE_ID, origin=None):
    bound = _bound_template(params)
    row = {"id": rule_id, "step": "1-1", "category": "python_orm", "maturity": "DETECT_ONLY", "risk": "LOW",
           "evidence": ["EV-001"], "detector_ref": bound.detector_refs[0] if bound else None,
           "fixer_ref": bound.fixer_ref if bound else None, "tests": {}, "params": params,
           "review_required": False}
    if origin is not None:
        row["origin"] = origin
    return row


def _evidence(rule_id=RULE_ID, *, eid="EV-001", source=COMMUNITY, official=True, description="official change"):
    row = {"id": eid, "rule_ids": [rule_id], "official": official, "origin": "KAP_MANUAL", "status": "VERIFIED",
           "description": description, "url": "https://github.com/odoo/odoo", "revision": "rev-sample", "risk": "LOW"}
    if source is not None:
        row["source_id"] = source
    return [row]


def _issue(template_id="python.rewrite_imported_symbol", *, mapping=CONFIDENTIALITY, evidence=None):
    params, cls = SAMPLES[template_id]
    row = _row(params)
    evidence = _evidence() if evidence is None else evidence
    return row, evidence, cert.issue(row, evidence, source_confidentiality=mapping, change_class=cls)


def _verify(row, evidence, record, *, mapping=CONFIDENTIALITY, template_id="python.rewrite_imported_symbol"):
    return cert.verify(row, evidence, record, source_confidentiality=mapping, change_class=SAMPLES[template_id][1])


def _codes(findings):
    return {finding["code"] for finding in findings}


class RoundTripTests(ComposedTestCase):
    def test_issue_then_verify_passes_for_every_enabled_template(self):
        for template_id in ENABLED:
            with self.subTest(template=template_id):
                row, evidence, record = _issue(template_id)
                self.assertEqual(_verify(row, evidence, record, template_id=template_id), [])

    def test_mixed_source_evidence_round_trips(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        row = _row(params)
        row["evidence"] = ["EV-001", "EV-002"]
        evidence = _evidence(eid="EV-001", source=COMMUNITY) + _evidence(eid="EV-002", source=ENTERPRISE)
        record = cert.issue(row, evidence, source_confidentiality=CONFIDENTIALITY, change_class=cls)
        self.assertEqual(record["evidence_sources"], [
            {"source_id": COMMUNITY, "confidentiality": "public"},
            {"source_id": ENTERPRISE, "confidentiality": "enterprise"}])
        self.assertEqual(_verify(row, evidence, record), [])

    def test_record_has_exact_schema_keys_and_no_pass_flags_or_edition(self):
        _, _, record = _issue()
        self.assertEqual(set(record), set(cert.RECORD_KEYS))
        for key in FORBIDDEN_KEYS:
            self.assertNotIn(key, record)
        self.assertEqual(record["schema"], "odooflux.fix-certification/1")
        self.assertEqual(record["policy_version"], "1")
        self.assertEqual(record["template_version"], 1)
        self.assertEqual(set(record["checks"]), set(cert.CHECK_NAMES))
        for name, value in record["checks"].items():
            with self.subTest(check=name):
                self.assertRegex(value, HEX64)

    def test_record_digest_covers_the_body(self):
        _, _, record = _issue()
        body = {k: v for k, v in record.items() if k != "record_digest"}
        self.assertEqual(record["record_digest"], digest_obj(body))

    def test_reference_format(self):
        _, _, record = _issue()
        self.assertRegex(cert.reference(record), r"^auto-cert:1:[0-9a-f]{64}$")
        self.assertEqual(cert.reference(record), f"auto-cert:1:{record['record_digest']}")

    def test_issue_is_deterministic(self):
        for template_id in ENABLED:
            with self.subTest(template=template_id):
                params, cls = SAMPLES[template_id]
                row, evidence = _row(params), _evidence()
                first = cert.issue(row, evidence, source_confidentiality=CONFIDENTIALITY, change_class=cls)
                second = cert.issue(row, evidence, source_confidentiality=CONFIDENTIALITY, change_class=cls)
                self.assertEqual(canonical_bytes(first), canonical_bytes(second))

    def test_rule_maturity_and_review_flag_are_outside_the_rule_digest(self):
        row, evidence, record = _issue()
        row["maturity"] = "FIX_ENABLED"
        row["review_required"] = True
        self.assertEqual(_verify(row, evidence, record), [])

    def test_approval_label_is_outside_the_rule_digest(self):
        # a record cannot contain the reference that names it, so the approval label must not change the rule digest
        row, evidence, record = _issue()
        before = cert.rule_digest(row)
        row["approval"] = cert.reference(record)
        self.assertEqual(cert.rule_digest(row), before)
        self.assertEqual(_verify(row, evidence, record), [])

    def test_transformer_identity_names_the_primitive(self):
        _, _, record = _issue("python.remove_imported_decorator")
        self.assertEqual(record["transformer"]["qualified_name"],
                         "odooflux.rules.python.certified.remove_imported_decorator")
        self.assertRegex(record["transformer"]["source_digest"], HEX64)


class IssueRefusalTests(ComposedTestCase):
    def assertIssueRefused(self, code, row, evidence, *, mapping=CONFIDENTIALITY,
                           change_class="REPLACEMENT_CONFIRMED"):
        with self.assertRaises(cert.CertificationError) as ctx:
            cert.issue(row, evidence, source_confidentiality=mapping, change_class=change_class)
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)
        self.assertTrue(ctx.exception.detail)

    def test_ineligible_row_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("not_eligible", _row(params, origin="AI"), _evidence(), change_class=cls)
        self.assertIssueRefused("not_eligible", _row({"callee": "a.b"}), _evidence(), change_class=cls)
        self.assertIssueRefused("not_eligible", _row(params), _evidence(), change_class="REMOVED")
        self.assertIssueRefused("not_eligible", _row(params), _evidence(), change_class="REPLACEMENT_CANDIDATE")

    def test_remove_keyword_row_cannot_be_issued(self):
        params, _ = SAMPLES["python.remove_keyword"]
        for cls in ("REPLACEMENT_CONFIRMED", "IDENTITY_DECORATOR_REMOVED", "REMOVED"):
            with self.subTest(change_class=cls):
                with self.assertRaises(cert.CertificationError) as ctx:
                    cert.issue(_row(params), _evidence(), source_confidentiality=CONFIDENTIALITY, change_class=cls)
                self.assertEqual(ctx.exception.code, "not_eligible")
                self.assertIn("python.remove_keyword is disabled", ctx.exception.detail)

    def test_rename_keyword_row_cannot_be_issued(self):
        params, _ = SAMPLES["python.rename_keyword"]
        with self.assertRaises(cert.CertificationError) as ctx:
            cert.issue(_row(params), _evidence(), source_confidentiality=CONFIDENTIALITY,
                       change_class="RENAMED_CANDIDATE")
        self.assertEqual(ctx.exception.code, "not_eligible")
        self.assertIn("disabled", ctx.exception.detail)

    def test_unofficial_evidence_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("evidence_not_official", _row(params), _evidence(official=False), change_class=cls)

    def test_missing_evidence_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("evidence_missing", _row(params), [], change_class=cls)
        self.assertIssueRefused("evidence_missing", _row(params), None, change_class=cls)

    def test_evidence_for_another_rule_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("evidence_rule_mismatch", _row(params), _evidence("1-2.python_orm.other"),
                                change_class=cls)

    def test_unexpected_evidence_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("evidence_unexpected", _row(params), _evidence() + _evidence(eid="EV-002"),
                                change_class=cls)

    def test_source_missing_from_the_mapping_is_refused_never_defaulted(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("source_unclassified", _row(params), _evidence(source="odoo-unknown"),
                                change_class=cls)
        self.assertIssueRefused("source_unclassified", _row(params), _evidence(), mapping={}, change_class=cls)
        self.assertIssueRefused("source_unclassified", _row(params), _evidence(), mapping=None, change_class=cls)

    def test_evidence_without_source_id_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("source_missing", _row(params), _evidence(source=None), change_class=cls)

    def test_invalid_confidentiality_value_is_refused(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        self.assertIssueRefused("source_confidentiality_invalid", _row(params), _evidence(),
                                mapping={COMMUNITY: "private"}, change_class=cls)

    def test_failing_check_refuses_issue(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]

        def no_edits(parsed, module, old, new, *, rule_id, severity=None, step=None):
            return []

        with mock.patch.object(imp, "rewrite_imported_symbol_edits", no_edits):
            self.assertIssueRefused("check_failed", _row(params), _evidence(), change_class=cls)

    def test_problems_are_reported_by_the_build_step(self):
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        record, problems = cert._build(_row(params), _evidence(official=False),
                                       source_confidentiality=CONFIDENTIALITY, change_class=cls)
        self.assertIn("evidence_not_official", {code for code, _ in problems})
        self.assertIsNotNone(record)  # the record is built, but issue() refuses it


class VerifyAdversarialTests(ComposedTestCase):
    def setUp(self):
        super().setUp()
        self.row, self.evidence, self.record = _issue()

    def test_added_pass_flags_and_edition_are_rejected(self):
        for key in FORBIDDEN_KEYS:
            with self.subTest(key=key):
                tampered = copy.deepcopy(self.record)
                tampered[key] = True
                findings = _verify(self.row, self.evidence, tampered)
                self.assertIn(key, {f["field"] for f in findings if f["code"] == "extra_key"})

    def test_passed_true_inside_checks_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["checks"]["positive"] = True
        self.assertIn("check_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_flipped_output_digest_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["outputs"]["positive_output_digest"] = "0" * 64
        self.assertIn("output_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_flipped_check_digest_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["checks"]["conflict"] = "f" * 64
        self.assertIn("check_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_tampered_record_digest_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["record_digest"] = "a" * 64
        self.assertIn("record_digest_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_record_edit_with_recomputed_digest_still_fails(self):
        tampered = copy.deepcopy(self.record)
        tampered["fixtures"]["negative_digest"] = "1" * 64
        tampered["record_digest"] = digest_obj({k: v for k, v in tampered.items() if k != "record_digest"})
        self.assertIn("fixture_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_param_changed_after_issue_is_rejected(self):
        row = copy.deepcopy(self.row)
        row["params"]["new"] = "other_name"
        self.assertIn("rule_changed", _codes(_verify(row, self.evidence, self.record)))

    def test_fixer_ref_changed_after_issue_is_rejected(self):
        # a row bound to another fixer is no longer the certified template: it is not eligible at all (no record)
        row = copy.deepcopy(self.row)
        row["fixer_ref"] = "odooflux.rules.python.generic:rename_keyword"
        findings = _verify(row, self.evidence, self.record)
        self.assertIn("not_eligible", _codes(findings))
        self.assertTrue(any("fixer_ref" in f["detail"] for f in findings if f["code"] == "not_eligible"))

    def test_evidence_digest_changed_is_rejected(self):
        evidence = copy.deepcopy(self.evidence)
        evidence[0]["description"] = "edited after issue"
        self.assertIn("evidence_changed", _codes(_verify(self.row, evidence, self.record)))

    def test_evidence_removed_is_rejected(self):
        self.assertIn("evidence_missing", _codes(_verify(self.row, [], self.record)))

    def test_confidentiality_changed_after_issue_is_rejected(self):
        flipped = {COMMUNITY: "public", ENTERPRISE: "public"}
        params, cls = SAMPLES["python.rewrite_imported_symbol"]
        row = _row(params)
        row["evidence"] = ["EV-001", "EV-002"]
        evidence = _evidence(eid="EV-001", source=COMMUNITY) + _evidence(eid="EV-002", source=ENTERPRISE)
        record = cert.issue(row, evidence, source_confidentiality=CONFIDENTIALITY, change_class=cls)
        findings = cert.verify(row, evidence, record, source_confidentiality=flipped, change_class=cls)
        self.assertIn("source_confidentiality_changed", _codes(findings))
        self.assertTrue(any(f["field"].startswith("evidence_sources") for f in findings))

    def test_source_missing_from_mapping_at_verify_is_a_finding(self):
        findings = _verify(self.row, self.evidence, self.record, mapping={})
        self.assertIn("source_unclassified", _codes(findings))
        self.assertTrue(findings)

    def test_swapped_rule_id_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["rule_id"] = "1-2.python_orm.other-rule"
        self.assertIn("rule_id_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_template_version_mismatch_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["template_version"] = 2
        self.assertIn("template_version_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_older_policy_version_is_rejected(self):
        with mock.patch.object(cert, "POLICY_VERSION", "0"):
            old = cert.issue(self.row, self.evidence, source_confidentiality=CONFIDENTIALITY,
                             change_class="REPLACEMENT_CONFIRMED")
        self.assertEqual(old["policy_version"], "0")
        self.assertIn("policy_version_mismatch", _codes(_verify(self.row, self.evidence, old)))

    def test_policy_string_edited_without_redigest_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["policy_version"] = "0"
        self.assertIn("record_digest_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_extra_nested_key_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["transformer"]["passed"] = True
        self.assertTrue(_verify(self.row, self.evidence, tampered))

    def test_extra_top_level_key_with_recomputed_digest_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["ok"] = True
        tampered["record_digest"] = digest_obj({k: v for k, v in tampered.items() if k != "record_digest"})
        self.assertIn("extra_key", _codes(_verify(self.row, self.evidence, tampered)))

    def test_missing_key_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        del tampered["checks"]
        self.assertIn("missing_key", _codes(_verify(self.row, self.evidence, tampered)))

    def test_wrong_schema_string_is_rejected(self):
        tampered = copy.deepcopy(self.record)
        tampered["schema"] = "odooflux.fix-certification/0"
        self.assertIn("schema_mismatch", _codes(_verify(self.row, self.evidence, tampered)))

    def test_change_class_mismatch_is_rejected(self):
        # rewrite_imported_symbol serves REPLACEMENT_CONFIRMED and DELEGATING_ALIAS: a record issued as one fails under
        # the other
        row, evidence, record = _issue("python.rewrite_imported_symbol")
        self.assertEqual(record["change_class"], "REPLACEMENT_CONFIRMED")
        findings = cert.verify(row, evidence, record, source_confidentiality=CONFIDENTIALITY,
                               change_class="DELEGATING_ALIAS")
        self.assertIn("change_class_mismatch", _codes(findings))
        # a class the template does not serve is refused as not eligible
        refused = cert.verify(self.row, self.evidence, self.record, source_confidentiality=CONFIDENTIALITY,
                              change_class="REMOVED")
        self.assertIn("not_eligible", _codes(refused))

    def test_derived_record_does_not_verify_once_its_change_class_is_an_old_class(self):
        row, evidence, record = _issue("python.rewrite_imported_symbol")
        for old in ("REPLACEMENT_CANDIDATE", "REMOVED"):
            with self.subTest(old_class=old):
                tampered = copy.deepcopy(record)
                tampered["change_class"] = old
                # without a recomputed digest the body digest catches the edit
                self.assertIn("record_digest_mismatch", _codes(_verify(row, evidence, tampered)))
                # with the digest recomputed, the recomputation still carries the derived class and reports the change
                tampered["record_digest"] = digest_obj({k: v for k, v in tampered.items() if k != "record_digest"})
                self.assertIn("change_class_mismatch", _codes(_verify(row, evidence, tampered)))
                # and verifying under the old class itself is refused as not eligible
                findings = cert.verify(row, evidence, tampered, source_confidentiality=CONFIDENTIALITY,
                                       change_class=old)
                self.assertIn("not_eligible", _codes(findings))

    def test_monkeypatched_primitive_is_rejected(self):
        def inert(parsed, module, old, new, *, rule_id, severity=None, step=None):
            return []

        with mock.patch.object(imp, "rewrite_imported_symbol_edits", inert):
            findings = _verify(self.row, self.evidence, self.record)
        self.assertIn("transformer_source_changed", _codes(findings))
        self.assertIn("check_failed", _codes(findings))

    def test_monkeypatched_primitive_with_same_outputs_is_still_rejected(self):
        original = imp.rewrite_imported_symbol_edits

        def same_behaviour(parsed, module, old, new, **kwargs):
            return original(parsed, module, old, new, **kwargs)

        with mock.patch.object(imp, "rewrite_imported_symbol_edits", same_behaviour):
            findings = _verify(self.row, self.evidence, self.record)
        self.assertIn("transformer_source_changed", _codes(findings))
        self.assertNotIn("check_failed", _codes(findings))

    def test_non_mapping_record_is_rejected(self):
        self.assertEqual(_codes(_verify(self.row, self.evidence, ["not", "a", "record"])), {"record_not_mapping"})

    def test_verify_does_not_mutate_inputs(self):
        before_record, before_row = copy.deepcopy(self.record), copy.deepcopy(self.row)
        _verify(self.row, self.evidence, self.record)
        self.assertEqual(self.record, before_record)
        self.assertEqual(self.row, before_row)

    def test_valid_record_yields_no_findings_for_a_second_verify(self):
        self.assertEqual(_verify(self.row, self.evidence, self.record), [])
        self.assertEqual(_verify(self.row, self.evidence, copy.deepcopy(self.record)), [])


class ExecutorAuthorityTests(ComposedTestCase):
    """The executor is process-wide and single-assignment; certification never accepts one from a caller."""

    def setUp(self):
        super().setUp()
        self.row, self.evidence, self.record = _issue()
        self.params, self.cls = SAMPLES["python.rewrite_imported_symbol"]

    def test_issue_without_an_attached_executor_fails_closed(self):
        cert._reset_for_tests()
        with self.assertRaises(cert.CertificationError) as ctx:
            cert.issue(_row(self.params), _evidence(), source_confidentiality=CONFIDENTIALITY, change_class=self.cls)
        self.assertEqual(ctx.exception.code, "CERT_EXECUTOR_MISSING")

    def test_verify_without_an_attached_executor_fails_closed(self):
        cert._reset_for_tests()
        findings = cert.verify(self.row, self.evidence, self.record, source_confidentiality=CONFIDENTIALITY,
                               change_class=self.cls)
        self.assertEqual([f["code"] for f in findings], ["CERT_EXECUTOR_MISSING"])

    def test_trusted_executor_raises_when_none_is_attached(self):
        cert._reset_for_tests()
        with self.assertRaises(cert.CertificationError) as ctx:
            cert.trusted_executor()
        self.assertEqual(ctx.exception.code, "CERT_EXECUTOR_MISSING")

    def test_disabled_remove_keyword_still_runs_its_primitive_through_exercise(self):
        # disabled for issue, but the executor still runs the real primitive on the fixtures
        params, _ = SAMPLES["python.remove_keyword"]
        result = cert.trusted_executor().exercise(_row(params), "python.remove_keyword", params)
        self.assertEqual(result["problems"], [])
        self.assertIsNotNone(result["fixtures"])
        self.assertIsNotNone(result["outputs"])

    def test_the_composition_root_attaches_the_real_executor(self):
        self.assertEqual(type(cert.trusted_executor()).__name__, "FixCertifier")

    def test_reattaching_the_identical_executor_is_a_no_op(self):
        attached = cert.trusted_executor()
        cert.attach_executor(attached)
        self.assertIs(cert.trusted_executor(), attached)
        _attach_real_executor()  # build_context attaches the same process object again
        self.assertIs(cert.trusted_executor(), attached)

    def test_attaching_a_different_executor_is_refused_and_the_first_is_kept(self):
        attached = cert.trusted_executor()

        class OtherExecutor:
            def eligible(self, rule_row, change_class=None):
                return None, "other"

        with self.assertRaises(cert.CertificationError) as ctx:
            cert.attach_executor(OtherExecutor())
        self.assertEqual(ctx.exception.code, "CERT_EXECUTOR_CONFLICT")
        self.assertIs(cert.trusted_executor(), attached)
        self.assertEqual(_verify(self.row, self.evidence, self.record), [])

    def test_attaching_none_is_refused(self):
        cert._reset_for_tests()
        with self.assertRaises(cert.CertificationError):
            cert.attach_executor(None)

    def test_a_caller_supplied_executor_is_not_consulted(self):
        # there is no registries keyword any more: an executor cannot be passed in, only attached by the composition root
        with self.assertRaises(TypeError):
            cert.issue(self.row, self.evidence, source_confidentiality=CONFIDENTIALITY, change_class=self.cls,
                       registries=object())
        with self.assertRaises(TypeError):
            cert.verify(self.row, self.evidence, self.record, source_confidentiality=CONFIDENTIALITY,
                        change_class=self.cls, registries=object())


class SourceClassificationTests(unittest.TestCase):
    """Confidentiality is derived from the verified provenance index, never hand-built in production code."""

    def test_enterprise_kinds_are_enterprise_and_others_public(self):
        index = {"odoo-community": {"source_id": "odoo-community", "kind": "GIT_COMMUNITY"},
                 "odoo-enterprise": {"source_id": "odoo-enterprise", "kind": "GIT_ENTERPRISE"}}
        self.assertEqual(cert.source_confidentiality_from_index(index),
                         {"odoo-community": "public", "odoo-enterprise": "enterprise"})

    def test_unknown_or_missing_provenance_classifies_nothing(self):
        self.assertEqual(cert.source_confidentiality_from_index(None), {})
        self.assertEqual(cert.source_confidentiality_from_index({"x": "not-a-mapping"}), {})


class SchemaFileTests(ComposedTestCase):
    def setUp(self):
        super().setUp()
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_is_closed_and_lists_the_record_keys(self):
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(set(self.schema["properties"]), set(cert.RECORD_KEYS))
        self.assertEqual(set(self.schema["required"]), set(cert.RECORD_KEYS))
        self.assertNotIn("edition", self.schema["properties"])
        for name in ("transformer", "fixtures", "outputs", "checks"):
            with self.subTest(object=name):
                self.assertFalse(self.schema["properties"][name]["additionalProperties"])

    def test_schema_enumerates_templates_classes_checks_and_confidentiality(self):
        props = self.schema["properties"]
        self.assertEqual(set(props["template_id"]["enum"]), set(ft.FIX_TEMPLATES))
        self.assertEqual(tuple(props["change_class"]["enum"]), ft.LEDGER_CLASSES + ft.DERIVED_CLASSES)
        self.assertEqual(set(props["checks"]["required"]), set(cert.CHECK_NAMES))
        source = props["evidence_sources"]["items"]
        self.assertFalse(source["additionalProperties"])
        self.assertEqual(source["properties"]["confidentiality"]["enum"], ["public", "enterprise"])

    def test_schema_refuses_pass_flags(self):
        for key in ("passed", "status", "ok"):
            self.assertNotIn(key, self.schema["properties"])

    def test_issued_record_shape_matches_schema_keys(self):
        _, _, record = _issue()
        self.assertEqual(set(record), set(self.schema["properties"]))


class ReferenceAndIdentityTests(ComposedTestCase):
    def test_issued_record_for_every_enabled_template_refers_to_its_own_primitive(self):
        for template_id in ENABLED:
            with self.subTest(template=template_id):
                _, _, record = _issue(template_id)
                self.assertEqual(record["template_id"], template_id)
                self.assertEqual(record["transformer"]["qualified_name"],
                                 ft.template(template_id).fixer_ref.replace(":", "."))


if __name__ == "__main__":
    unittest.main()
