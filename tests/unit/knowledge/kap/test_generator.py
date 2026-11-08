"""TST-011-058 (REQ-KAP-016, REQ-KAP-014): candidate generation is deterministic, never produces FIX_ENABLED or fixer
candidates, links an existing matching rule instead of duplicating it, keeps unconfirmed rename and replacement
candidates detect-only with no replacement mapping, needs no code for a new version pair, marks unofficial evidence
review_required, and invents no evidence for a change without a template.

Contract candidate-rule-generation. Fixtures are built in memory in temporary directories.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.candidates.templates import TemplateError, load_templates
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.builtins import build_registries  # composition root: the verified detector table

KNOWN_DETECTORS = build_registries().extract_toolkit.detectors

CLOCK = lambda: "2026-11-08T00:00:00Z"  # noqa: E731
DETECTOR = "odooflux.rules.python.generic:flag_class_attribute"


def _snap(sid_hex: str, digest_hex: str) -> dict:
    return {"snapshot_id": "ss-" + sid_hex, "snapshot_digest": digest_hex * 64}


def _loc(path="addons/base/models/res_partner.py", line=12):
    return {"snapshot_id": "ss-0123456789ab", "path": path, "line": line, "sha256": "cd" * 32}


def _draft(subject="res.partner::field::foo", kind="field", cls="REMOVED", detail=None, domain="python_orm"):
    return {"domain": domain, "kind": kind, "subject_key": subject, "class": cls, "detail": detail or {},
            "locations": [_loc()], "proposed_by": "DETERMINISTIC"}


def _ledger(drafts, step="17-18", from_hex="1", to_hex="2"):
    return Ledger.create(step, _snap("111111111111", from_hex), _snap("222222222222", to_hex), drafts, clock=CLOCK)


def _source(official=True):
    return {"source_id": "odoo-community-17.0" if official else "oca-web-17.0", "official": official,
            "url": "https://github.com/odoo/odoo/tree/" + "a" * 40, "repository": "odoo/odoo",
            "revision": "a" * 40, "branch": "17.0"}


def _run(ledger, tree_root, **over):
    kwargs = {"tree_root": tree_root, "source": _source(), "checked_on": "2026-11-08"}
    kwargs.update(over)
    return gen.generate(ledger, **kwargs, known_detectors=KNOWN_DETECTORS)


def _tree(rows=()):
    root = Path(tempfile.mkdtemp(prefix="kap-gen-"))
    (root / "compatibility").mkdir()
    (root / "evidence").mkdir()
    (root / "compatibility" / "17-18.rules.json").write_text(json.dumps(list(rows)), encoding="utf-8")
    return root


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tree = _tree()

    def test_generation_deterministic(self):
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]
        before = _ledger(drafts).to_dict()
        first = _run(_ledger(drafts), self.tree, templates=load_templates(known_detectors=KNOWN_DETECTORS))
        second = _run(_ledger(drafts), self.tree, templates=load_templates(known_detectors=KNOWN_DETECTORS))
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        ledger = _ledger(drafts)
        once = _run(ledger, self.tree)
        twice = _run(ledger, self.tree)
        self.assertEqual(canonical_bytes(once), canonical_bytes(twice))
        self.assertEqual(ledger.to_dict(), before, "generation must not mutate the ledger")

    def test_no_fix_enabled_candidates(self):
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "SIGNATURE_CHANGED")]
        result = _run(_ledger(drafts), self.tree)
        self.assertTrue(result["candidates"])
        for cand in result["candidates"]:
            self.assertIsNone(cand["rule"]["fixer_ref"])
            self.assertIn(cand["rule"]["maturity"], ("DRAFT", "DETECT_ONLY"))
            self.assertNotEqual(cand["rule"]["maturity"], "FIX_ENABLED")
            self.assertEqual(cand["status"], "PROPOSED")
            self.assertEqual(cand["origin"], "DETERMINISTIC")

    def test_existing_rule_linked(self):
        existing = {"id": "17-18.python_orm.existing-attr", "step": "17-18", "category": "python_orm",
                    "severity": "INFO", "maturity": "DETECT_ONLY", "origin": "MANUAL", "risk": "MEDIUM",
                    "evidence": [], "detector_ref": DETECTOR, "fixer_ref": None,
                    "params": {"attribute": "foo"}, "tests": {}}
        tree = _tree([existing])
        result = _run(_ledger([_draft()]), tree)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(result["linked"]), 1)
        link = result["linked"][0]
        self.assertEqual(link["rule_ids"], ["17-18.python_orm.existing-attr"])
        disposition = [d for d in result["dispositions"] if d["change_id"] == link["change_id"]][0]
        self.assertEqual(disposition["disposition"], "EXISTING_RULE_LINKED")
        self.assertEqual(disposition["rule_ids"], ["17-18.python_orm.existing-attr"])
        self.assertEqual(len(result["evidence"]), 1, "the link is still supported by evidence")

    def test_rename_candidate_detect_only(self):
        drafts = [_draft("res.partner::method::old_name", "method", "RENAMED_CANDIDATE",
                         {"from": "old_name", "to": "new_name", "score": 60, "basis": "body", "candidates": []})]
        result = _run(_ledger(drafts), self.tree)
        self.assertEqual(len(result["candidates"]), 1)
        rule = result["candidates"][0]["rule"]
        self.assertIn(rule["maturity"], ("DRAFT", "DETECT_ONLY"))
        self.assertIsNone(rule["fixer_ref"])
        self.assertTrue(rule["review_required"])
        self.assertIn("Candidate", rule["message"])
        self.assertNotIn("new_name", json.dumps(rule))
        disposition = result["dispositions"][0]
        self.assertEqual(disposition["disposition"], "HUMAN_REVIEW")
        self.assertTrue(disposition["rationale"])

    def test_unconfirmed_replacement_not_mapped(self):
        drafts = [_draft("res.partner::method::legacy", "method", "REPLACEMENT_CANDIDATE",
                         {"replacement": "modern_api", "score": 50, "basis": "doc", "candidates": []})]
        result = _run(_ledger(drafts), self.tree)
        self.assertEqual(len(result["candidates"]), 1)
        text = json.dumps(result["candidates"][0]["rule"])
        self.assertNotIn("modern_api", text, "an unconfirmed replacement must never become a mapping")
        self.assertIsNone(result["candidates"][0]["rule"]["fixer_ref"])

    def test_new_version_pair_no_code(self):
        result = _run(_ledger([_draft()], step="18-19", from_hex="3", to_hex="4"), self.tree)
        self.assertEqual(len(result["candidates"]), 1)
        rule = result["candidates"][0]["rule"]
        self.assertTrue(rule["id"].startswith("18-19.python_orm.cand-"))
        self.assertEqual(result["candidates"][0]["applicability"]["source_versions"], ["18.0"])
        self.assertEqual(result["candidates"][0]["applicability"]["target_versions"], ["19.0"])

    def test_verified_run_marks_summary_and_candidates(self):
        result = _run(_ledger([_draft()]), self.tree, templates=load_templates(known_detectors=KNOWN_DETECTORS))
        self.assertIs(result["detectors_verified"], True)
        self.assertTrue(result["candidates"])
        self.assertTrue(all(c["detectors_verified"] is True for c in result["candidates"]))

    def test_unverified_run_is_visible_on_summary_and_every_candidate(self):
        result = _run(_ledger([_draft()]), self.tree, templates=load_templates(verify=False))
        self.assertIs(result["detectors_verified"], False)
        self.assertTrue(result["candidates"])
        self.assertTrue(all(c["detectors_verified"] is False for c in result["candidates"]))

    def test_unofficial_evidence_review_required(self):
        result = gen.generate(_ledger([_draft()]), tree_root=self.tree, source=_source(official=False),
                              checked_on="2026-11-08", known_detectors=KNOWN_DETECTORS)
        self.assertIs(result["evidence"][0]["official"], False)
        rule = result["candidates"][0]["rule"]
        self.assertTrue(rule["review_required"])
        self.assertIn("Supplementary", rule["message"])

    def test_local_clone_source_without_repository_generates_schema_valid_evidence(self):
        # A raw spec from a local clone: no repository field; identity comes from expected_origin.
        source = {"source_id": "odoo-community-17.0", "official": True, "url": "local:/home/maint/clones/odoo",
                  "expected_origin": "https://github.com/odoo/odoo", "revision": "a" * 40, "branch": "17.0"}
        result = gen.generate(_ledger([_draft()]), tree_root=self.tree, source=source, checked_on="2026-11-08",
                              known_detectors=KNOWN_DETECTORS)
        self.assertTrue(result["evidence"])
        for record in result["evidence"]:
            self.assertEqual(record["repository"], "odoo/odoo")
            self.assertEqual(record["url"], "https://github.com/odoo/odoo/tree/" + "a" * 40)
            self.assertNotIn("/home/maint", json.dumps(record))

    def test_local_clone_source_without_identity_refused(self):
        source = {"source_id": "odoo-community-17.0", "official": True, "url": "local:/home/maint/clones/odoo",
                  "revision": "a" * 40, "branch": "17.0"}
        with self.assertRaises(eb.SourceIdentityError):
            gen.generate(_ledger([_draft()]), tree_root=self.tree, source=source, checked_on="2026-11-08",
                         known_detectors=KNOWN_DETECTORS)

    def test_template_unknown_detector_ref_error(self):
        bad = [{"template_id": "py-bad", "description": "x",
                "match": {"domain": "python_orm", "class": "REMOVED", "kind": "field"},
                "rule": {"category": "python_orm", "detector_ref": "odooflux.rules.python.generic:nope",
                         "fixer_ref": None, "params_from": {"attribute": "subject.name"}, "risk": "MEDIUM",
                         "review_required": True},
                "confidence": "MEDIUM", "tests": {"generate_skeleton": True}}]
        with self.assertRaises(TemplateError):
            _run(_ledger([_draft()]), self.tree, templates=bad)

    def test_no_template_no_evidence(self):
        result = _run(_ledger([_draft("res.partner::xml::thing", "view", "ADDED", domain="xml_view")]), self.tree)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(len(result["skipped"]), 1)

    def test_apply_dispositions_uses_ledger_api(self):
        ledger = _ledger([_draft(), _draft("res.partner::method::legacy", "method", "REPLACEMENT_CANDIDATE",
                                           {"replacement": "modern_api"})])
        result = _run(ledger, self.tree)
        gen.apply_dispositions(ledger, result, tree_root=self.tree)
        dispositions = {r["disposition"] for r in ledger.records()}
        # Only the unconfirmed replacement goes to HUMAN_REVIEW; the removed field stays UNRESOLVED.
        self.assertEqual(dispositions, {"UNRESOLVED", "HUMAN_REVIEW"})
        self.assertEqual(ledger.verify(), [])


class EvidenceIdAllocationTests(unittest.TestCase):
    """Ids are never reused: the allocator also skips every id held by the candidate store (rejected included)."""

    def setUp(self):
        self.tree = _tree()

    def _persist_first_run(self, status="REJECTED"):
        """Generate once and persist its evidence and candidates under candidates/, as the CLI does."""
        first = _run(_ledger([_draft()]), self.tree)
        store = self.tree / "candidates"
        (store / "evidence").mkdir(parents=True, exist_ok=True)
        for record in first["evidence"]:
            (store / "evidence" / f"{record['id']}.json").write_text(json.dumps(record, sort_keys=True),
                                                                    encoding="utf-8")
        for cand in first["candidates"]:
            body = {**cand, "status": status}
            (store / f"{cand['candidate_id']}.json").write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
        return first

    def test_rejected_candidate_evidence_id_not_reused(self):
        first = self._persist_first_run("REJECTED")
        self.assertEqual([e["id"] for e in first["evidence"]], ["EV-001"])
        kept = self.tree / "candidates" / "evidence" / "EV-001.json"
        before = kept.read_bytes()
        # The same change is already held by a REJECTED candidate: it is skipped, so no evidence is written at all.
        again = _run(_ledger([_draft()]), self.tree)
        self.assertEqual(again["evidence"], [])
        # A genuinely new change still gets a fresh id that the rejected record does not hold.
        fresh = _run(_ledger([_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]), self.tree)
        self.assertEqual([e["id"] for e in fresh["evidence"]], ["EV-002"])
        self.assertEqual(fresh["candidates"][0]["rule"]["evidence"], ["EV-002"])
        self.assertEqual(kept.read_bytes(), before, "the rejected evidence file must never be overwritten")

    def test_reserved_ids_are_skipped(self):
        result = _run(_ledger([_draft()]), self.tree, reserved_ids=["EV-001", "EV-002"])
        self.assertEqual([e["id"] for e in result["evidence"]], ["EV-003"])

    def test_reserved_ids_default_is_empty(self):
        result = _run(_ledger([_draft()]), self.tree, reserved_ids=())
        self.assertEqual([e["id"] for e in result["evidence"]], ["EV-001"])

    def test_tree_evidence_clash_is_skipped(self):
        (self.tree / "evidence" / "EV-001.json").write_text("{}", encoding="utf-8")
        result = _run(_ledger([_draft()]), self.tree)
        self.assertEqual([e["id"] for e in result["evidence"]], ["EV-002"])

    def test_evidence_cited_by_candidate_record_is_skipped(self):
        store = self.tree / "candidates"
        store.mkdir()
        cand = {"candidate_id": "CR-0123456789abcdef", "status": "REJECTED", "rule": {"evidence": ["EV-004"]}}
        (store / "CR-0123456789abcdef.json").write_text(json.dumps(cand), encoding="utf-8")
        result = _run(_ledger([_draft()]), self.tree)
        self.assertEqual([e["id"] for e in result["evidence"]], ["EV-005"])

    def test_allocation_deterministic_with_store(self):
        self._persist_first_run("REJECTED")
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]
        first = _run(_ledger(drafts), self.tree, reserved_ids=["EV-002"])
        second = _run(_ledger(drafts), self.tree, reserved_ids=["EV-002"])
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        # The first change already has a (rejected) candidate and is skipped; only the new change gets evidence.
        self.assertEqual([e["id"] for e in first["evidence"]], ["EV-003"])


class ExistingCandidateTests(unittest.TestCase):
    """Generation never overwrites, resets or resurrects a candidate of any status, and creates no evidence for it."""

    def setUp(self):
        self.tree = _tree()

    def _persist(self, status):
        return _persist_into(self.tree, status)

    def test_result_has_existing_key_empty_without_store(self):
        result = _run(_ledger([_draft()]), self.tree)
        self.assertEqual(result["existing"], [])

    def test_existing_candidate_of_any_status_is_skipped(self):
        for status in ("PROPOSED", "CONFLICT", "ACCEPTED", "REJECTED"):
            with self.subTest(status=status):
                tree = _tree()
                cand = _persist_into(tree, status)
                ledger = _ledger([_draft()])
                before = canonical_bytes(ledger.to_dict())
                result = _run(ledger, tree)
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["evidence"], [])
                self.assertEqual(result["dispositions"], [])
                self.assertEqual(result["linked"], [])
                self.assertEqual(result["existing"], [{"candidate_id": cand["candidate_id"], "status": status,
                                                       "change_id": cand["change_id"]}])
                self.assertEqual(canonical_bytes(ledger.to_dict()), before, "the ledger must not change")

    def test_new_change_is_generated_next_to_existing(self):
        existing = self._persist("REJECTED")
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]
        result = _run(_ledger(drafts), self.tree)
        self.assertEqual([e["change_id"] for e in result["existing"]], [existing["change_id"]])
        self.assertEqual(len(result["candidates"]), 1)
        self.assertNotEqual(result["candidates"][0]["candidate_id"], existing["candidate_id"])
        self.assertNotIn(existing["change_id"], [d["change_id"] for d in result["dispositions"]])

    def test_existing_listing_is_deterministic(self):
        self._persist("ACCEPTED")
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]
        first = _run(_ledger(drafts), self.tree)
        second = _run(_ledger(drafts), self.tree)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))


def _persist_into(tree, status):
    """Write one candidate record for `_draft()` with `status` into `tree`, as an earlier run would have."""
    first = _run(_ledger([_draft()]), tree)
    store = tree / "candidates"
    (store / "evidence").mkdir(parents=True, exist_ok=True)
    for record in first["evidence"]:
        (store / "evidence" / f"{record['id']}.json").write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    cand = first["candidates"][0]
    body = {**cand, "status": status}
    (store / f"{cand['candidate_id']}.json").write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return body

    def test_no_candidate_store_no_behaviour_change(self):
        self.assertFalse((self.tree / "candidates").exists())
        drafts = [_draft(), _draft("res.partner::method::bar", "method", "REMOVED")]
        result = _run(_ledger(drafts), self.tree)
        self.assertEqual([e["id"] for e in result["evidence"]], ["EV-001", "EV-002"])
        explicit = _run(_ledger(drafts), self.tree, reserved_ids=())
        self.assertEqual(canonical_bytes(result), canonical_bytes(explicit))


if __name__ == "__main__":
    unittest.main()
