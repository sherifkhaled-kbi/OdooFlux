"""Feature 012 Wave 3b (plan addendum C1, C2): one release that holds Community and Enterprise sources, built offline.

Two synthetic local clones, both 16.0 -> 17.0: a GIT_COMMUNITY clone (the synth fixture) and a GIT_ENTERPRISE clone with
a simulated official origin (`https://github.com/odoo/enterprise.git`, as test_enterprise_provenance.py does; nothing is
fetched). Both families use the same step "16-17" with distinct pair keys. The enterprise pair is listed first, because
evidence ids are allocated in pair order. The enterprise tree keeps the Community model, field and method identifiers; only
its addon directory is renamed (two modules with one name are an inventory conflict, a separate case). A change both
sources share links to the rule the Enterprise pair generated, and its Community evidence ships with that rule.

Covered: a unified build installs with `confidentiality internal`, provenance verifies, ledgers are keyed distinctly,
and the module inventory is emitted only when enabled. A second release carries the Enterprise sources from their
retained snapshots while the Community source is re-pinned: the shared rule's Community citation is replaced and nothing is
removed, so the release installs; the Enterprise rows are byte-identical to the first release. A tampered retained snapshot stops the build and leaves the installed release
untouched. A duplicated step without keys is refused. Sockets are patched to fail for the whole module.
"""

import json
import shutil
import stat
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_registries
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.adapters.retained import RetainedSnapshotAdapter
from odooflux.knowledge.acquisition.sources import load_allow_list
from odooflux.knowledge.extract import driver
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.manifest import verify_release_tree
from odooflux.knowledge.release.model import builtin_handle
from odooflux.knowledge.release.provenance import SNAPSHOT_DIRNAME, verify_provenance
from odooflux.knowledge.release.store import list_installed
from odooflux.knowledge.update import inventory
from tests.fixtures.kap import make_synth_repo as synth

CREATED = "2026-11-08T10:00:00Z"
COM16, COM17 = "odoo-community-16.0", "odoo-community-17.0"
ENT16, ENT17 = "odoo-enterprise-16.0", "odoo-enterprise-17.0"
ENT_IDS = (ENT16, ENT17)
ENT_ORIGIN = "https://github.com/odoo/enterprise"
ENT_MODULE = "sale_ent"
LICENCE_ID = "ENT-LIC-0001"
def _enterprise_tree(tree: dict) -> dict:
    """The synthetic tree with only the addon directory renamed. Its model, field and method identifiers are the
    Community ones, so a shared change links across sources (see the module docstring)."""
    def rename(text):
        return text.replace("sale_demo", ENT_MODULE)
    return {rename(path): rename(text) for path, text in tree.items()}


def _git_commit(git_dir, env, tree_sha, message, parent=None):
    args = ["commit-tree", tree_sha, "-m", message] + (["-p", parent] if parent else [])
    return synth._run(args, env, git_dir)


def _enterprise_clone(dest: Path) -> dict:
    """A two-commit clone of the renamed synthetic tree with the simulated enterprise origin. Returns {version: sha}."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="kap-unified-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        synth._run(["remote", "add", "origin", ENT_ORIGIN + ".git"], init_env, git_dir)
        parent, shas = None, {}
        for version, tree in (("16.0", synth._TREE_16), ("17.0", synth._TREE_17)):
            env = synth._git_env(home, template, synth._DATES[version])
            tree_sha = synth._write_tree(git_dir, env, _enterprise_tree(tree))
            sha = _git_commit(git_dir, env, tree_sha, synth._MESSAGES[version], parent)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return shas


def _repin_community(repo: str, from_sha: str) -> str:
    """A new 17.0 commit with the same tree and a new message: the same content under a changed revision."""
    scratch = Path(tempfile.mkdtemp(prefix="kap-repin-"))
    try:
        env = synth._git_env(scratch, scratch, "1720000000 +0000")
        git_dir = Path(repo) / ".git"
        tree = synth._run(["rev-parse", "17.0^{tree}"], env, git_dir)
        sha = _git_commit(git_dir, env, tree, "Synthetic 17.0 target (re-pinned, same tree)", from_sha)
        synth._run(["update-ref", "refs/heads/17.0", sha], env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return sha


def _spec(sid, common, branch, revision):
    spec = {"source_id": sid, "branch": branch, "revision": revision, "required": True, "status": "DECLARED",
            "retrieved_at": None, "checksum": None, "failure_reason": None,
            "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []}}
    spec.update(common)
    return spec


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _enterprise_rows(release: Path) -> dict:
    """The Enterprise-only content of a release: provenance entries, their snapshot manifests, the evidence whose source
    is Enterprise, and the rules whose every evidence id is one of that evidence."""
    knowledge = release / "knowledge"
    provenance = [e for e in _read(release / "provenance" / "sources.json") if e["source_id"] in ENT_IDS]
    snapshots = {e["snapshot_id"]: (release / SNAPSHOT_DIRNAME / f"{e['snapshot_id']}.json").read_bytes()
                 for e in provenance}
    evidence = {}
    for path in sorted((knowledge / "evidence").glob("EV-*.json")):
        record = _read(path)
        if record.get("source_id") in ENT_IDS:
            evidence[record["id"]] = record
    rules = {}
    for path in sorted((knowledge / "compatibility").glob("*.rules.json")):
        for rule in _read(path):
            cited = rule.get("evidence") or []
            if cited and all(eid in evidence for eid in cited):
                rules[rule["id"]] = rule
    return {"provenance": provenance, "snapshots": snapshots, "evidence_ids": set(evidence), "rule_ids": set(rules),
            "evidence": canonical_bytes([evidence[k] for k in sorted(evidence)]),
            "rules": canonical_bytes([rules[k] for k in sorted(rules)])}


class UnifiedPipelineTests(unittest.TestCase):
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
        self.enterprise = _enterprise_clone(self.dir / "enterprise")

    def _plan(self, label, com17, *, emit=False, retained=None, parent=None, supersede=()):
        toolkit = self.registries.extract_toolkit
        registry = full_registry()

        def extract(from_snap, to_snap, step, store):
            result = driver.extract_pair(from_snap, to_snap, None, registry, store=store, step=step, toolkit=toolkit)
            return result.drafts, result.accounting

        community = {"kind": "GIT_COMMUNITY", "official": False, "url": "local:" + self.community.path,
                     "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3"}
        enterprise = {"kind": "GIT_ENTERPRISE", "official": True, "url": "local:" + str(self.dir / "enterprise"),
                      "expected_origin": ENT_ORIGIN, "licence_access": "ENTERPRISE_AUTHORIZED",
                      "licence_id": LICENCE_ID}
        specs = [
            _spec(COM16, community, "16.0", self.community.from_sha),
            _spec(COM17, community, "17.0", com17),
            _spec(ENT16, enterprise, "16.0", self.enterprise["16.0"]),
            _spec(ENT17, enterprise, "17.0", self.enterprise["17.0"]),
        ]
        return pl.BuildPlan(
            label=label, specs=specs,
            # The enterprise pair first: evidence ids are allocated in pair order (see the module docstring).
            pairs=[{"step": "16-17", "key": "16-17.enterprise", "from": ENT16, "to": ENT17},
                   {"step": "16-17", "key": "16-17", "from": COM16, "to": COM17}],
            base_tree=builtin_handle().root,
            adapters={"GIT_COMMUNITY": GitLocalAdapter("GIT_COMMUNITY"),
                      "GIT_ENTERPRISE": GitLocalAdapter("GIT_ENTERPRISE")},
            adapter_by_source=retained or {}, emit_inventory=emit, parent_dir=parent, supersede=tuple(supersede),
            extract=extract, known_detectors=toolkit.detectors, created_at=CREATED, checked_on="2026-11-08",
            author="unified", tool_version="0.2.0", allow_list=load_allow_list(),
            source_meta={COM16: {"repository": "odoo/odoo"}, COM17: {"repository": "odoo/odoo"},
                         ENT16: {"repository": "odoo/enterprise"}, ENT17: {"repository": "odoo/enterprise"}})

    def _installed(self, home, result):
        self.assertEqual(result.outcome, "OK", result.message)
        self.assertNotEqual(result.completeness, "FAILED")
        return home / "releases" / result.release_id


class UnifiedBuildTests(UnifiedPipelineTests):
    def test_unified_build_installs_both_families_with_inventory(self):
        home = self.dir / "kb"
        result = pl.run_build(home, self._plan("unified-one", self.community.to_sha, emit=True))
        release = self._installed(home, result)
        self.assertEqual([r.release_id for r in list_installed(home)], [result.release_id])
        self.assertEqual(list_installed(home)[0].state.value, "INSTALLED")
        # The staging workdir is created 0700: retained Enterprise blobs may live there (never in a release).
        self.assertEqual(stat.S_IMODE((home / "staging" / "unified-one").stat().st_mode), 0o700)

        meta = _read(release / "release.json")
        self.assertEqual(meta["confidentiality"], "internal")
        self.assertEqual(sorted(s["source_id"] for s in meta["sources"]), sorted([COM16, COM17, ENT16, ENT17]))
        self.assertTrue(all(s.get("confidentiality") == "enterprise"
                            for s in meta["sources"] if s["source_id"] in ENT_IDS))
        verify_provenance(release)
        self.assertEqual(verify_release_tree(release), [])

        staging = home / "staging" / "unified-one"
        self.assertEqual(sorted(p.name for p in (staging / "ledgers").iterdir()),
                         ["16-17.enterprise.json", "16-17.json"])
        self.assertEqual({Ledger.load(p).to_dict()["step"] for p in (staging / "ledgers").iterdir()}, {"16-17"})
        self.assertEqual(sorted(p.name for p in (staging / "accounting").iterdir()),
                         ["16-17.enterprise.json", "16-17.json"])
        self.assertEqual([row["step"] for row in meta["steps_covered"]], ["16-17"])

        inventory_dir = release / "knowledge" / "inventory"
        self.assertEqual(sorted(p.name for p in inventory_dir.iterdir()), ["16.0.json", "17.0.json"])
        document = _read(inventory_dir / "17.0.json")
        self.assertEqual(inventory.verify_inventory(document), [])
        self.assertEqual(sorted(s["source_id"] for s in document["sources"]), sorted([COM17, ENT17]))
        self.assertEqual(document["modules"][ENT_MODULE]["confidentiality"], "enterprise")
        self.assertEqual(document["modules"]["sale_demo"]["confidentiality"], "public")
        self.assertIn("knowledge/inventory/17.0.json", json.dumps(meta["files"]))

    def test_inventory_absent_when_not_enabled(self):
        home = self.dir / "kb"
        result = pl.run_build(home, self._plan("unified-plain", self.community.to_sha))
        release = self._installed(home, result)
        self.assertFalse((release / "knowledge" / "inventory").exists())
        self.assertNotIn("inventory/", json.dumps(_read(release / "release.json")["files"]))
        self.assertEqual(_read(release / "release.json")["confidentiality"], "internal")

    def test_duplicate_step_without_keys_and_duplicate_keys_are_refused(self):
        home = self.dir / "kb"
        pairs = [{"step": "16-17", "from": COM16, "to": COM17}, {"step": "16-17", "from": ENT16, "to": ENT17}]
        with self.assertRaises(ValueError) as ctx:
            pl.run_build(home, pl.BuildPlan(label="dup", pairs=pairs), dry_run=True)
        self.assertIn("16-17", str(ctx.exception))
        keyed = [dict(pairs[0], key="same"), dict(pairs[1], key="same")]
        with self.assertRaises(ValueError):
            pl.plan_fingerprint(pl.BuildPlan(label="dup", pairs=keyed))
        self.assertFalse(home.exists(), "a refused plan writes nothing")


class CarriedEnterpriseTests(UnifiedPipelineTests):
    def _first_release(self, home, label):
        result = pl.run_build(home, self._plan(label, self.community.to_sha, emit=True))
        release = self._installed(home, result)
        entries = _read(release / "provenance" / "sources.json")
        digests = {e["source_id"]: e["snapshot_digest"] for e in entries if e["source_id"] in ENT_IDS}
        return release, digests

    def _retained(self, home, label, digests):
        # The pipeline writes each verified manifest to <workdir>/snapshots/<source_id>.json.
        adapter = RetainedSnapshotAdapter(home / "staging" / label / "snapshots", digests)
        return {ENT16: adapter, ENT17: adapter}

    def test_carried_enterprise_rows_are_byte_identical_in_the_next_release(self):
        home, label = self.dir / "kb", "carry"
        first, digests = self._first_release(home, label)
        self.assertEqual(set(digests), set(ENT_IDS))
        retained = self._retained(home, label, digests)
        new_17 = _repin_community(self.community.path, self.community.from_sha)
        self.assertNotEqual(new_17, self.community.to_sha)
        first_rows = _enterprise_rows(first)
        self.assertGreater(len(first_rows["evidence_ids"]), 0, "the Enterprise pair must contribute evidence")
        self.assertGreater(len(first_rows["rule_ids"]), 0, "an Enterprise-only rule must exist for this check")

        # The re-pinned Community source changes its snapshot. Its changes of this pair link to or collide with the rules
        # of the Enterprise pair, so no rule is removed: the shared rule's Community citation is replaced. No verified
        # item is removed, so the release installs without any approval.
        second = self._installed(home, pl.run_build(home, self._plan(
            label, new_17, emit=True, retained=retained, parent=first)))
        self.assertNotEqual(second.name, first.name)
        second_rows = _enterprise_rows(second)
        self.assertEqual(second_rows["provenance"], first_rows["provenance"])
        self.assertEqual(second_rows["snapshots"], first_rows["snapshots"])
        self.assertEqual(second_rows["evidence_ids"], first_rows["evidence_ids"])
        self.assertEqual(second_rows["evidence"], first_rows["evidence"])
        self.assertEqual(second_rows["rule_ids"], first_rows["rule_ids"])
        self.assertEqual(second_rows["rules"], first_rows["rules"])
        self.assertEqual(_read(second / "release.json")["confidentiality"], "internal")
        revisions = {e["source_id"]: e["revision"] for e in _read(second / "provenance" / "sources.json")}
        self.assertEqual(revisions[COM17], new_17)

    def test_tampered_retained_snapshot_stops_and_keeps_the_previous_release(self):
        home, label = self.dir / "kb", "tamper"
        first, digests = self._first_release(home, label)
        before = {p.name: p.read_bytes() for p in first.rglob("*") if p.is_file()}
        installed_before = [(r.release_id, r.state.value) for r in list_installed(home)]

        tampered = home / "staging" / label / "snapshots" / f"{ENT17}.json"
        altered = _read(tampered)
        altered["snapshot_digest"] = "2" * 64
        tampered.write_bytes(canonical_bytes(altered) + b"\n")

        new_17 = _repin_community(self.community.path, self.community.from_sha)
        result = pl.run_build(home, self._plan(label, new_17, emit=True,
                                               retained=self._retained(home, label, digests), parent=first))
        self.assertEqual(result.outcome, "STOPPED")
        self.assertEqual((result.stopped_at, result.code), (1, "SOURCE_REQUIRED_FAILED"))
        self.assertIn("CHECKSUM_MISMATCH", result.message)
        self.assertEqual([(r.release_id, r.state.value) for r in list_installed(home)], installed_before)
        self.assertEqual({p.name: p.read_bytes() for p in first.rglob("*") if p.is_file()}, before)
        self.assertFalse((home / "active.json").exists())


def _release_evidence(release: Path) -> dict:
    return {path.stem: _read(path) for path in sorted((release / "knowledge" / "evidence").glob("EV-*.json"))}


def _release_rules(release: Path) -> dict:
    rules = {}
    for path in sorted((release / "knowledge" / "compatibility").glob("*.rules.json")):
        for row in _read(path):
            rules[row["id"]] = row
    return rules


def _gate_status(release: Path, gate_id: str) -> dict:
    manifest = _read(release / "coverage" / "coverage-manifest.json")
    return next(gate for gate in manifest["gates"] if gate["gate_id"] == gate_id)


def _step_output(home: Path, label: str, name: str) -> dict:
    return _read(home / "staging" / label / "steps" / name)["output"]


MANUAL_ID = "16-17.python_orm.manual-total"


class SameIdentifierTests(UnifiedPipelineTests):
    """Feature 012 Wave 3c: a change both sources share links to the rule the Enterprise pair generated. Its Community
    evidence ships with that rule; a rule this build did not generate is never extended."""

    def test_shared_rule_cites_evidence_from_both_sources_and_provenance_verifies(self):
        home = self.dir / "kb"
        result = pl.run_build(home, self._plan("same-ids", self.community.to_sha))
        release = self._installed(home, result)
        self.assertIn(result.completeness, ("COMPLETE", "PARTIAL"))
        self.assertEqual([(r.release_id, r.state.value) for r in list_installed(home)],
                         [(result.release_id, "INSTALLED")])
        self.assertEqual(_gate_status(release, "G-EVID")["status"], "PASS")
        verify_provenance(release)
        self.assertEqual(verify_release_tree(release), [])

        evidence = _release_evidence(release)
        shared = [row for row in _release_rules(release).values()
                  if {evidence[eid].get("source_id") for eid in row.get("evidence", []) if eid in evidence} >= {COM17, ENT17}]
        self.assertEqual(len(shared), 1, "one generated rule cites the Community and the Enterprise evidence")
        row = shared[0]
        self.assertEqual((row["origin"], row["maturity"]), ("GENERATED", "DRAFT"))
        self.assertEqual(row["params"], {"method": "compute_total"})
        self.assertEqual(row["detector_ref"], "odooflux.rules.python.generic:flag_method_override")
        cited = {evidence[eid]["source_id"]: evidence[eid] for eid in row["evidence"]}
        self.assertEqual(cited[ENT17]["revision"], self.enterprise["17.0"], "Enterprise row keeps its source revision")
        self.assertEqual(cited[COM17]["revision"], self.community.to_sha, "Community row keeps its source revision")
        self.assertEqual((cited[ENT17]["repository"], cited[COM17]["repository"]),
                         ("odoo/enterprise", "odoo/odoo"))
        for record in cited.values():
            self.assertEqual(record["rule_ids"], [row["id"]])

    def test_repeated_run_reuses_every_step_and_adds_no_evidence(self):
        home = self.dir / "kb"
        plan = self._plan("same-again", self.community.to_sha)
        first = self._installed(home, pl.run_build(home, plan))
        before_evidence = {p.name: p.read_bytes() for p in (first / "knowledge" / "evidence").glob("EV-*.json")}
        before_rules = canonical_bytes(list(_release_rules(first).values()))
        again = pl.run_build(home, plan)
        self.assertEqual((again.outcome, again.release_id), ("OK", first.name))
        self.assertEqual({row["action"] for row in again.rows}, {"REUSE"})
        self.assertEqual({p.name: p.read_bytes() for p in (first / "knowledge" / "evidence").glob("EV-*.json")},
                         before_evidence)
        self.assertEqual(canonical_bytes(list(_release_rules(first).values())), before_rules)

    def test_an_identical_build_under_a_new_label_writes_the_same_evidence(self):
        home = self.dir / "kb"
        first = self._installed(home, pl.run_build(home, self._plan("same-a", self.community.to_sha)))
        second = self._installed(home, pl.run_build(home, self._plan("same-b", self.community.to_sha)))
        self.assertEqual(
            {p.name: p.read_bytes() for p in (second / "knowledge" / "evidence").glob("EV-*.json")},
            {p.name: p.read_bytes() for p in (first / "knowledge" / "evidence").glob("EV-*.json")},
            "no duplicate row: the linked evidence has one id and one content in every build")
        self.assertEqual(canonical_bytes(list(_release_rules(second).values())),
                         canonical_bytes(list(_release_rules(first).values())))
        self.assertEqual(_gate_status(second, "G-EVID")["status"], "PASS")

    def test_link_to_a_manual_rule_ships_nothing_and_leaves_the_rule_alone(self):
        home, label = self.dir / "kb", "manual-link"
        base = self.dir / "base"
        base.mkdir()
        source = builtin_handle().root
        for name in ("evidence", "compatibility", "official_sources", "schemas"):
            shutil.copytree(source / name, base / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(source / "gaps.json", base / "gaps.json")
        builtin_evidence = sorted(k for k in load_knowledge(source).evidence if k.startswith("EV-"))[0]
        manual = {"id": MANUAL_ID, "step": "16-17", "category": "python_orm", "risk": "LOW", "severity": "INFO",
                  "maturity": "DETECT_ONLY", "origin": "MANUAL", "rev": 1, "evidence": [builtin_evidence],
                  "detector_ref": "odooflux.rules.python.generic:flag_method_override", "fixer_ref": None,
                  "params": {"method": "compute_total"}, "tests": {}, "review_required": False,
                  "message": "manual guard for compute_total", "suggestion": "review by hand"}
        compat = base / "compatibility" / "16-17.rules.json"
        rows = _read(compat) + [manual]
        compat.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan = self._plan(label, self.community.to_sha)
        plan.base_tree = base

        result = pl.run_build(home, plan)
        release = self._installed(home, result)
        self.assertIn(result.completeness, ("COMPLETE", "PARTIAL"))
        self.assertEqual(_gate_status(release, "G-EVID")["status"], "PASS")
        self.assertEqual(_release_rules(release)[MANUAL_ID], manual, "the MANUAL rule is byte-for-byte unchanged")

        skipped = _step_output(home, label, "06-candidates.json")["skipped_links"]
        self.assertEqual({item["origin"] for item in skipped}, {"MANUAL"})
        self.assertEqual({item["reason"] for item in skipped}, {"LINKED_RULE_NOT_GENERATED"})
        withheld = {item["change_id"] for item in skipped}
        self.assertEqual(len(withheld), 2, "the Enterprise and the Community compute_total changes")
        shipped_changes = {cid for record in _release_evidence(release).values() for cid in record.get("change_ids", [])}
        self.assertFalse(withheld & shipped_changes, "withheld changes have no shipped evidence")
        for pair_file in (home / "staging" / label / "ledgers").iterdir():
            for record in Ledger.load(pair_file).records():
                if record["change_id"] in withheld:
                    self.assertNotIn(record["disposition"], ("EXISTING_RULE_LINKED", "RULE_CREATED"))


if __name__ == "__main__":
    unittest.main()
