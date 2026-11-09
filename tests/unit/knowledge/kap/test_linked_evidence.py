"""Feature 012 Wave 3c: evidence of a change that links to an existing rule.

- A link to a rule GENERATED in this build ships: the evidence row goes into the tree evidence store with a fresh id and is
  cited by the rule through ops.link_evidence (one history revision; maturity, detector and params untouched). Identical
  linked content reuses its id: no second row, no second citation.
- A link to a MANUAL, built-in or inherited rule is marked not generated; the pipeline withholds it (tested in the
  integration suite). Nothing here modifies such a rule.
- A rule that cites evidence from two sources passes gate 1 when one row is officially supported and non-AI, and the other
  row is valid (not UNVERIFIED or CONFLICTING).
- A Community rule extended with Enterprise evidence makes the release refused by package/confidentiality.assess, and its
  Community evidence stays byte-identical.

Fixtures are built in temporary directories from a copy of the built-in data directories; the repository is only read.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_registries  # composition root: the verified detector table
from odooflux.knowledge.acquisition.sources import load_allow_list
from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.package.confidentiality import assess
from odooflux.knowledge.release import safety

KNOWN_DETECTORS = build_registries().extract_toolkit.detectors
DATA_DIRS = ("evidence", "compatibility", "official_sources")
CLOCK = lambda: "2026-11-08T00:00:00Z"  # noqa: E731
AT = "2026-11-08T10:00:00Z"
STEP = "16-17"
SUBJECT = "sale.demo.order.compute_total"
DETECTOR_METHOD = "odooflux.rules.python.generic:flag_method_override"
MANUAL_ID = "16-17.python_orm.manual-total"
COM_ID, ENT_ID = "odoo-community-17.0", "odoo-enterprise-17.0"
COM = {"source_id": COM_ID, "official": True, "url": "https://github.com/odoo/odoo/tree/" + "a" * 40,
       "repository": "odoo/odoo", "revision": "a" * 40, "branch": "17.0"}
ENT = {"source_id": ENT_ID, "official": True, "url": "https://github.com/odoo/enterprise/tree/" + "b" * 40,
       "repository": "odoo/enterprise", "revision": "b" * 40, "branch": "17.0"}


def _snap(sid_hex, digest_hex):
    return {"snapshot_id": "ss-" + sid_hex, "snapshot_digest": digest_hex * 64}


def _draft(path):
    return {"domain": "python_orm", "kind": "method", "subject_key": SUBJECT, "class": "SIGNATURE_CHANGED",
            "detail": {}, "proposed_by": "DETERMINISTIC",
            "locations": [{"snapshot_id": "ss-0123456789ab", "path": path, "line": 12, "sha256": "cd" * 32}]}


def _ledger(path):
    return Ledger.create(STEP, _snap("111111111111", "1"), _snap("222222222222", "2"), [_draft(path)], clock=CLOCK)


def _generate(ledger, tree, source):
    return gen.generate(ledger, tree_root=tree, source=source, checked_on="2026-11-08", known_detectors=KNOWN_DETECTORS)


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _rule_row(tree, rule_id):
    for path in sorted((tree / "compatibility").glob("*.rules.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row.get("id") == rule_id:
                return row
    raise AssertionError(f"no rule {rule_id}")


class TreeFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.tree = self.base / "tree"
        self.tree.mkdir()
        for name in DATA_DIRS:
            shutil.copytree(KNOWLEDGE_ROOT / name, self.tree / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(KNOWLEDGE_ROOT / "gaps.json", self.tree / "gaps.json")
        self.builtin_evidence = sorted(k for k in load_knowledge(KNOWLEDGE_ROOT).evidence if k.startswith("EV-"))[0]
        # The pipeline's evidence step catalogues every verified revision; the evidence checks need the same entries.
        catalogue = self.tree / "official_sources" / "revisions.json"
        revisions = json.loads(catalogue.read_text(encoding="utf-8"))
        for spec in (COM, ENT):
            revisions.append({"repository": spec["repository"], "branch": "17.0", "revision": spec["revision"],
                              "committed": "2026-11-01", "pinned_on": "2026-11-08", "tags": []})
        catalogue.write_text(json.dumps(revisions, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _manual_rule(self, rule_id=MANUAL_ID, method="compute_total"):
        ops.create_rule(self.tree, {"id": rule_id, "step": STEP, "category": "python_orm", "risk": "LOW",
                                    "evidence": [self.builtin_evidence], "detector_ref": DETECTOR_METHOD,
                                    "fixer_ref": None, "tests": [], "params": {"method": method},
                                    "message": "manual guard", "maturity": "DETECT_ONLY"},
                        author="alice", at=AT)


class SharedRuleFixture(TreeFixture):
    """`FIRST` generates and accepts a rule; the `SECOND` change of the same identifier links to it (its evidence is the
    row under test, `self.record`). Default: an Enterprise rule linked by Community."""
    FIRST, SECOND = ENT, COM

    def setUp(self):
        super().setUp()
        first = _ledger("addons/sale_demo/models/order.py")
        result = _generate(first, self.tree, self.FIRST)
        candidate = result["candidates"][0]
        acc.accept(self.tree, candidate, ledger=first, evidence=result["evidence"], author="alice", at=AT)
        self.rule_id = candidate["rule"]["id"]
        self.first_evidence_id = candidate["rule"]["evidence"][0]
        self.second = _generate(_ledger("addons/sale_demo/models/order.py"), self.tree, self.SECOND)
        self.link = self.second["linked"][0]
        self.record = self.second["evidence"][0]


class GeneratorLinkTests(SharedRuleFixture):
    def test_link_to_a_generated_rule_is_marked_generated_and_keeps_its_source(self):
        self.assertEqual(self.link["rule_ids"], [self.rule_id])
        self.assertIs(self.link["generated"], True)
        self.assertEqual(self.link["origin"], "GENERATED")
        self.assertEqual(self.record["source_id"], COM_ID)
        self.assertEqual(self.record["revision"], "a" * 40)
        self.assertEqual(self.record["repository"], "odoo/odoo")
        self.assertNotEqual(self.record["id"], self.first_evidence_id, "a fresh id, never the first row's")
        self.assertFalse((self.tree / "evidence" / f"{self.record['id']}.json").exists(), "generation writes nothing")

    def test_held_identical_linked_content_reuses_its_id(self):
        acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        again = _generate(_ledger("addons/sale_demo/models/order.py"), self.tree, self.SECOND)
        self.assertEqual(again["linked"][0]["evidence_ids"], [self.record["id"]])
        self.assertEqual(again["evidence"][0], self.record, "the same record, no new id")



class ManualLinkTests(TreeFixture):
    def test_link_to_a_manual_rule_is_marked_not_generated_and_the_rule_is_not_changed(self):
        self._manual_rule()
        before = _rule_row(self.tree, MANUAL_ID)
        result = _generate(_ledger("addons/sale_demo/models/order.py"), self.tree, COM)
        link = result["linked"][0]
        self.assertEqual(link["rule_ids"], [MANUAL_ID])
        self.assertIs(link["generated"], False)
        self.assertEqual(link["origin"], "MANUAL")
        self.assertEqual(_rule_row(self.tree, MANUAL_ID), before)


class ShipLinkedEvidenceTests(SharedRuleFixture):
    def test_ship_writes_the_row_and_cites_it_without_touching_the_rule_fields(self):
        before = _rule_row(self.tree, self.rule_id)
        ev_id = acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        self.assertEqual(ev_id, self.record["id"])
        self.assertEqual(json.loads((self.tree / "evidence" / f"{ev_id}.json").read_text(encoding="utf-8")),
                         self.record)
        after = _rule_row(self.tree, self.rule_id)
        self.assertEqual(after["evidence"], [self.first_evidence_id, ev_id])
        for field in ("maturity", "detector_ref", "params", "origin", "step", "fixer_ref", "risk"):
            self.assertEqual(after[field], before[field], field)
        entry = h.load_history(self.tree, self.rule_id)["entries"][-1]
        self.assertEqual((entry["action"], entry["actor"], entry["provenance"]),
                         ("link_evidence", "bob", {"evidence": ev_id}))
        self.assertIn(ev_id, load_knowledge(self.tree).evidence)
        self.assertEqual([f for f in ops.validate_tree(self.tree) if f.severity == "ERROR"], [])

    def test_ship_is_idempotent_no_second_row_and_no_second_citation(self):
        acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        once = _tree_bytes(self.tree)
        history_once = h.load_history(self.tree, self.rule_id)["entries"]
        again = acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        self.assertEqual(again, self.record["id"])
        self.assertEqual(_tree_bytes(self.tree), once)
        self.assertEqual(h.load_history(self.tree, self.rule_id)["entries"], history_once)

    def test_ship_refuses_a_rule_that_is_not_generated_and_writes_nothing(self):
        self._manual_rule("16-17.python_orm.manual-other", method="manual_only")
        before = _tree_bytes(self.tree)
        with self.assertRaises(acc.AcceptError) as caught:
            acc.ship_linked_evidence(self.tree, "16-17.python_orm.manual-other", self.record, author="bob", at=AT)
        self.assertIn("not GENERATED", str(caught.exception))
        self.assertEqual(_tree_bytes(self.tree), before)

    def test_ship_refuses_an_id_held_with_different_content(self):
        held = dict(self.record, description="a different claim")
        (self.tree / "evidence" / f"{self.record['id']}.json").write_text(json.dumps(held), encoding="utf-8")
        before = _tree_bytes(self.tree)
        with self.assertRaises(acc.AcceptError):
            acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        self.assertEqual(_tree_bytes(self.tree), before)

    def test_ship_refuses_a_record_that_fails_the_schema(self):
        bad = dict(self.record, locations=[])  # the schema needs at least one location
        before = _tree_bytes(self.tree)
        with self.assertRaises(acc.AcceptError):
            acc.ship_linked_evidence(self.tree, self.rule_id, bad, author="bob", at=AT)
        self.assertEqual(_tree_bytes(self.tree), before)

    def test_failed_revision_rolls_back_the_evidence_file(self):
        before = _tree_bytes(self.tree)
        with mock.patch.object(h, "append_entry", side_effect=h.HistoryError("simulated write failure")):
            with self.assertRaises(acc.AcceptError):
                acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        self.assertEqual(_tree_bytes(self.tree), before, "neither the row nor the rule file may be left behind")

    def test_link_evidence_record_must_carry_the_id(self):
        with self.assertRaises(ops.OpsError):
            ops.link_evidence(self.tree, self.rule_id, "EV-999", author="bob", at=AT, record=self.record)


class GateOneTwoSourceTests(unittest.TestCase):
    """A rule citing a Community and an Enterprise row, checked by the release gate 1 (safety._gate1) with provenance."""

    def setUp(self):
        self.allow = load_allow_list()
        self.provenance = {
            COM_ID: {"source_id": COM_ID, "official": True, "kind": "GIT_COMMUNITY", "status": "VERIFIED",
                     "url": COM["url"][:len("https://github.com/odoo/odoo/")], "revision": "a" * 40,
                     "snapshot_digest": "sha256:" + "1" * 64},
        }
        self.index = safety.load_provenance_index(None, provenance=list(self.provenance.values()))

    def _record(self, eid, source_id, *, official, status="DOCUMENTED_NOT_TESTED", origin="KAP_DETERMINISTIC"):
        return {"id": eid, "source_id": source_id, "official": official, "origin": origin, "status": status,
                "locations": [{"path": "addons/sale_demo/models/order.py", "content_sha256": "cd" * 32}]}

    def _gate(self, records, index=None):
        kb_evidence = {eid: rec for eid, rec in records}
        return safety._gate1("16-17.python_orm.shared", [eid for eid, _ in records], records, kb_evidence,
                             self.index if index is None else index, self.allow)

    def test_official_community_row_and_valid_enterprise_row_pass(self):
        records = [("EV-010", self._record("EV-010", COM_ID, official=True)),
                   ("EV-011", self._record("EV-011", ENT_ID, official=False))]
        self.assertEqual(self._gate(records), [])

    def test_order_does_not_matter(self):
        records = [("EV-011", self._record("EV-011", ENT_ID, official=False)),
                   ("EV-010", self._record("EV-010", COM_ID, official=True))]
        self.assertEqual(self._gate(records), [])

    def test_the_other_row_must_be_valid_not_blocking(self):
        records = [("EV-010", self._record("EV-010", COM_ID, official=True)),
                   ("EV-011", self._record("EV-011", ENT_ID, official=False, status="UNVERIFIED"))]
        codes = {finding["code"] for finding in self._gate(records)}
        self.assertEqual(codes, {"evidence-unverified-or-conflicting"})

    def test_no_officially_supported_row_fails(self):
        records = [("EV-010", self._record("EV-010", COM_ID, official=False)),
                   ("EV-011", self._record("EV-011", ENT_ID, official=False))]
        self.assertEqual({finding["code"] for finding in self._gate(records)}, {"no-official-evidence"})

    def test_an_ai_origin_row_never_supports_the_rule(self):
        records = [("EV-010", self._record("EV-010", COM_ID, official=True, origin="AI_PROPOSED")),
                   ("EV-011", self._record("EV-011", ENT_ID, official=False))]
        self.assertIn("no-official-evidence", {finding["code"] for finding in self._gate(records)})

    def test_an_enterprise_official_claim_without_provenance_is_unsupported(self):
        records = [("EV-010", self._record("EV-010", ENT_ID, official=True)),
                   ("EV-011", self._record("EV-011", COM_ID, official=False))]
        codes = {finding["code"] for finding in self._gate(records, index=None)}
        self.assertIn("official-claim-unsupported", codes)
        self.assertIn("no-official-evidence", codes)


class ConfidentialityOfExtendedRuleTests(SharedRuleFixture):
    """A Community-origin rule extended with Enterprise evidence: the release is refused, whatever its flag says, and the
    Community evidence is intact."""
    FIRST, SECOND = COM, ENT

    def _release(self, flag, *, extend):
        if extend:
            acc.ship_linked_evidence(self.tree, self.rule_id, self.record, author="bob", at=AT)
        release = self.base / f"release-{flag}-{extend}"
        shutil.copytree(self.tree / "evidence", release / "knowledge" / "evidence")
        shutil.copytree(self.tree / "compatibility", release / "knowledge" / "compatibility")
        sources = [{"source_id": COM_ID, "kind": "GIT_COMMUNITY", "confidentiality": "public"}]
        (release / "release.json").write_text(json.dumps({"confidentiality": flag, "sources": sources}),
                                              encoding="utf-8")
        return release

    def test_extended_rule_refuses_export_even_when_flagged_public(self):
        release = self._release("public", extend=True)
        reasons = assess(release)
        self.assertTrue(reasons, "an Enterprise reference must refuse the release")
        self.assertTrue(any("reference an Enterprise source" in reason for reason in reasons), reasons)

    def test_extended_rule_is_internal_when_flagged_internal(self):
        reasons = assess(self._release("internal", extend=True))
        self.assertIn("release is internal", reasons)

    def test_community_only_release_is_public_and_its_evidence_is_intact(self):
        before = (self.tree / "evidence" / f"{self.first_evidence_id}.json").read_bytes()
        self.assertEqual(assess(self._release("public", extend=False)), [])
        release = self._release("public", extend=True)
        self.assertEqual((release / "knowledge" / "evidence" / f"{self.first_evidence_id}.json").read_bytes(), before)
        community_rows = [json.loads(p.read_text(encoding="utf-8"))
                          for p in (release / "knowledge" / "evidence").glob("EV-*.json")]
        self.assertTrue(any(row.get("source_id") == COM_ID for row in community_rows), "Community evidence must stay")


if __name__ == "__main__":
    unittest.main()
