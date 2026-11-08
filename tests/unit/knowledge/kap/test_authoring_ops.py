"""TST-011-024 (REQ-KAP-019, REQ-KAP-021): authoring verbs create, edit, disable, enable, retire, inspect, validate,
history, link-evidence and add-test.

Every test works on a copy of the data directories of the built-in tree inside a temporary directory. The repository
copy is only read. A failed verb must leave every file of the copy byte-identical (test_failed_validation_rolls_back).
"""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.release.canonical import digest_obj

DATA_DIRS = ("evidence", "compatibility", "official_sources")
RULE_ID = "17-18.manual.example-check"
AT = "2026-11-08T10:00:00Z"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _row(**over):
    row = {
        "id": RULE_ID,
        "step": "17-18",
        "category": "xml",
        "risk": "LOW",
        "evidence": [],
        "detector_ref": "det.example",
        "fixer_ref": None,
        "tests": [],
        "file_kinds": ["xml"],
        "params": {"tag": "field"},
        "message": "example",
    }
    row.update(over)
    return row


class AuthoringOpsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        kb = load_knowledge(KNOWLEDGE_ROOT)
        ids = sorted(k for k in kb.evidence if k.startswith("EV-"))
        self.evidence_id, self.other_evidence = ids[0], ids[1]
        self.rules_file = self.tree / "compatibility" / "17-18.rules.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _create(self, author="alice", **over):
        over.setdefault("evidence", [self.evidence_id])  # every rule must cite evidence (E005)
        return ops.create_rule(self.tree, _row(**over), evidence=(), author=author, at=AT)

    def _rule_row(self, rule_id=RULE_ID):
        for path in sorted((self.tree / "compatibility").glob("*.rules.json")):
            for row in json.loads(path.read_text(encoding="utf-8")):
                if row["id"] == rule_id:
                    return row
        raise AssertionError(f"{rule_id} not found")

    def test_create_validates(self):
        row = self._create(evidence=[self.evidence_id])
        self.assertEqual(row["origin"], "MANUAL")
        self.assertEqual(row["maturity"], "DETECT_ONLY")
        self.assertEqual(row["rev"], 1)
        stored = self._rule_row()
        self.assertEqual(stored["origin"], "MANUAL")
        self.assertEqual(stored["evidence"], [self.evidence_id])
        doc = h.load_history(self.tree, RULE_ID)
        self.assertEqual(doc["created_by"], "alice")
        self.assertEqual(doc["entries"][0]["action"], "create")
        self.assertEqual(doc["entries"][0]["rule_sha256"], digest_obj(self._rule_row()))
        self.assertEqual([f for f in ops.validate_tree(self.tree) if f.code == "A006"], [])

    def test_create_refuses_fix_enabled(self):
        with self.assertRaises(ops.OpsError):
            self._create(maturity="FIX_ENABLED")
        self.assertFalse(self.tree.joinpath("history", "rules", f"{RULE_ID}.json").exists())

    def test_duplicate_id_rejected(self):
        self._create()
        before = _snapshot(self.tree)
        with self.assertRaises(ops.OpsError) as ctx:
            self._create(author="mallory")
        self.assertIn("duplicate", str(ctx.exception))
        self.assertEqual(_snapshot(self.tree), before)
        self.assertEqual(h.load_history(self.tree, RULE_ID)["created_by"], "alice")

    def test_edit_preserves_creator(self):
        self._create(author="alice")
        ops.edit_rule(self.tree, RULE_ID, {"message": "changed"}, author="bob", at="2026-11-08T11:00:00Z")
        doc = h.load_history(self.tree, RULE_ID)
        self.assertEqual(doc["created_by"], "alice")
        self.assertEqual(doc["created_at"], AT)
        self.assertEqual([e["action"] for e in doc["entries"]], ["create", "edit"])
        self.assertEqual(doc["entries"][1]["actor"], "bob")
        self.assertEqual(self._rule_row()["rev"], 2)
        self.assertEqual(self._rule_row()["message"], "changed")

    def test_edit_cannot_set_fix_enabled(self):
        self._create()
        before = _snapshot(self.tree)
        with self.assertRaises(ops.OpsError):
            ops.edit_rule(self.tree, RULE_ID, {"maturity": "FIX_ENABLED"}, author="bob", at=AT)
        self.assertEqual(_snapshot(self.tree), before)

    def test_edit_cannot_change_origin_or_id(self):
        self._create()
        with self.assertRaises(ops.OpsError):
            ops.edit_rule(self.tree, RULE_ID, {"origin": "BUILTIN"}, author="bob", at=AT)
        with self.assertRaises(ops.OpsError):
            ops.edit_rule(self.tree, RULE_ID, {"id": "17-18.manual.other"}, author="bob", at=AT)

    def test_retire_sets_reason(self):
        self._create()
        with self.assertRaises(ops.OpsError):
            ops.retire_rule(self.tree, RULE_ID, reason="", author="bob", at=AT)
        ops.retire_rule(self.tree, RULE_ID, reason="superseded by a better rule", author="bob", at=AT,
                        superseded_by="17-18.manual.newer")
        row = self._rule_row()
        self.assertEqual(row["maturity"], "RETIRED")
        self.assertEqual(row["retired_reason"], "superseded by a better rule")
        self.assertEqual(h.load_history(self.tree, RULE_ID)["entries"][-1]["action"], "retire")

    def test_disable_enable_roundtrip(self):
        self._create()
        ops.disable_rule(self.tree, RULE_ID, reason="noisy", author="bob", at=AT)
        self.assertEqual(self._rule_row()["maturity"], "DRAFT")
        ops.enable_rule(self.tree, RULE_ID, author="bob", at=AT)
        self.assertEqual(self._rule_row()["maturity"], "DETECT_ONLY")

    def test_link_evidence_requires_known_evidence(self):
        self._create()
        with self.assertRaises(ops.OpsError):
            ops.link_evidence(self.tree, RULE_ID, "EV-999", author="bob", at=AT)
        ops.link_evidence(self.tree, RULE_ID, self.other_evidence, author="bob", at=AT)
        self.assertEqual(self._rule_row()["evidence"], [self.evidence_id, self.other_evidence])
        self.assertEqual(h.load_history(self.tree, RULE_ID)["entries"][-1]["action"], "link_evidence")

    def test_add_test_hashes_fixture(self):
        self._create()
        source = self.base / "positive.xml"
        source.write_bytes(b"<odoo><field name='x'/></odoo>\n")
        ops.add_test(self.tree, RULE_ID, kind="positive", fixture=source, author="bob", at=AT)
        rel = self._rule_row()["tests"]["positive"]
        copied = self.tree / rel
        self.assertTrue(copied.is_file())
        self.assertEqual(copied.read_bytes(), source.read_bytes())
        entry = h.load_history(self.tree, RULE_ID)["entries"][-1]
        self.assertEqual(entry["action"], "add_test")
        self.assertEqual(entry["provenance"]["fixture_sha256"], _sha(source.read_bytes()))
        with self.assertRaises(ops.OpsError):
            ops.add_test(self.tree, RULE_ID, kind="bogus", fixture=source, author="bob", at=AT)

    def test_failed_validation_rolls_back(self):
        before = _snapshot(self.tree)
        with self.assertRaises(ops.OpsError):
            self._create(evidence=["EV-999"])
        self.assertEqual(_snapshot(self.tree), before)
        self.assertFalse((self.tree / "history").exists())

    def test_inspect_and_history_report_head(self):
        self._create(evidence=[self.evidence_id])
        info = ops.inspect_rule(self.tree, RULE_ID)
        self.assertEqual(info["rule"]["id"], RULE_ID)
        self.assertEqual(info["history_head"]["rev"], 1)
        self.assertEqual(info["evidence"][self.evidence_id], load_knowledge(self.tree).evidence[self.evidence_id]
                         .get("status", "MISSING"))
        self.assertEqual(ops.history_rule(self.tree, RULE_ID)["rule_id"], RULE_ID)


class GeneratedOriginTests(unittest.TestCase):
    """TST-011-059 support (feature 011 T059): create_rule accepts origin GENERATED only with a source candidate."""

    CANDIDATE = "CR-0123456789abcdef"
    setUp = AuthoringOpsTests.setUp
    tearDown = AuthoringOpsTests.tearDown

    def _gen(self, **over):
        over.setdefault("evidence", [self.evidence_id])
        return ops.create_rule(self.tree, _row(id="17-18.generated.new-1", **over), evidence=(), author="gen",
                               at=AT, origin="GENERATED", source_candidate=self.CANDIDATE, detectors_verified=True)

    def test_generated_origin_records_provenance(self):
        row = self._gen()
        self.assertEqual(row["origin"], "GENERATED")
        history = h.load_history(self.tree, "17-18.generated.new-1")
        self.assertEqual(history["entries"][0]["provenance"],
                         {"origin": "GENERATED", "source_candidate": self.CANDIDATE})

    def test_generated_requires_verified_detectors_whatever_the_entry_point(self):
        """detectors_verified defaults to False: a direct create_rule call cannot skip template verification."""
        for kwargs in ({}, {"detectors_verified": False}, {"detectors_verified": None}, {"detectors_verified": "true"},
                       {"detectors_verified": 1}):
            with self.assertRaises(ops.OpsError, msg=str(kwargs)) as caught:
                ops.create_rule(self.tree, _row(id="17-18.generated.new-3", evidence=[self.evidence_id]), evidence=(),
                                author="gen", at=AT, origin="GENERATED", source_candidate=self.CANDIDATE, **kwargs)
            self.assertIn("detectors_unverified", str(caught.exception))
        self.assertEqual([], h.load_history_ids(self.tree) if hasattr(h, "load_history_ids") else [])

    def test_manual_rules_do_not_need_the_flag(self):
        row = ops.create_rule(self.tree, _row(id="17-18.manual.new-4", evidence=[self.evidence_id]), evidence=(),
                              author="me", at=AT)
        self.assertEqual("MANUAL", row["origin"])

    def test_generated_requires_source_candidate(self):
        with self.assertRaises(ops.OpsError):
            ops.create_rule(self.tree, _row(id="17-18.generated.new-2", evidence=[self.evidence_id]),
                            evidence=(), author="gen", at=AT, origin="GENERATED")

    def test_origin_must_be_creatable(self):
        for origin in ("BUILTIN", "AI_PROPOSED", "KAP"):
            with self.assertRaises(ops.OpsError):
                ops.create_rule(self.tree, _row(id="17-18.generated.new-3", evidence=[self.evidence_id]),
                                evidence=(), author="gen", at=AT, origin=origin, source_candidate=self.CANDIDATE)

    def test_generated_still_refuses_fix_enabled(self):
        with self.assertRaises(ops.OpsError):
            self._gen(maturity="FIX_ENABLED")

    def test_generated_row_origin_must_match(self):
        with self.assertRaises(ops.OpsError):
            self._gen(origin="MANUAL")


if __name__ == "__main__":
    unittest.main()
