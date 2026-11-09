"""Feature 012 Wave 3c: certified FIX_ENABLED trust at build, package import (P10) and load time (plan section 4, A4, C3, D3).

Every trust decision goes through ``release/safety.fix_row_trusted``. A certification record is checked by
``certification.verify`` with the process's attached executor, the real one (``builtins.build_context``). The adversarial
cases below each must produce a refusal, and a valid record must not change behaviour for rows that have none.
Stdlib unittest only; packages are built with the real builder.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins as composition_root
from odooflux.knowledge.authoring import promote as promote_mod
from odooflux.knowledge.loader import KAP_FIX_CAPPED, KNOWLEDGE_ROOT, load_active_knowledge, load_knowledge
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.release import safety
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import KnowledgeHandle
from odooflux.knowledge.release.store import ensure_layout
from odooflux.knowledge.update import certification as cert
from odooflux.transformers import fix_templates as ft
from odooflux.transformers import imported as imp

RULE_ID = "16-17.python.synthetic-fix"
OTHER_RULE_ID = "16-17.python.synthetic-other"
COMMUNITY_SOURCE = "odoo-community-16.0"
CATALOGUED_REVISION = "ba1ba88874e2ae9716e59ec199eb739d58c3f771"  # in official_sources/revisions.json (P11 E003)
CHANGE_CLASS = "REPLACEMENT_CONFIRMED"
EVIDENCE = {
    "id": "EV-900", "rule_ids": [RULE_ID], "category": "orm",
    "source_applicability": {"from": "16.0", "to": "16.0"}, "target_applicability": {"from": "17.0", "to": None},
    "description": "Synthetic evidence for the certified trust tests",
    "url": "https://github.com/odoo/odoo/blob/0000/odoo/api.py#L1", "repository": "odoo/odoo",
    "revision": CATALOGUED_REVISION,
    "locations": [{"branch": "16.0", "revision": CATALOGUED_REVISION, "path": "odoo/api.py", "line": 1, "match": "x",
                   "kind": "present", "content_sha256": "c" * 64}],
    "detection_method": "grep on pinned source", "proposed_transformation": "replace call", "risk": "LOW",
    "required_validation": ["python_runtime"], "status": "DOCUMENTED_NOT_TESTED", "checked_on": "2026-11-01",
    "checked_by": "test", "official": True, "source_id": COMMUNITY_SOURCE,
}
PROVENANCE = [{
    "source_id": COMMUNITY_SOURCE, "revision": "0" * 40, "snapshot_digest": "sha256:" + "b" * 64, "official": True,
    "status": "VERIFIED", "kind": "GIT_COMMUNITY", "url": "https://github.com/odoo/odoo/",
}]
INDEX = {COMMUNITY_SOURCE: PROVENANCE[0]}
CONFIDENTIALITY = cert.source_confidentiality_from_index(INDEX)
PARAMS = {"module": "api", "old": "old_call", "new": "new_call"}
# the certified template for REPLACEMENT_CONFIRMED: rows bind its fixer and detector (rules/python/certified.py)
TEMPLATE = ft.FIX_TEMPLATES["python.rewrite_imported_symbol"]
FIXER_REF = TEMPLATE.fixer_ref
DETECTOR_REF = TEMPLATE.detector_refs[0]
TESTS = {"positive": "TST-SYN-1", "negative": "TST-SYN-2", "idempotence": "TST-SYN-3"}
META = {
    "label": "community-16.0-17.0-2026.11", "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"}, "sources": [], "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32, "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}


def make_row(rule_id=RULE_ID, **changes):
    row = {"id": rule_id, "step": "16-17", "category": "python_orm", "maturity": "FIX_ENABLED", "risk": "LOW",
           "evidence": ["EV-900"], "detector_ref": DETECTOR_REF, "fixer_ref": FIXER_REF, "review_required": False,
           "tests": dict(TESTS), "conflicts_with": [], "origin": "MANUAL", "params": dict(PARAMS)}
    row.update(changes)
    return row


def make_evidence(rule_id=RULE_ID, eid="EV-900"):
    record = copy.deepcopy(EVIDENCE)
    record["id"], record["rule_ids"] = eid, [rule_id]
    return record


def write_tree(root: Path, rules, evidence, provenance=PROVENANCE):
    """A knowledge tree at root/knowledge with provenance at root/provenance (the layout of a release)."""
    tree = root / "knowledge"
    (tree / "compatibility").mkdir(parents=True, exist_ok=True)
    (tree / "evidence").mkdir(parents=True, exist_ok=True)
    (tree / "compatibility" / "16-17.rules.json").write_text(json.dumps(rules), encoding="utf-8")
    for record in evidence:
        (tree / "evidence" / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    if provenance is not None:
        (root / "provenance").mkdir(parents=True, exist_ok=True)
        (root / "provenance" / "sources.json").write_text(json.dumps(provenance), encoding="utf-8")
    return tree


def certify(row, evidence, index=INDEX):
    return cert.issue(row, evidence, source_confidentiality=cert.source_confidentiality_from_index(index),
                      change_class=CHANGE_CLASS)


def store_record(tree: Path, rule_id: str, record) -> Path:
    path = tree / "certifications" / f"{rule_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")
    return path


def rule_in(tree: Path, rule_id: str) -> dict:
    kb = load_knowledge(tree)
    return next(r for r in kb.rules if r["id"] == rule_id)


def trust(tree: Path, rule_id: str, *, inherit=False):
    kb = load_knowledge(tree)
    index = safety.load_provenance_index(tree)
    row = next(r for r in kb.rules if r["id"] == rule_id)
    evidence_rows = [kb.evidence[eid] for eid in row.get("evidence") or [] if eid in kb.evidence]
    return safety.fix_row_trusted(row, tree, evidence_rows, index, kb=kb, inherit=inherit)


def codes(findings):
    return {f["code"] for f in findings}


class ComposedTestCase(unittest.TestCase):
    """The real executor is attached for every test, as the app does; a test that detaches it re-attaches in tearDown.

    Phase 1 (feature 012 Addendum F): the change class of a certified row is established by a verified machine
    confirmation (`safety.confirmed_class`), whose verifier lands in phase 2. Until then this base stands in for it with
    the class the fixture certifies. Every record in these tests is still checked against that class, and a record that
    declares another class is refused (`test_self_declared_class_is_not_trusted`)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        cert._reset_for_tests()
        composition_root.build_context()
        safety._reset_trust_cache_for_tests()
        patcher = mock.patch.object(safety, "confirmed_class",
                                    lambda rule, tree_root, kb, index, snapshot_dir: (CHANGE_CLASS, []))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        cert._reset_for_tests()
        composition_root.build_context()
        safety._reset_trust_cache_for_tests()
        self._tmp.cleanup()


class TrustWithoutCertificationTests(ComposedTestCase):
    """A row with no certification record keeps today's gate path exactly."""

    def test_gate_passing_row_without_a_record_is_trusted(self):
        # CHANGED (review item 1): this row binds a certified fixer, so certification governs it and an absent record
        # refuses it. Its gates 1 to 5 still pass (the gate functions are unchanged).
        tree = write_tree(self.base / "a", [make_row()], [make_evidence()])
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertEqual(codes(findings), {"cert-missing"})
        self.assertEqual(safety.fix_gate_findings(tree), [])

    def test_gate_failing_row_without_a_record_is_untrusted(self):
        tree = write_tree(self.base / "b", [make_row()], [make_evidence()], provenance=None)
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("no-official-evidence", codes(findings))

    def test_absent_certification_file_keeps_existing_behaviour(self):
        # CHANGED (review item 1): a certified-fixer row is governed; an absent record is refused (cert-missing)
        tree = write_tree(self.base / "c", [make_row()], [make_evidence()])
        self.assertFalse((tree / "certifications").exists())
        self.assertEqual(codes(trust(tree, RULE_ID)[1]), {"cert-missing"})
        self.assertEqual(safety.fix_gate_findings(tree), [])

    def test_non_fix_enabled_row_is_never_trusted(self):
        tree = write_tree(self.base / "d", [make_row(maturity="DETECT_ONLY")], [make_evidence()])
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertEqual(codes(findings), {"not-fix-enabled"})

    def test_human_promoted_row_is_unaffected_by_a_certification_file_for_it(self):
        # CHANGED (review item 1): a human approval does not exempt a certified-fixer row; the unreadable record refuses it
        tree = write_tree(self.base / "e", [make_row(approval="owner: alice (ticket 42)")], [make_evidence()])
        store_record(tree, RULE_ID, "{not json")
        self.assertEqual(codes(trust(tree, RULE_ID)[1]), {"cert-unreadable"})


class CertifiedTrustTests(ComposedTestCase):
    def tree_with_record(self, name, *, rule=None, record_source=None):
        row = make_row() if rule is None else rule
        evidence = [make_evidence()]
        tree = write_tree(self.base / name, [row], evidence)
        record = certify(make_row(), evidence) if record_source is None else record_source
        store_record(tree, RULE_ID, record)
        return tree, record

    def test_certified_row_is_trusted_when_the_record_verifies(self):
        tree, _ = self.tree_with_record("ok")
        self.assertEqual(trust(tree, RULE_ID), (True, []))

    def test_forged_record_copied_from_another_rule_is_untrusted(self):
        evidence_a = [make_evidence(RULE_ID, "EV-900")]
        evidence_b = [make_evidence(OTHER_RULE_ID, "EV-901")]
        other = make_row(OTHER_RULE_ID, evidence=["EV-901"],
                         params={"module": "api", "old": "b_old_call", "new": "b_new_call"})  # not A002 twin of A
        tree = write_tree(self.base / "forged", [make_row(), other], evidence_a + evidence_b)
        record_a = certify(make_row(), evidence_a)
        # the record of rule A is copied to rule B's place: B's row differs from A's record
        store_record(tree, OTHER_RULE_ID, record_a)
        trusted, findings = trust(tree, OTHER_RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("cert-verify-failed", codes(findings))
        self.assertIn("rule_id_mismatch", " ".join(f["detail"] for f in findings))

    def test_tampered_record_without_redigest_is_untrusted(self):
        tree, record = self.tree_with_record("tamper")
        record["outputs"]["positive_output_digest"] = "0" * 64
        store_record(tree, RULE_ID, record)
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("record_digest_mismatch", " ".join(f["detail"] for f in findings))

    def test_tampered_record_with_recomputed_digest_is_untrusted(self):
        tree, record = self.tree_with_record("redigest")
        record["fixtures"]["negative_digest"] = "1" * 64
        record["record_digest"] = cert.digest_obj({k: v for k, v in record.items() if k != "record_digest"})
        store_record(tree, RULE_ID, record)
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("fixture_mismatch", " ".join(f["detail"] for f in findings))

    def test_record_for_a_different_rule_digest_is_untrusted(self):
        tree, _ = self.tree_with_record("digest")
        changed = make_row(params={"module": "api", "old": "old_call", "new": "other_call"})
        (tree / "compatibility" / "16-17.rules.json").write_text(json.dumps([changed]), encoding="utf-8")
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("rule_changed", " ".join(f["detail"] for f in findings))

    def test_certification_present_but_executor_missing_is_untrusted(self):
        tree, _ = self.tree_with_record("noexec")
        cert._reset_for_tests()
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertEqual(codes(findings), {"cert-executor-missing"})

    def test_stored_pass_like_keys_are_rejected(self):
        for key, value in (("passed", True), ("status", "PASS"), ("ok", True), ("edition", "enterprise")):
            with self.subTest(key=key):
                tree, record = self.tree_with_record(f"pass-{key}")
                record[key] = value
                store_record(tree, RULE_ID, record)
                self.assertFalse(trust(tree, RULE_ID)[0])
                record["record_digest"] = cert.digest_obj({k: v for k, v in record.items() if k != "record_digest"})
                store_record(tree, RULE_ID, record)
                trusted, findings = trust(tree, RULE_ID)
                self.assertFalse(trusted)
                self.assertTrue(any(f"extra_key ({key})" in f["detail"] for f in findings), findings)

    def test_approval_reference_must_match_the_record(self):
        evidence = [make_evidence()]
        tree = write_tree(self.base / "approval", [make_row(approval="auto-cert:1:" + "0" * 64)], evidence)
        record = certify(make_row(), evidence)
        store_record(tree, RULE_ID, record)
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertEqual(codes(findings), {"cert-approval-mismatch"})
        matching = write_tree(self.base / "approval-ok", [make_row(approval=cert.reference(record))], evidence)
        store_record(matching, RULE_ID, record)
        self.assertEqual(trust(matching, RULE_ID), (True, []))

    def test_automated_approval_without_a_record_is_untrusted(self):
        tree = write_tree(self.base / "noref", [make_row(approval="auto-cert:1:" + "a" * 64)], [make_evidence()])
        trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertEqual(codes(findings), {"cert-missing"})

    def test_unusable_rule_id_cannot_name_a_record_and_is_refused(self):
        tree = write_tree(self.base / "badid", [make_row("../escape")], [make_evidence("../escape")])
        self.assertIsNone(safety.certification_path(tree, "../escape"))
        self.assertIsNone(safety.certification_path(tree, "a/b"))
        self.assertIsNone(safety.certification_path(tree, "a..b"))
        self.assertIsNotNone(safety.certification_path(tree, RULE_ID))

    def test_unknown_provenance_refuses_the_certified_row(self):
        # the classification comes from the verified index; without it every source is unclassified and refused
        tree, _ = self.tree_with_record("noindex")
        kb = load_knowledge(tree)
        trusted, findings = safety.fix_row_trusted(rule_in(tree, RULE_ID), tree, [make_evidence()], None, kb=kb)
        self.assertFalse(trusted)
        self.assertTrue(findings)

    def test_enterprise_confidentiality_flipped_in_the_index_is_a_finding(self):
        evidence = [make_evidence()]
        record = certify(make_row(), evidence)
        flipped = {COMMUNITY_SOURCE: {**PROVENANCE[0], "kind": "GIT_ENTERPRISE"}}
        findings = cert.verify(make_row(), evidence, record,
                               source_confidentiality=cert.source_confidentiality_from_index(flipped),
                               change_class=CHANGE_CLASS)
        self.assertIn("source_confidentiality_changed", codes(findings))

    def test_verification_is_cached_per_process_and_reruns_when_an_input_changes(self):
        tree, record = self.tree_with_record("cache")
        with mock.patch.object(cert, "verify", wraps=cert.verify) as verify:
            self.assertEqual(trust(tree, RULE_ID), (True, []))
            self.assertEqual(trust(tree, RULE_ID), (True, []))
            self.assertEqual(verify.call_count, 1)
            tampered = copy.deepcopy(record)
            tampered["outputs"]["negative_output_digest"] = "2" * 64  # stored digest not recomputed: must not reuse a pass
            store_record(tree, RULE_ID, tampered)
            trusted, _ = trust(tree, RULE_ID)
            self.assertFalse(trusted)
            self.assertEqual(verify.call_count, 2)

    def test_cached_verdict_does_not_survive_a_change_of_the_transformer(self):
        tree, _ = self.tree_with_record("transformer")
        self.assertTrue(trust(tree, RULE_ID)[0])
        with mock.patch.object(imp, "rewrite_imported_symbol_edits", lambda *args, **kw: []):
            trusted, findings = trust(tree, RULE_ID)
        self.assertFalse(trusted)
        self.assertIn("transformer_source_changed", " ".join(f["detail"] for f in findings))


class InheritedTrustTests(ComposedTestCase):
    """D3 at the predicate: a shipped row is accepted only by byte identity with a verified baseline."""

    def shipped_fix_row(self):
        kb = load_knowledge(KNOWLEDGE_ROOT)
        return copy.deepcopy(next(r for r in kb.rules if r.get("maturity") == "FIX_ENABLED"))

    def test_byte_identical_shipped_row_is_inherited_when_the_baseline_is_verified(self):
        row = self.shipped_fix_row()
        with mock.patch.object(safety, "builtin_digest", return_value="a" * 64):
            self.assertEqual(safety.fix_row_trusted(row, self.base, [], None, kb=load_knowledge(KNOWLEDGE_ROOT),
                                                    inherit=True), (True, []))

    def test_changed_row_with_a_shipped_id_is_not_inherited(self):
        row = self.shipped_fix_row()
        row["message"] = row.get("message", "") + " (changed)"
        with mock.patch.object(safety, "builtin_digest", return_value="a" * 64):
            self.assertFalse(safety.is_inherited_builtin(row))
            trusted, findings = safety.fix_row_trusted(row, self.base, [], None, kb=load_knowledge(KNOWLEDGE_ROOT),
                                                       inherit=True)
        self.assertFalse(trusted)
        self.assertTrue(findings)

    def test_unverifiable_baseline_disables_inheritance(self):
        row = self.shipped_fix_row()
        with mock.patch.object(safety, "builtin_digest", side_effect=OSError("unreadable")):
            self.assertIsNone(safety.shipped_baseline_digest())
            self.assertFalse(safety.is_inherited_builtin(row))

    def test_inheritance_is_on_by_default_and_requires_byte_identity(self):
        self.assertTrue(safety.INHERITED_TRUST_RECORDABLE)  # D3, owner-approved
        tree = write_tree(self.base / "p10", [make_row()], [make_evidence()], provenance=None)
        with mock.patch.object(safety, "_shipped_rule_rows", return_value={RULE_ID: safety._row_bytes(make_row())}), \
                mock.patch.object(safety, "builtin_digest", return_value="a" * 64):
            findings, inherited, _ = safety.package_fix_findings(tree)
            self.assertEqual(findings, [])
            self.assertEqual(inherited, [RULE_ID])
            # a changed row with the same id is NOT inherited and fails gates 1 to 5 as before
            tree2 = write_tree(self.base / "p10b", [dict(make_row(), message="changed")], [make_evidence()],
                               provenance=None)
            findings2, inherited2, _ = safety.package_fix_findings(tree2)
            self.assertEqual(inherited2, [])
            self.assertTrue(findings2)
            # inheritance can still be switched off per call
            off, none, _ = safety.package_fix_findings(tree, inherit=False)
        self.assertTrue(off)
        self.assertEqual(none, [])


class LoadTimeTests(ComposedTestCase):
    def handle(self, name):
        return KnowledgeHandle(root=self.base / name, release_id="kr-test", digest=None, builtin=False,
                               completeness=None)

    def load(self, name, rules, evidence=(), record=None, provenance=PROVENANCE):
        tree = write_tree(self.base / name, rules, list(evidence), provenance=provenance)
        if record is not None:
            store_record(tree, RULE_ID, record)
        return load_active_knowledge(self.handle(name))

    def rule(self, kb):
        return next(r for r in kb.rules if r["id"] == RULE_ID)

    def capped(self, kb):
        return [f for f in kb.load_findings if f.code == KAP_FIX_CAPPED]

    def test_valid_certified_row_stays_fix_enabled(self):
        evidence = [make_evidence()]
        kb = self.load("valid", [make_row()], evidence, certify(make_row(), evidence))
        self.assertEqual(self.rule(kb)["maturity"], "FIX_ENABLED")
        self.assertEqual(self.capped(kb), [])

    def test_corrupted_record_caps_the_row_with_the_gate_6_finding(self):
        kb = self.load("corrupt", [make_row()], [make_evidence()], record="{truncated")
        self.assertEqual(self.rule(kb)["maturity"], "DETECT_ONLY")
        [finding] = self.capped(kb)
        self.assertIn("gate 6 cert-unreadable", finding.message)

    def test_tampered_record_caps_the_row_with_the_verification_detail(self):
        evidence = [make_evidence()]
        record = certify(make_row(), evidence)
        record["outputs"]["positive_output_digest"] = "0" * 64
        kb = self.load("tampered", [make_row()], evidence, record=record)
        self.assertEqual(self.rule(kb)["maturity"], "DETECT_ONLY")
        [finding] = self.capped(kb)
        self.assertIn("certification record fails verification", finding.message)

    def test_missing_executor_caps_the_row_fail_closed(self):
        evidence = [make_evidence()]
        record = certify(make_row(), evidence)
        cert._reset_for_tests()
        kb = self.load("noexec", [make_row()], evidence, record=record)
        self.assertEqual(self.rule(kb)["maturity"], "DETECT_ONLY")
        [finding] = self.capped(kb)
        self.assertIn("cert-executor-missing", finding.message)

    def test_human_row_with_gates_passing_is_not_capped(self):
        # CHANGED (review item 1): the row binds a certified fixer, so the missing record caps it (gate 6 cert-missing)
        kb = self.load("human", [make_row()], [make_evidence()])
        self.assertEqual(self.rule(kb)["maturity"], "DETECT_ONLY")
        [finding] = self.capped(kb)
        self.assertIn("gate 6 cert-missing", finding.message)

    def test_gate_failing_row_is_capped_with_the_existing_message(self):
        kb = self.load("gatefail", [make_row()], [make_evidence()], provenance=None)  # gate 1 fails
        self.assertEqual(self.rule(kb)["maturity"], "DETECT_ONLY")
        [finding] = self.capped(kb)
        self.assertIn("gate 1", finding.message)


class ImportTests(ComposedTestCase):
    """P10 at package import, with real packages built by the real builder."""

    def release(self, name, rules, evidence, record=None):
        root = self.base / name
        shutil.copytree(KNOWLEDGE_ROOT / "official_sources", root / "knowledge" / "official_sources")
        tree = write_tree(root, rules, evidence)
        (root / "coverage").mkdir(exist_ok=True)
        (root / "coverage" / "coverage-manifest.json").write_bytes(b'{"items": []}\n')
        if record is not None:
            store_record(tree, RULE_ID, record)
        write_release_manifest(root, META)
        return export_package(root, self.base / f"{name}.ofkp").path

    def test_certified_rule_imports_when_the_record_verifies(self):
        evidence = [make_evidence()]
        archive = self.release("good", [make_row()], evidence, certify(make_row(), evidence))
        home = self.base / "kb-good"
        ensure_layout(home)
        result = import_package(archive, home, activate=True)
        self.assertEqual(result.downgraded_rules, ())
        installed = home / "releases" / result.release_id / "knowledge"
        self.assertEqual(rule_in(installed, RULE_ID)["maturity"], "FIX_ENABLED")

    def test_certified_rule_with_a_tampered_record_is_refused_at_p10(self):
        evidence = [make_evidence()]
        record = certify(make_row(), evidence)
        record["outputs"]["positive_output_digest"] = "0" * 64
        archive = self.release("bad", [make_row()], evidence, record)
        home = self.base / "kb-bad"
        ensure_layout(home)
        with self.assertRaises(PackageError) as ctx:
            import_package(archive, home, activate=True)
        self.assertEqual(ctx.exception.code, "P10")
        self.assertEqual(list((home / "releases").iterdir()), [])

    def test_certified_rule_with_a_tampered_record_is_capped_only_by_downgrade(self):
        evidence = [make_evidence()]
        record = certify(make_row(), evidence)
        record["outputs"]["positive_output_digest"] = "0" * 64
        archive = self.release("capped", [make_row()], evidence, record)
        home = self.base / "kb-capped"
        ensure_layout(home)
        result = import_package(archive, home, activate=True, downgrade_unverified=True)
        self.assertEqual(result.downgraded_rules, (RULE_ID,))
        installed = home / "releases" / result.release_id / "knowledge"
        self.assertEqual(rule_in(installed, RULE_ID)["maturity"], "DETECT_ONLY")

    def test_gate_passing_row_without_a_record_is_refused_at_import(self):
        # CHANGED (review item 1): a certified-fixer row with no record is refused at P10 (it was imported before)
        archive = self.release("plain", [make_row()], [make_evidence()])
        home = self.base / "kb-plain"
        ensure_layout(home)
        with self.assertRaises(PackageError) as ctx:
            import_package(archive, home, activate=True)
        self.assertEqual(ctx.exception.code, "P10")


class PromoteGuardTests(unittest.TestCase):
    def test_promote_refuses_an_automated_reference_as_a_human_approval(self):
        for ref in ("auto-cert:1:" + "a" * 64, "AUTO-CERT:1:" + "a" * 64, " auto-cert:1:x "):
            with self.subTest(ref=ref):
                with self.assertRaises(promote_mod.PromoteError) as ctx:
                    promote_mod._approval_ref(ref, "alice")
                self.assertIn("auto-cert", str(ctx.exception))

    def test_promote_refuses_before_touching_the_tree(self):
        with self.assertRaises(promote_mod.PromoteError):
            promote_mod.promote(Path("/nonexistent-tree"), RULE_ID, approval="auto-cert:1:" + "a" * 64,
                                author="alice")

    def test_a_human_approval_is_still_accepted(self):
        self.assertEqual(promote_mod._approval_ref("owner-ticket-42", "alice"), "owner-ticket-42")


if __name__ == "__main__":
    unittest.main()
