"""TST-011-026 (REQ-KAP-031, REQ-KAP-020): generated candidates that collide with MANUAL rules are recorded as CONFLICT,
the manual rule is kept by default, and `resolve` records the decision in the manual rule's history.

Contract manual-rule-cli, section Generated/manual conflicts. Tests use a temporary copy of the built-in data
directories; the repository tree is only read.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.authoring import conflicts as cf
from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge

DATA_DIRS = ("evidence", "compatibility", "official_sources")
MANUAL_ID = "17-18.manual.example-check"
CANDIDATE_ID = "CR-0123456789abcdef"


def _manual(**over):
    row = {
        "id": MANUAL_ID,
        "step": "17-18",
        "category": "xml",
        "risk": "LOW",
        "origin": "MANUAL",
        "maturity": "DETECT_ONLY",
        "evidence": [],
        "detector_ref": "det.field",
        "fixer_ref": None,
        "tests": [],
        "file_kinds": ["xml"],
        "params": {"tag": "field"},
        "rev": 1,
    }
    row.update(over)
    return row


def _candidate(rule_id="17-18.generated.field-1", candidate_id=CANDIDATE_ID, **over):
    rule = {
        "id": rule_id,
        "step": "17-18",
        "category": "xml",
        "risk": "LOW",
        "maturity": "DRAFT",
        "evidence": [],
        "detector_ref": "det.field",
        "fixer_ref": None,
        "tests": [],
        "file_kinds": ["xml"],
        "params": {"tag": "field"},
    }
    rule.update(over)
    return {"candidate_id": candidate_id, "status": "PROPOSED", "origin": "DETERMINISTIC", "rule": rule}


class ConflictDetectionTests(unittest.TestCase):
    def test_manual_wins_by_default(self):
        manual = [_manual()]
        before = copy.deepcopy(manual)
        candidates = [_candidate(), _candidate(rule_id="17-18.generated.other", detector_ref="det.unrelated")]
        plan = cf.plan_build(manual, candidates)
        statuses = {c["rule"]["id"]: c["status"] for c in plan["candidates"]}
        self.assertEqual(statuses["17-18.generated.field-1"], "CONFLICT")
        self.assertEqual(statuses["17-18.generated.other"], "PROPOSED")
        self.assertEqual(manual, before)  # the manual rule is never modified by a build
        self.assertEqual(plan["manual_kept"], [MANUAL_ID])
        self.assertTrue(all(c["keep"] == "manual" and c["resolved"] is False for c in plan["conflicts"]))

    def test_conflict_listed(self):
        manual = [_manual()]
        plan = cf.plan_build(manual, [_candidate(), _candidate(rule_id=MANUAL_ID, candidate_id="CR-1111111111111111")])
        kinds = sorted((c["candidate_id"], c["kind"], c["with"]) for c in plan["conflicts"])
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / "build"
            cf.write_conflicts(build, plan["conflicts"])
            doc = json.loads((build / "conflicts.json").read_text(encoding="utf-8"))
        listed = sorted((c["candidate_id"], c["kind"], c["with"]) for c in doc["conflicts"])
        self.assertEqual(listed, kinds)
        self.assertIn((CANDIDATE_ID, "A002", MANUAL_ID), listed)
        self.assertIn(("CR-1111111111111111", "A001", MANUAL_ID), listed)

    def test_detection_codes(self):
        manual = [_manual()]
        same_scope_other_params = _candidate(params={"tag": "other"}, file_kinds=["xml", "py"])
        self.assertEqual([c["kind"] for c in cf.detect(manual, same_scope_other_params["rule"])], ["A005"])
        disjoint = _candidate(params={"tag": "other"}, file_kinds=["py"])
        self.assertEqual(cf.detect(manual, disjoint["rule"]), [])

    def test_retired_manual_rule_does_not_conflict(self):
        manual = [_manual(maturity="RETIRED", retired_reason="old")]
        self.assertEqual(cf.detect(manual, _candidate()["rule"]), [])

    def test_generated_rules_never_conflict_with_generated(self):
        generated = _manual(origin="GENERATED")
        self.assertEqual(cf.detect([generated], _candidate()["rule"]), [])


class ConflictResolutionTests(unittest.TestCase):
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
        self.evidence_id = sorted(k for k in kb.evidence if k.startswith("EV-"))[0]
        self.build = self.base / "build"
        ops.create_rule(self.tree, {
            "id": MANUAL_ID, "step": "17-18", "category": "xml", "risk": "LOW", "evidence": [self.evidence_id],
            "detector_ref": "det.field", "fixer_ref": None, "tests": [], "file_kinds": ["xml"],
            "params": {"tag": "field"}, "message": "manual"}, author="alice", at="2026-11-08T10:00:00Z")
        plan = cf.plan_build(self._manual_rows(), [_candidate()])
        cf.write_conflicts(self.build, plan["conflicts"])

    def tearDown(self):
        self._tmp.cleanup()

    def _manual_rows(self):
        rows = json.loads((self.tree / "compatibility" / "17-18.rules.json").read_text(encoding="utf-8"))
        return [r for r in rows if r.get("origin") == "MANUAL"]

    def test_resolution_recorded(self):
        cf.resolve(self.build, tree=self.tree, candidate_id=CANDIDATE_ID, keep="candidate",
                   author="bob", at="2026-11-08T12:00:00Z")
        doc = json.loads((self.build / "conflicts.json").read_text(encoding="utf-8"))
        entry = [c for c in doc["conflicts"] if c["candidate_id"] == CANDIDATE_ID][0]
        self.assertTrue(entry["resolved"])
        self.assertEqual(entry["keep"], "candidate")
        self.assertEqual(entry["resolved_by"], "bob")
        history = h.load_history(self.tree, MANUAL_ID)
        last = history["entries"][-1]
        self.assertEqual(last["action"], "edit")
        self.assertEqual(last["provenance"]["conflict_resolution"], {"candidate_id": CANDIDATE_ID, "keep": "candidate"})
        self.assertEqual(history["created_by"], "alice")
        row = self._manual_rows()[0]
        self.assertEqual(row["rev"], last["rev"])

    def test_resolve_rejects_unknown_choice_and_unknown_candidate(self):
        with self.assertRaises(cf.ConflictError):
            cf.resolve(self.build, tree=self.tree, candidate_id=CANDIDATE_ID, keep="both", author="bob",
                       at="2026-11-08T12:00:00Z")
        with self.assertRaises(cf.ConflictError):
            cf.resolve(self.build, tree=self.tree, candidate_id="CR-ffffffffffffffff", keep="manual",
                       author="bob", at="2026-11-08T12:00:00Z")
        self.assertEqual(h.load_history(self.tree, MANUAL_ID)["entries"][-1]["action"], "create")

    def test_resolve_twice_refused(self):
        cf.resolve(self.build, tree=self.tree, candidate_id=CANDIDATE_ID, keep="manual", author="bob",
                   at="2026-11-08T12:00:00Z")
        with self.assertRaises(cf.ConflictError):
            cf.resolve(self.build, tree=self.tree, candidate_id=CANDIDATE_ID, keep="candidate", author="bob",
                       at="2026-11-08T13:00:00Z")


if __name__ == "__main__":
    unittest.main()
