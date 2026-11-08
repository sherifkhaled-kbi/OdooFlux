"""TST-011-009 (REQ-KAP-018, REQ-KAP-027, REQ-KAP-039): promotion gates 1 to 5 for FIX_ENABLED rules in a tree.

Gate 6 (`--approval`) belongs to `promote` (T025), not to this module. Built-in rules are grandfathered: they are checked
only when `include_builtin=True` is passed.

Provenance (gate 1): a record's own `official: true` is never trusted. A linked record counts as official only when its
source is resolved in `provenance/sources.json` (next to the tree, or passed explicitly) as official, usable, pinned,
on the allow-list, and the record carries a content digest. A claim that fails is `official-claim-unsupported`.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.release.safety import fix_gate_findings

BASE_EVIDENCE = {
    "id": "EV-900",
    "rule_ids": ["16-17.python.synthetic-fix"],
    "category": "orm",
    "source_applicability": {"from": "16.0", "to": "16.0"},
    "target_applicability": {"from": "17.0", "to": None},
    "description": "Synthetic evidence for the safety gate tests",
    "url": "https://github.com/odoo/odoo/blob/0000/odoo/api.py#L1",
    "repository": "odoo/odoo",
    "revision": "0" * 40,
    "locations": [{"branch": "16.0", "revision": "0" * 40, "path": "odoo/api.py", "line": 1, "match": "x",
                   "kind": "present", "content_sha256": "c" * 64}],
    "detection_method": "grep on pinned source",
    "proposed_transformation": "rename keyword",
    "risk": "LOW",
    "required_validation": ["python_runtime"],
    "status": "DOCUMENTED_NOT_TESTED",
    "checked_on": "2026-11-01",
    "checked_by": "test",
    "official": True,
    "source_id": "odoo-community-16.0",
}

PROVENANCE = [{
    "source_id": "odoo-community-16.0",
    "revision": "0" * 40,
    "snapshot_digest": "sha256:" + "b" * 64,
    "official": True,
    "status": "VERIFIED",
    "kind": "GIT_COMMUNITY",
    "url": "https://github.com/odoo/odoo/",
}]

BASE_RULE = {
    "id": "16-17.python.synthetic-fix",
    "step": "16-17",
    "category": "python_orm",
    "maturity": "FIX_ENABLED",
    "risk": "LOW",
    "evidence": ["EV-900"],
    "detector_ref": "odooflux.rules.python.generic:flag_decorator",
    "fixer_ref": "odooflux.rules.python.generic:remove_decorator",
    "review_required": False,
    "tests": {"positive": "TST-011-009", "negative": "TST-011-009", "idempotence": "TST-011-009"},
    "conflicts_with": [],
    "origin": "MANUAL",
}


def _tree(root: Path, rules, evidence) -> Path:
    (root / "compatibility").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    (root / "compatibility" / "16-17.rules.json").write_text(json.dumps(rules), encoding="utf-8")
    for record in evidence:
        (root / "evidence" / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    return root


def _write_provenance(parent: Path, entries) -> None:
    (parent / "provenance").mkdir(parents=True, exist_ok=True)
    (parent / "provenance" / "sources.json").write_text(json.dumps(entries), encoding="utf-8")


def _with(base: dict, **changes) -> dict:
    out = json.loads(json.dumps(base))
    for key, value in changes.items():
        if value is _DELETE:
            out.pop(key, None)
        else:
            out[key] = value
    return out


_DELETE = object()


def _snapshot(origin_url="https://github.com/odoo/odoo") -> dict:
    """A SourceSnapshot for odoo-community-16.0 whose snapshot_digest is recomputed from its entries."""
    entries = [{"path": "addons/sale_demo.py", "sha256": "d" * 64, "size": 1, "kind": "python"}]
    body = {"source_id": "odoo-community-16.0", "revision": "0" * 40, "entries": entries}
    digest = digest_obj(body)
    return {"snapshot_id": "ss-" + digest[:12], **body, "snapshot_digest": digest,
            "created_at": "2026-11-08T10:00:00Z", "limits": {"excluded": []}, "origin_url": origin_url}


class SafetyGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self._n = 0

    def tearDown(self):
        self._tmp.cleanup()

    def _gated(self, name, rules, evidence, provenance=PROVENANCE):
        """A tree at base/<name>/knowledge with provenance at base/<name>/provenance/sources.json (none if None)."""
        parent = self.base / name
        root = _tree(parent / "knowledge", rules, evidence)
        if provenance is not None:
            _write_provenance(parent, provenance)
        return root

    def _check(self, rule, evidence=None, provenance=PROVENANCE):
        self._n += 1
        evidence = [BASE_EVIDENCE] if evidence is None else evidence
        return fix_gate_findings(self._gated(f"t{self._n}", [rule], evidence, provenance))

    def _gate1_codes(self, findings):
        return [f["code"] for f in findings if f["gate"] == 1]

    def test_baseline_passes_all_gates(self):
        self.assertEqual([], self._check(BASE_RULE))

    def test_each_gate_blocks(self):
        other = {**BASE_RULE, "id": "12-13.python.other", "step": "12-13", "conflicts_with": []}
        cases = {
            1: ([_with(BASE_RULE, evidence=[])], [BASE_EVIDENCE]),                       # no linked evidence
            2: ([_with(BASE_RULE, step=_DELETE)], [BASE_EVIDENCE]),                      # applicability: step
            3: ([_with(BASE_RULE, tests={"positive": "a"})], [BASE_EVIDENCE]),           # tests not registered
            4: ([_with(BASE_RULE, conflicts_with=["12-13.python.other"]), other], [BASE_EVIDENCE]),
            5: ([_with(BASE_RULE, fixer_ref=None)], [BASE_EVIDENCE]),                    # fixer missing
        }
        for gate, (rules, evidence) in cases.items():
            with self.subTest(gate=gate):
                root = self._gated(f"g{gate}", rules, evidence)
                findings = fix_gate_findings(root)
                self.assertTrue(any(f["gate"] == gate for f in findings), findings)
                self.assertTrue(all(f["gate"] == gate for f in findings), findings)

    def test_gate1_unverified_or_conflicting_evidence_blocks(self):
        for status in ("UNVERIFIED", "CONFLICTING"):
            with self.subTest(status=status):
                ev = _with(BASE_EVIDENCE, status=status)
                findings = self._check(BASE_RULE, evidence=[ev])
                self.assertTrue(any(f["gate"] == 1 for f in findings), findings)

    def test_gate1_missing_evidence_record_blocks(self):
        findings = self._check(BASE_RULE, evidence=[])
        self.assertTrue(any(f["gate"] == 1 and "EV-900" in f["detail"] for f in findings), findings)

    def test_gate2_missing_applicability_blocks(self):
        ev = _with(BASE_EVIDENCE, target_applicability=_DELETE)
        findings = self._check(BASE_RULE, evidence=[ev])
        self.assertTrue(any(f["gate"] == 2 for f in findings), findings)

    def test_gate3_missing_idempotence_blocks(self):
        rule = _with(BASE_RULE, tests={"positive": "a", "negative": "b", "idempotence": ""})
        self.assertTrue(any(f["gate"] == 3 for f in self._check(rule)))

    def test_gate5_review_required_blocks(self):
        findings = self._check(_with(BASE_RULE, review_required=True))
        self.assertTrue(any(f["gate"] == 5 for f in findings), findings)

    def test_origin_claim_never_grandfathers_a_rule(self):
        """REQ-KAP-027: a release is not trusted to describe itself. An origin-less (or origin BUILTIN) FIX_ENABLED row
        that is not the shipped built-in row goes through gates 1 to 5 whatever it claims."""
        for origin in (_DELETE, "BUILTIN"):
            claimed = _with(BASE_RULE, origin=origin, id="16-17.python.spoofed-builtin")
            root = self._gated(f"spoof-{origin}", [claimed], [])  # no evidence at all
            findings = fix_gate_findings(root)
            self.assertTrue(any(f["gate"] == 1 and f["rule_id"] == "16-17.python.spoofed-builtin" for f in findings),
                            (origin, findings))

    def test_shipped_builtin_rows_are_grandfathered_and_altered_ones_are_not(self):
        from odooflux.knowledge.loader import load_knowledge
        shipped = next(r for r in load_knowledge().rules if r.get("maturity") == "FIX_ENABLED")
        root = self._gated("shipped", [dict(shipped)], [])
        self.assertEqual([], fix_gate_findings(root))  # identical shipped row: grandfathered
        self.assertTrue(fix_gate_findings(root, include_builtin=True))  # import path still gates it
        altered = dict(shipped)
        altered["message"] = str(shipped.get("message", "")) + " (altered)"
        root2 = self._gated("altered", [altered], [])
        self.assertTrue(any(f["rule_id"] == shipped["id"] for f in fix_gate_findings(root2)))

    def test_official_evidence_required(self):
        unofficial = _with(BASE_EVIDENCE, official=False)
        findings = self._check(BASE_RULE, evidence=[unofficial])
        self.assertTrue(any(f["gate"] == 1 for f in findings), findings)
        ai_only = _with(BASE_EVIDENCE, origin="AI_PROPOSED")
        findings = self._check(BASE_RULE, evidence=[ai_only])
        self.assertTrue(any(f["gate"] == 1 for f in findings), findings)
        absent = _with(BASE_EVIDENCE, official=_DELETE)
        self.assertTrue(any(f["gate"] == 1 for f in self._check(BASE_RULE, evidence=[absent])))

    def test_detect_only_rules_not_gated(self):
        rule = _with(BASE_RULE, maturity="DETECT_ONLY", fixer_ref=None, evidence=[])
        self.assertEqual([], self._check(rule))

    def test_builtin_tree_grandfathered(self):
        self.assertEqual([], fix_gate_findings(KNOWLEDGE_ROOT))

    # --- provenance: an official claim is supported only by a resolved, official, pinned, allow-listed source ---

    def test_record_official_flag_alone_is_not_enough(self):
        ev = _with(BASE_EVIDENCE, source_id=_DELETE)
        findings = self._check(BASE_RULE, evidence=[ev])
        self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_unknown_provenance_stays_unverified(self):
        findings = self._check(BASE_RULE, provenance=None)
        self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_unknown_source_id_is_unsupported(self):
        ev = _with(BASE_EVIDENCE, source_id="odoo-unknown-99")
        self.assertIn("official-claim-unsupported", self._gate1_codes(self._check(BASE_RULE, evidence=[ev])))

    def test_unofficial_source_is_unsupported(self):
        for changes in ({"official": False}, {"kind": "OCA"}, {"kind": "OPENUPGRADE"}):
            with self.subTest(changes=changes):
                entry = _with(PROVENANCE[0], **changes)
                findings = self._check(BASE_RULE, provenance=[entry])
                self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_unpinned_revision_is_unsupported(self):
        for revision in ("main", "v16.0", "0" * 39, "sha256:" + "b" * 63):
            with self.subTest(revision=revision):
                entry = _with(PROVENANCE[0], revision=revision)
                findings = self._check(BASE_RULE, provenance=[entry])
                self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_missing_content_sha256_is_unsupported(self):
        location = _with(BASE_EVIDENCE["locations"][0], content_sha256=_DELETE)
        ev = _with(BASE_EVIDENCE, locations=[location])
        self.assertIn("official-claim-unsupported", self._gate1_codes(self._check(BASE_RULE, evidence=[ev])))

    def test_ai_origin_is_unsupported(self):
        ev = _with(BASE_EVIDENCE, origin="AI_PROPOSED")
        findings = self._check(BASE_RULE, evidence=[ev])
        self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_url_outside_allow_list_is_unsupported(self):
        entry = _with(PROVENANCE[0], url="https://example.com/odoo/")
        findings = self._check(BASE_RULE, provenance=[entry])
        self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_unusable_status_is_unsupported(self):
        for status in ("DECLARED", "FAILED", "UNAVAILABLE"):
            with self.subTest(status=status):
                entry = _with(PROVENANCE[0], status=status)
                findings = self._check(BASE_RULE, provenance=[entry])
                self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_local_official_claim_without_verified_origin_is_refused(self):
        # a local: url is never official evidence by itself (no origin_url, no snapshot)
        entry = _with(PROVENANCE[0], url="local:/kb/odoo-16", kind="DIRECTORY")
        findings = self._check(BASE_RULE, provenance=[entry])
        self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)
        self.assertTrue(any("local source without verified origin" in f["detail"] for f in findings), findings)

    # --- local-origin claims: origin_url must be a verified origin and bound to the snapshot (identity contract) ---

    def _local_entry(self, snap, **changes):
        entry = {"source_id": "odoo-community-16.0", "revision": "0" * 40, "snapshot_id": snap["snapshot_id"],
                 "snapshot_digest": "sha256:" + snap["snapshot_digest"], "official": True, "status": "VERIFIED",
                 "kind": "GIT_COMMUNITY", "url": "local:/kb/odoo-16", "origin_url": "https://github.com/odoo/odoo"}
        for key, value in changes.items():
            if value is _DELETE:
                entry.pop(key, None)
            else:
                entry[key] = value
        return entry

    def _local_check(self, entry, snap=None):
        self._n += 1
        parent = self.base / f"local{self._n}"
        root = _tree(parent / "knowledge", [BASE_RULE], [BASE_EVIDENCE])
        _write_provenance(parent, [entry])
        if snap is not None:
            (parent / "snapshots").mkdir()
            (parent / "snapshots" / f"{snap['snapshot_id']}.json").write_text(json.dumps(snap), encoding="utf-8")
        return fix_gate_findings(root)

    def test_local_origin_with_bound_snapshot_is_supported(self):
        snap = _snapshot()
        self.assertEqual([], self._local_check(self._local_entry(snap), snap))

    def test_local_origin_not_on_allowlist_is_refused(self):
        snap = _snapshot(origin_url="https://example.com/odoo")
        entry = self._local_entry(snap, origin_url="https://example.com/odoo")
        findings = self._local_check(entry, snap)
        self.assertTrue(any(f["code"] == "official-claim-unsupported" and "OFFICIAL_IDENTITY_UNVERIFIED" in f["detail"]
                            for f in findings), findings)

    def test_local_only_url_without_origin_refused_with_identity_code(self):
        snap = _snapshot()
        entry = self._local_entry(snap, origin_url=_DELETE)
        findings = self._local_check(entry, snap)
        self.assertTrue(any("local source without verified origin" in f["detail"]
                            and "OFFICIAL_IDENTITY_UNVERIFIED" in f["detail"] for f in findings), findings)

    def test_edited_provenance_revision_or_digest_is_refused(self):
        snap = _snapshot()
        for changes in ({"revision": "1" * 40}, {"snapshot_digest": "sha256:" + "e" * 64}):
            with self.subTest(changes=changes):
                findings = self._local_check(self._local_entry(snap, **changes), snap)
                self.assertIn("official-claim-unsupported", self._gate1_codes(findings), findings)

    def test_missing_or_tampered_snapshot_is_refused(self):
        snap = _snapshot()
        self.assertIn("official-claim-unsupported", self._gate1_codes(self._local_check(self._local_entry(snap))))
        tampered = json.loads(json.dumps(snap))
        tampered["entries"][0]["sha256"] = "e" * 64
        self.assertIn("official-claim-unsupported", self._gate1_codes(self._local_check(self._local_entry(snap),
                                                                                       tampered)))

    def test_provenance_read_from_release_layout(self):
        self.assertEqual([], self._check(BASE_RULE))  # provenance/sources.json beside the tree is read
        self._n += 1
        parent = self.base / f"corrupt{self._n}"
        root = self._gated(parent.name, [BASE_RULE], [BASE_EVIDENCE], provenance=None)
        (parent / "provenance").mkdir()
        (parent / "provenance" / "sources.json").write_text("{not json", encoding="utf-8")
        self.assertIn("official-claim-unsupported", self._gate1_codes(fix_gate_findings(root)))

    def test_explicit_provenance_parameter_overrides_file(self):
        root = self._gated("explicit", [BASE_RULE], [BASE_EVIDENCE], provenance=None)
        self.assertEqual([], fix_gate_findings(root, provenance=PROVENANCE))
        self.assertIn("official-claim-unsupported", self._gate1_codes(fix_gate_findings(root, provenance=[])))

    # --- gate 4: the A001..A006 authoring checks (reused from authoring/checks.py) ---

    def test_gate4_authoring_duplicate_blocks(self):
        twin = {**BASE_RULE, "id": "16-17.python.twin", "maturity": "DETECT_ONLY", "fixer_ref": None}
        root = self._gated("dup", [BASE_RULE, twin], [BASE_EVIDENCE])
        findings = fix_gate_findings(root)
        self.assertTrue(any(f["gate"] == 4 and f["code"] == "A002" and f["rule_id"] == BASE_RULE["id"]
                            for f in findings), findings)

    def test_gate4_a005_error_between_fix_enabled_rules_blocks_both(self):
        first = _with(BASE_RULE, params={"qualified": "q", "new_name": "A"})
        second = _with(BASE_RULE, id="16-17.python.synthetic-fix-2", params={"qualified": "q", "new_name": "B"})
        root = self._gated("a005", [first, second], [BASE_EVIDENCE])
        findings = fix_gate_findings(root)
        blocked = {f["rule_id"] for f in findings if f["gate"] == 4 and f["code"] == "A005"}
        self.assertEqual({first["id"], second["id"]}, blocked, findings)

    def test_gate4_a005_warning_does_not_block(self):
        fixed = _with(BASE_RULE, params={"qualified": "q", "new_name": "A"})
        detect = _with(BASE_RULE, id="16-17.python.detect-only", maturity="DETECT_ONLY", fixer_ref=None,
                       params={"qualified": "q", "new_name": "B"})
        root = self._gated("a005w", [fixed, detect], [BASE_EVIDENCE])
        self.assertEqual([], fix_gate_findings(root))

    def test_gate4_unknown_reference_blocks(self):
        rule = _with(BASE_RULE, depends_on=["16-17.python.gone"])
        findings = self._check(rule)
        self.assertTrue(any(f["gate"] == 4 and f["code"] == "A003" for f in findings), findings)

    def test_gate4_unknown_evidence_blocks(self):
        rule = _with(BASE_RULE, evidence=["EV-900", "EV-404"])
        findings = self._check(rule)
        self.assertTrue(any(f["gate"] == 4 and f["code"] == "A006" for f in findings), findings)

    def test_gate4_authoring_error_on_unfixed_rule_not_gated(self):
        plain = _with(BASE_RULE, id="16-17.python.plain", maturity="DETECT_ONLY", fixer_ref=None,
                      depends_on=["16-17.python.gone"])
        root = self._gated("scope", [plain], [BASE_EVIDENCE])
        self.assertEqual([], fix_gate_findings(root))


if __name__ == "__main__":
    unittest.main()
