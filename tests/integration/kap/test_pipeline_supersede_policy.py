"""Feature 012 Wave 3c (owner decision A): the recorded semantic supersede policy in a real build, offline.

Release 1 is built from the synthetic 16.0 -> 17.0 repository. Re-pinning its 17.0 target to a new commit with the same tree
rotates the snapshot digests, so the generated candidate rules of the 16-17 pair get new ids (their change ids change).
Without a policy the build stops with DESTRUCTIVE_NEEDS_SUPERSEDE. With `semantic_supersede_policy()` the same removals are
approved (equal semantics under new ids), the release installs with no manual supersede, and the audit trail names the
approved mapping. A removal with no equivalent still stops even with the policy. Sockets are patched for the whole module.
"""

import copy
import json
import re
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_registries
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.sources import load_allow_list
from odooflux.knowledge.extract import driver
from odooflux.knowledge.release.manifest import META_FIELDS, write_release_manifest
from odooflux.knowledge.release.model import builtin_handle
from odooflux.knowledge.release.store import list_installed
from odooflux.knowledge.update.capability import POLICY_NAME, semantic_supersede_policy
from tests.fixtures.kap import make_synth_repo as synth
from tests.integration.kap import test_pipeline_unified as tu
from tests.unit.knowledge.kap import test_certified_fix_trust as ctf

COM16, COM17 = tu.COM16, tu.COM17
REMOVED_PATTERN = re.compile(r"removed without approval: (.*)$")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rule_rows(release: Path) -> dict:
    return {row["id"]: row for path in sorted((release / "knowledge" / "compatibility").glob("*.rules.json"))
            for row in _read(path)}


class SupersedePolicyBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls._net = [mock.patch.object(socket, "socket", side_effect=AssertionError("network is disabled")),
                    mock.patch.object(socket, "create_connection", side_effect=AssertionError("network is disabled"))]
        for patch in cls._net:
            patch.start()
        cls.registries = build_registries()

    @classmethod
    def tearDownClass(cls):
        for patch in cls._net:
            patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.dir = self.base / self.id().rsplit(".", 1)[-1]
        self.dir.mkdir()
        self.community = synth.build_synth_repo(self.dir / "community")

    def _plan(self, label, com17, *, parent=None, supersede=(), policy=None):
        toolkit = self.registries.extract_toolkit
        registry = full_registry()

        def extract(from_snap, to_snap, step, store):
            result = driver.extract_pair(from_snap, to_snap, None, registry, store=store, step=step, toolkit=toolkit)
            return result.drafts, result.accounting

        community = {"kind": "GIT_COMMUNITY", "official": False, "url": "local:" + self.community.path,
                     "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3"}
        return pl.BuildPlan(
            label=label,
            specs=[tu._spec(COM16, community, "16.0", self.community.from_sha),
                   tu._spec(COM17, community, "17.0", com17)],
            pairs=[{"step": "16-17", "from": COM16, "to": COM17}],
            base_tree=builtin_handle().root,
            adapters={"GIT_COMMUNITY": GitLocalAdapter("GIT_COMMUNITY")},
            parent_dir=parent, supersede=tuple(supersede), supersede_policy=policy,
            extract=extract, known_detectors=toolkit.detectors, created_at=tu.CREATED, checked_on="2026-11-08",
            author="supersede-policy", tool_version="0.2.0", allow_list=load_allow_list(),
            source_meta={COM16: {"repository": "odoo/odoo"}, COM17: {"repository": "odoo/odoo"}})

    def _first_release(self, home):
        result = pl.run_build(home, self._plan("one", self.community.to_sha))
        self.assertEqual(result.outcome, "OK", result.message)
        return home / "releases" / result.release_id

    def _removed_without_approval(self, result) -> set:
        self.assertEqual((result.outcome, result.code), ("STOPPED", "DESTRUCTIVE_NEEDS_SUPERSEDE"), result.message)
        return set(REMOVED_PATTERN.search(result.message).group(1).split(", "))

    def _installed_actions(self, home) -> list:
        """The release ids named by the audit's release_installed entries, in order."""
        entries = [json.loads(line) for line in (home / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        return [e["target"] for e in entries if e.get("action") == "release_installed"]

    def _audit_release_installed(self, home, release_id) -> dict:
        entries = [json.loads(line) for line in (home / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        matches = [e for e in entries if e.get("action") == "release_installed" and e.get("target") == release_id]
        self.assertEqual(len(matches), 1)
        return matches[0]["details"]

    def test_rotated_generated_rules_install_with_the_policy_and_the_audit_names_them(self):
        home = self.dir / "kb"
        first = self._first_release(home)
        new_17 = tu._repin_community(self.community.path, self.community.from_sha)

        removed = self._removed_without_approval(pl.run_build(home, self._plan(
            "two-plain", new_17, parent=first)))
        self.assertTrue(removed)
        self.assertTrue(all(rid.startswith("16-17.python_orm.cand-") for rid in removed), removed)

        result = pl.run_build(home, self._plan("two-policy", new_17, parent=first,
                                               policy=semantic_supersede_policy()))
        self.assertEqual(result.outcome, "OK", result.message)
        installed = result.release_id
        self.assertIn(installed, [r.release_id for r in list_installed(home)])
        self.assertNotEqual(result.completeness, "FAILED")

        details = self._audit_release_installed(home, installed)
        self.assertEqual(details["supersede_policy"], POLICY_NAME)
        self.assertEqual(set(details["approved"]), removed)
        self.assertTrue(all(reason.startswith("semantic replacement by 16-17.python_orm.cand-")
                            for reason in details["approved"].values()), details["approved"])

        step = _read(home / "staging" / "two-policy" / "steps" / "12-build-package.json")
        self.assertEqual(set(step["output"]["approved"]), removed)
        self.assertEqual(set(step["output"]["supersede"]), removed)
        self.assertEqual(set(step["output"]["destructive"]), removed)

        release = home / "releases" / installed
        rows = _rule_rows(release)
        for rid in removed:
            self.assertNotIn(rid, rows)
        replacements = {reason.rsplit(" ", 1)[1] for reason in details["approved"].values()}
        self.assertTrue(replacements <= set(rows))

    def test_the_same_rotation_without_the_policy_stops_and_installs_nothing(self):
        home = self.dir / "kb"
        first = self._first_release(home)
        new_17 = tu._repin_community(self.community.path, self.community.from_sha)
        before = [r.release_id for r in list_installed(home)]
        result = pl.run_build(home, self._plan("two-plain", new_17, parent=first))
        removed = self._removed_without_approval(result)
        self.assertTrue(removed)
        self.assertEqual([r.release_id for r in list_installed(home)], before)
        self.assertEqual(self._installed_actions(home), [first.name])

    def test_a_removal_with_no_equivalent_still_stops_with_the_policy(self):
        home = self.dir / "kb"
        first = self._first_release(home)
        new_17 = tu._repin_community(self.community.path, self.community.from_sha)
        # A parent that also carries a generated rule the new release does not reproduce: no equivalent exists.
        parent = self._parent_with_extra_generated_rule(home, first)
        result = pl.run_build(home, self._plan("two-orphan", new_17, parent=parent,
                                               policy=semantic_supersede_policy()))
        removed = self._removed_without_approval(result)
        self.assertEqual(removed, {"16-17.python_orm.cand-ffffffff"})
        self.assertEqual([r.release_id for r in list_installed(home)], [first.name])
        self.assertEqual(self._installed_actions(home), [first.name])

    def test_plan_fingerprint_names_the_policy_only_when_one_is_set(self):
        plain = self._plan("fp", self.community.to_sha)
        with_policy = self._plan("fp", self.community.to_sha, policy=semantic_supersede_policy())
        self.assertEqual(pl.plan_fingerprint(plain), pl.plan_fingerprint(self._plan("fp", self.community.to_sha)))
        self.assertNotEqual(pl.plan_fingerprint(plain), pl.plan_fingerprint(with_policy))

    def _parent_with_extra_generated_rule(self, home, first: Path) -> Path:
        parent = self.dir / "parent-with-orphan"
        shutil.copytree(first, parent)
        rules_path = parent / "knowledge" / "compatibility" / "16-17.rules.json"
        rows = _read(rules_path)
        orphan = copy.deepcopy(next(r for r in rows if r["id"].startswith("16-17.python_orm.cand-")))
        orphan["id"] = "16-17.python_orm.cand-ffffffff"
        orphan["params"] = {"subject": "sale.demo.order.orphan_with_no_equivalent"}
        rows.append(orphan)
        rows.sort(key=lambda row: row["id"])
        rules_path.write_text(json.dumps(rows) + "\n", encoding="utf-8")
        meta = {key: _read(first / "release.json")[key] for key in sorted(META_FIELDS)}
        write_release_manifest(parent, meta)
        return parent



class BuildGateCertificationTests(ctf.ComposedTestCase):
    """The build gate (step 9, `_fix_trust_findings`) uses the loader's trust predicate: a certified row with an invalid
    record fails it, and a row without a record gets exactly the gate 1 to 5 findings of `fix_gate_findings`."""

    def test_valid_certified_row_passes_the_build_gate(self):
        evidence = [ctf.make_evidence()]
        tree = ctf.write_tree(self.base / "valid", [ctf.make_row()], evidence)
        ctf.store_record(tree, ctf.RULE_ID, ctf.certify(ctf.make_row(), evidence))
        self.assertEqual(pl._fix_trust_findings(tree), [])

    def test_forged_certified_row_fails_the_build_gate(self):
        evidence = [ctf.make_evidence()]
        record = ctf.certify(ctf.make_row(), evidence)
        record["outputs"]["positive_output_digest"] = "0" * 64
        tree = ctf.write_tree(self.base / "forged", [ctf.make_row()], evidence)
        ctf.store_record(tree, ctf.RULE_ID, record)
        findings = pl._fix_trust_findings(tree)
        self.assertEqual({f["rule_id"] for f in findings}, {ctf.RULE_ID})
        self.assertIn("cert-verify-failed", {f["code"] for f in findings})

    def test_row_without_a_record_gets_the_same_findings_as_before(self):
        from odooflux.knowledge.release.safety import fix_gate_findings
        tree = ctf.write_tree(self.base / "norecord", [ctf.make_row(), ctf.make_row(
            "16-17.python.synthetic-other", evidence=["EV-901"],
            params={"callee": "api.b_old_call", "replacement": "api.b_new_call"})],
            [ctf.make_evidence(), ctf.make_evidence("16-17.python.synthetic-other", "EV-901")], provenance=None)
        self.assertFalse((tree / "certifications").exists())
        self.assertEqual(pl._fix_trust_findings(tree), fix_gate_findings(tree))
        self.assertTrue(pl._fix_trust_findings(tree))


if __name__ == "__main__":
    unittest.main()
