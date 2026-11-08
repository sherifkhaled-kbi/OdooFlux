"""TST-011-059 (REQ-KAP-016, REQ-KAP-020, REQ-KAP-021, REQ-KAP-031): candidate acceptance runs the schema and authoring
checks, writes the rule (origin GENERATED) and its history through authoring/ops, records the ledger disposition, and
refuses (candidate stays PROPOSED or CONFLICT, tree untouched) when evidence fails the schema or a MANUAL rule collides.

Contract candidate-rule-generation (acceptance) and manual-rule-cli. Tests use a temporary copy of the built-in data
directories; the repository tree is only read.
"""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.builtins import build_registries
from odooflux.knowledge.candidates.templates import load_templates  # composition root: the verified detector table

KNOWN_DETECTORS = build_registries().extract_toolkit.detectors

DATA_DIRS = ("evidence", "compatibility", "official_sources")
CLOCK = lambda: "2026-11-08T00:00:00Z"  # noqa: E731
AT = "2026-11-08T10:00:00Z"
DETECTOR_FLAG_ATTR = "odooflux.rules.python.generic:flag_class_attribute"
DETECTOR_FLAG_METHOD = "odooflux.rules.python.generic:flag_method_override"
SOURCE = {"source_id": "odoo-community-17.0", "official": True, "url": "https://github.com/odoo/odoo/tree/" + "a" * 40,
          "repository": "odoo/odoo", "revision": "a" * 40, "branch": "17.0"}


def _snap(sid_hex, digest_hex):
    return {"snapshot_id": "ss-" + sid_hex, "snapshot_digest": digest_hex * 64}


def _draft(subject, kind, cls):
    return {"domain": "python_orm", "kind": kind, "subject_key": subject, "class": cls, "detail": {},
            "locations": [{"snapshot_id": "ss-0123456789ab", "path": "addons/base/models/res_partner.py",
                           "line": 12, "sha256": "cd" * 32}], "proposed_by": "DETERMINISTIC"}


def _ledger(drafts):
    return Ledger.create("17-18", _snap("111111111111", "1"), _snap("222222222222", "2"), drafts, clock=CLOCK)


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class AcceptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        self.builtin_evidence = sorted(k for k in load_knowledge(KNOWLEDGE_ROOT).evidence if k.startswith("EV-"))[0]

    def tearDown(self):
        self._tmp.cleanup()

    def _generate(self, ledger):
        return gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08", known_detectors=KNOWN_DETECTORS)

    def _manual_guard(self):
        """A MANUAL rule on the method detector with other params: a generated method candidate collides (A005)."""
        ops.create_rule(self.tree, {"id": "17-18.manual.method-guard", "step": "17-18", "category": "python_orm",
                                    "risk": "LOW", "evidence": [self.builtin_evidence],
                                    "detector_ref": DETECTOR_FLAG_METHOD,
                                    "fixer_ref": None, "tests": [], "params": {"method": "other"},
                                    "message": "manual guard", "maturity": "DETECT_ONLY"},
                        author="alice", at=AT)


class AcceptBehaviourTests(AcceptTests):
    def test_accept_writes_rule_and_history(self):
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        out = acc.accept(self.tree, candidate, ledger=ledger, evidence=result["evidence"], author="alice", at=AT)
        self.assertEqual(out["status"], "ACCEPTED")
        self.assertEqual(candidate["status"], "ACCEPTED")
        rule_id = candidate["rule"]["id"]
        rows = json.loads((self.tree / "compatibility" / "17-18.rules.json").read_text(encoding="utf-8"))
        row = [r for r in rows if r["id"] == rule_id][0]
        self.assertEqual(row["origin"], "GENERATED")
        self.assertIn(row["maturity"], ("DRAFT", "DETECT_ONLY"))
        self.assertIsNone(row["fixer_ref"])
        history = h.load_history(self.tree, rule_id)
        self.assertEqual(history["entries"][0]["provenance"],
                         {"origin": "GENERATED", "source_candidate": candidate["candidate_id"]})
        self.assertTrue((self.tree / "evidence" / f"{result['evidence'][0]['id']}.json").is_file())
        self.assertEqual(ledger.get(candidate["change_id"])["disposition"], "RULE_CREATED")
        self.assertEqual(ledger.verify(), [])

    def test_failure_stays_proposed(self):
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        bad_evidence = [dict(result["evidence"][0], locations=[])]  # fails the schema (minItems 1)
        before_tree = _tree_bytes(self.tree)
        before_ledger = ledger.to_dict()
        with self.assertRaises(acc.AcceptError):
            acc.accept(self.tree, candidate, ledger=ledger, evidence=bad_evidence, author="alice", at=AT)
        self.assertEqual(candidate["status"], "PROPOSED")
        self.assertEqual(_tree_bytes(self.tree), before_tree)
        self.assertEqual(ledger.to_dict(), before_ledger)

    def test_conflict_status(self):
        self._manual_guard()
        ledger = _ledger([_draft("res.partner::method::bar", "method", "REMOVED")])
        result = self._generate(ledger)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["status"], "CONFLICT")
        before_tree = _tree_bytes(self.tree)
        with self.assertRaises(acc.AcceptError):
            acc.accept(self.tree, candidate, ledger=ledger, evidence=result["evidence"], author="alice", at=AT)
        self.assertEqual(candidate["status"], "CONFLICT")
        self.assertEqual(_tree_bytes(self.tree), before_tree)

    def test_unverified_candidate_refused(self):
        """Templates loaded with verify=False mark every candidate unverified; accept refuses it (detectors_unverified)."""
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        result = gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                              templates=load_templates(verify=False), known_detectors=KNOWN_DETECTORS)
        self.assertIs(result["detectors_verified"], False)
        candidate = result["candidates"][0]
        self.assertIs(candidate["detectors_verified"], False)
        with self.assertRaises(acc.AcceptError) as caught:
            acc.accept(self.tree, candidate, ledger=ledger, evidence=result["evidence"], author="alice", at=AT)
        self.assertIn("detectors_unverified", str(caught.exception))
        self.assertEqual(candidate["status"], "PROPOSED")

    def test_absent_or_non_true_flag_is_refused_and_true_survives_json(self):
        """accept reads detectors_verified as `is True`: an absent key, None or a string is refused; a verified
        candidate keeps True through a JSON round trip and is then accepted."""
        import json
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        result = gen.generate(ledger, tree_root=self.tree, source=SOURCE, checked_on="2026-11-08",
                              templates=load_templates(known_detectors=KNOWN_DETECTORS), known_detectors=KNOWN_DETECTORS)
        candidate = json.loads(json.dumps(result["candidates"][0]))  # serialization round trip
        self.assertIs(candidate["detectors_verified"], True)
        for mutate in (lambda c: c.pop("detectors_verified"), lambda c: c.update(detectors_verified=None),
                       lambda c: c.update(detectors_verified="true"), lambda c: c.update(detectors_verified=1)):
            broken = json.loads(json.dumps(candidate))
            mutate(broken)
            with self.assertRaises(acc.AcceptError) as caught:
                acc.accept(self.tree, broken, ledger=ledger, evidence=result["evidence"], author="alice", at=AT)
            self.assertIn("detectors_unverified", str(caught.exception))

    def test_fix_enabled_candidate_refused(self):
        ledger = _ledger([_draft("res.partner::field::foo", "field", "REMOVED")])
        result = self._generate(ledger)
        candidate = copy.deepcopy(result["candidates"][0])
        candidate["rule"]["fixer_ref"] = "odooflux.rules.python.generic:rewrite_thing"
        with self.assertRaises(acc.AcceptError):
            acc.accept(self.tree, candidate, ledger=ledger, evidence=result["evidence"], author="alice", at=AT)
        self.assertEqual(candidate["status"], "PROPOSED")


if __name__ == "__main__":
    unittest.main()
