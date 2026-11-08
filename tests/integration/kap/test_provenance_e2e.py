"""End-to-end provenance (feature 011 note 21): verified local clone -> acquired snapshot -> release builder (provenance
writer + manifest) -> portable package -> importer -> Gate 1, offline.

The clone is a synthetic repository (`make_synth_repo`) with `origin` set to the official upstream URL. Every tamper case
edits the built release tree, re-runs the manifest builder so the release is intact, and then requires that Gate 1 (the
existing gate, `release/safety.py`) refuses the FIX_ENABLED rule, both directly and through the importer. The importer
contract (`package/importer.py`): a FIX_ENABLED rule that fails gates is refused with PackageError P10 by default, and
with `downgrade_unverified` it is capped to DETECT_ONLY. A package whose bytes were altered is refused with P06 by
`validate.py`. `socket.socket` is replaced for the whole module.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.sources import SourceRegistry, load_allow_list
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import _zip_bytes_to, export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.release.manifest import verify_release_tree, write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.provenance import PROVENANCE_RELPATH, SNAPSHOT_DIRNAME, sources_meta, \
    verify_provenance, write_provenance
from odooflux.knowledge.release.safety import fix_gate_findings
from tests.fixtures.kap.make_synth_repo import ADDON, build_synth_repo

ORIGIN = "https://github.com/odoo/odoo"
EVIL_ORIGIN = "https://github.com/evil/odoo"
SID = "odoo-community-17.0"
RULE_ID = "16-17.python_orm.sale-demo-get-amount-rename"
EVIDENCE_ID = "EV-201"
SALE_ORDER = f"{ADDON}/models/sale_order.py"
CREATED = "2026-11-08T10:00:00Z"
ALLOW = load_allow_list()
META = {
    "label": "community-16-17-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-08T10:00:00Z", "host_free": True},
}


def _git(repo: Path, *args) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"})


def _spec(repo: Path, revision: str) -> dict:
    return {
        "source_id": SID, "kind": "GIT_COMMUNITY", "official": True, "url": f"local:{repo}",
        "expected_origin": ORIGIN, "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3.0", "branch": "17.0",
        "revision": revision, "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


def _acquire(repo: Path, revision: str, store_root: Path):
    """Register, acquire and verify the official clone. Returns (snapshot manifest, registry record)."""
    registry = SourceRegistry(allow_list=ALLOW)
    spec = _spec(repo, revision)
    registry.add(spec)
    store = BlobStore(store_root)
    snap = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW).snapshot(spec, store, created_at=CREATED)
    registry.transition(SID, "RETRIEVED", checksum=snap["snapshot_digest"], retrieved_at=CREATED)
    for entry in snap["entries"]:
        store.get(entry["sha256"])  # verify-on-read, as `kap_source verify` does
    registry.transition(SID, "VERIFIED")
    return snap, registry.get(SID)


def _evidence(snap: dict) -> dict:
    sale_order = next(e for e in snap["entries"] if e["path"] == SALE_ORDER)
    return {
        "id": EVIDENCE_ID, "rule_ids": [RULE_ID], "category": "orm", "origin": "KAP_MANUAL",
        "source_id": SID, "official": True, "change_ids": [],
        "source_applicability": {"from": "16.0", "to": "17.0"},
        "target_applicability": {"from": "17.0", "to": None},
        "description": "get_amount_old is replaced by get_amount in 17.0",
        "url": f"{ORIGIN}/blob/{snap['revision']}/{SALE_ORDER}", "repository": "odoo/odoo",
        "revision": snap["revision"],
        "locations": [{"branch": "17.0", "revision": snap["revision"], "path": SALE_ORDER, "line": 1,
                       "match": "def get_amount(", "kind": "present", "content_sha256": sale_order["sha256"],
                       "snapshot_ref": snap["snapshot_id"]}],
        "detection_method": "grep on pinned source", "proposed_transformation": "rename get_amount_old call",
        "risk": "LOW", "required_validation": ["python_runtime"], "status": "DOCUMENTED_NOT_TESTED",
        "checked_on": "2026-11-08", "checked_by": "kap-provenance-e2e",
    }


def _rule() -> dict:
    return {
        "id": RULE_ID, "step": "16-17", "category": "python_orm", "maturity": "FIX_ENABLED", "risk": "LOW",
        "severity": "WARNING", "file_kinds": ["python"], "review_required": False, "ai_eligible": False,
        "origin": "MANUAL", "evidence": [EVIDENCE_ID], "depends_on": [], "conflicts_with": [], "params": {},
        "detector_ref": "odooflux.rules.python.generic:flag_decorator",
        "fixer_ref": "odooflux.rules.python.generic:remove_decorator",
        "tests": {"positive": "T1", "negative": "T2", "idempotence": "T3"},
        "message": "get_amount_old is replaced by get_amount", "suggestion": "call get_amount",
    }


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_release(root: Path, snap: dict, rec: dict) -> Path:
    """Release tree with one FIX_ENABLED rule backed by one official, verified evidence record."""
    tree = root / "release"
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", tree / "knowledge" / "official_sources")
    _write_json(tree / "knowledge" / "compatibility" / "versions.json", {"versions": [], "transitions": []})
    _write_json(tree / "knowledge" / "compatibility" / "16-17.rules.json", [_rule()])
    _write_json(tree / "knowledge" / "evidence" / f"{EVIDENCE_ID}.json", _evidence(snap))
    # The loader checks evidence revisions against the release's pinned revision catalogue (E003). The synthetic clone
    # is pinned here as an entry of this release; the shipped catalogue is kept as it is.
    catalogue = json.loads((KNOWLEDGE_ROOT / "official_sources" / "revisions.json").read_text(encoding="utf-8"))
    catalogue.append({"repository": "odoo/odoo", "branch": "17.0", "revision": snap["revision"],
                      "committed": "2024-03-09", "pinned_on": "2026-11-08", "tags": []})
    _write_json(tree / "knowledge" / "official_sources" / "revisions.json", catalogue)
    _write_json(tree / "coverage" / "coverage-manifest.json", {"items": []})
    entries = write_provenance(tree, [snap], [rec])
    write_release_manifest(tree, {**META, "sources": sources_meta(entries)})
    return tree


def _resync(tree: Path, entries: list) -> None:
    """Re-run the manifest builder over the tampered tree so the release itself stays intact."""
    write_release_manifest(tree, {**META, "sources": sources_meta(entries)})


def _provenance(tree: Path) -> list:
    return json.loads((tree / PROVENANCE_RELPATH).read_text(encoding="utf-8"))


def _edit_provenance(tree: Path, change) -> list:
    entries = _provenance(tree)
    for entry in entries:
        change(entry)
    _write_json(tree / PROVENANCE_RELPATH, entries)
    return entries


def _repack_member(source: Path, dest: Path, member: str, data: bytes) -> None:
    """Copy a package, replacing one member's bytes and keeping every other member as it was."""
    with zipfile.ZipFile(source) as zf:
        members = [(name, data if name == member else zf.read(name)) for name in zf.namelist()]
    _zip_bytes_to(dest, members)


class ProvenanceEndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        net = mock.patch("socket.socket", side_effect=AssertionError("network is disabled in tests"))
        net.start()
        self.addCleanup(net.stop)
        synth = build_synth_repo(self.base / "clone")
        self.repo = Path(synth.path)
        _git(self.repo, "remote", "add", "origin", ORIGIN)
        self.revision = synth.to_sha
        self.snap, self.rec = _acquire(self.repo, self.revision, self.base / "store")
        self.tree = _build_release(self.base / "baseline", self.snap, self.rec)

    def _fresh_tree(self, label: str) -> Path:
        return _build_release(self.base / label, self.snap, self.rec)

    def _refused(self, package: Path, kb: Path, code: str) -> None:
        with self.assertRaises(PackageError) as ctx:
            import_package(package, kb)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(list((kb / "releases").iterdir()), [])
        self.assertFalse((kb / "active.json").exists())


class TestGateOneOnBuiltRelease(ProvenanceEndToEnd):
    def test_built_release_passes_gate_one_and_verifies(self):
        verify_provenance(self.tree)
        self.assertEqual(verify_release_tree(self.tree), [])
        self.assertEqual(fix_gate_findings(self.tree / "knowledge"), [])

    def test_official_identity_is_bound_in_provenance_and_release(self):
        entry = _provenance(self.tree)[0]
        self.assertEqual((entry["source_id"], entry["origin_url"], entry["url"]), (SID, ORIGIN, ORIGIN))
        release = json.loads((self.tree / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(release["sources"][0]["origin_url"], ORIGIN)
        self.assertEqual(release["sources"][0]["snapshot_id"], self.snap["snapshot_id"])

    def test_determinism_two_builds_from_same_inputs(self):
        # A second acquisition of the same clone into a fresh store and a fresh tree.
        snap2, rec2 = _acquire(self.repo, self.revision, self.base / "store2")
        self.assertEqual(snap2, self.snap)
        tree2 = _build_release(self.base / "second", snap2, rec2)
        first = json.loads((self.tree / "release.json").read_text(encoding="utf-8"))
        second = json.loads((tree2 / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(first["release_digest"], second["release_digest"])
        self.assertEqual(first["release_id"], second["release_id"])
        self.assertEqual((self.tree / PROVENANCE_RELPATH).read_bytes(), (tree2 / PROVENANCE_RELPATH).read_bytes())

    def test_identity_tamper_changes_release_digest(self):
        before = json.loads((self.tree / "release.json").read_text(encoding="utf-8"))["release_digest"]
        entries = _edit_provenance(self.tree, lambda e: e.update(origin_url=EVIL_ORIGIN))
        self.assertTrue(verify_release_tree(self.tree))  # provenance is hashed by the release manifest
        self.assertTrue(entries)
        _resync(self.tree, entries)
        after = json.loads((self.tree / "release.json").read_text(encoding="utf-8"))["release_digest"]
        self.assertNotEqual(before, after)
        with self.assertRaises(KnowledgeReleaseError):
            verify_provenance(self.tree)


class TestImporterAcceptsOnlyValidProvenance(ProvenanceEndToEnd):
    def test_valid_provenance_accepted_by_importer(self):
        package = export_package(self.tree, self.base / "valid.ofkp")
        kb = self.base / "kb-valid"
        result = import_package(package.path, kb)
        self.assertTrue(result.installed)
        self.assertEqual(result.downgraded_rules, ())
        installed = kb / "releases" / package.release_id
        rules = json.loads((installed / "knowledge" / "compatibility" / "16-17.rules.json").read_text("utf-8"))
        self.assertEqual(rules[0]["maturity"], "FIX_ENABLED")
        self.assertEqual(fix_gate_findings(installed / "knowledge"), [])

    def test_fail_closed_tamper_cases(self):
        def provenance_missing(tree):
            entries = _provenance(tree)
            (tree / PROVENANCE_RELPATH).unlink()
            _resync(tree, entries)

        def revision_altered(tree):
            _resync(tree, _edit_provenance(tree, lambda e: e.update(revision="c" * 40)))

        def digest_altered(tree):
            _resync(tree, _edit_provenance(tree, lambda e: e.update(snapshot_digest="e" * 64)))

        def origin_missing(tree):
            _resync(tree, _edit_provenance(tree, lambda e: e.update(origin_url=None)))

        def origin_not_allowlisted(tree):
            _resync(tree, _edit_provenance(tree, lambda e: e.update(origin_url=EVIL_ORIGIN)))

        def official_false(tree):
            _resync(tree, _edit_provenance(tree, lambda e: e.update(official=False)))

        def evidence_source_unknown(tree):
            path = tree / "knowledge" / "evidence" / f"{EVIDENCE_ID}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["source_id"] = "community-ghost-01"
            _write_json(path, record)
            _resync(tree, _provenance(tree))

        def snapshot_file_missing(tree):
            (tree / SNAPSHOT_DIRNAME / f"{self.snap['snapshot_id']}.json").unlink()
            _resync(tree, _provenance(tree))

        cases = {
            "provenance/sources.json missing": provenance_missing,
            "entry revision altered": revision_altered,
            "entry snapshot_digest altered": digest_altered,
            "origin_url missing": origin_missing,
            "origin_url not allow-listed": origin_not_allowlisted,
            "source marked official=false": official_false,
            "evidence source_id not in provenance": evidence_source_unknown,
            "shipped snapshot file missing": snapshot_file_missing,
        }
        for index, (label, mutate) in enumerate(cases.items()):
            with self.subTest(case=label):
                tree = self._fresh_tree(f"case-{index}")
                mutate(tree)
                self.assertEqual(verify_release_tree(tree), [])  # the release itself is intact
                findings = fix_gate_findings(tree / "knowledge")
                self.assertTrue(any(f["gate"] == 1 and f["rule_id"] == RULE_ID for f in findings), findings)
                package = export_package(tree, self.base / f"case-{index}.ofkp")
                self._refused(package.path, self.base / f"kb-case-{index}", "P10")

    def test_downgrade_option_caps_refused_rule(self):
        def provenance_missing(tree):
            entries = _provenance(tree)
            (tree / PROVENANCE_RELPATH).unlink()
            _resync(tree, entries)

        tree = self._fresh_tree("downgrade")
        provenance_missing(tree)
        package = export_package(tree, self.base / "downgrade.ofkp")
        kb = self.base / "kb-downgrade"
        result = import_package(package.path, kb, downgrade_unverified=True)
        self.assertEqual(result.downgraded_rules, (RULE_ID,))
        # The downgrade rewrites the staged manifest, so the installed release has the id returned by the importer.
        rules = json.loads((kb / "releases" / result.release_id / "knowledge" / "compatibility" /
                            "16-17.rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules[0]["maturity"], "DETECT_ONLY")

    def test_snapshot_altered_after_build_fails_release_verification(self):
        package = export_package(self.tree, self.base / "clean.ofkp")
        snap_path = self.tree / SNAPSHOT_DIRNAME / f"{self.snap['snapshot_id']}.json"
        original = snap_path.read_bytes()
        altered = original.replace(b'"kind":"python"', b'"kind":"pyth0n"', 1)  # same length, different bytes
        self.assertNotEqual(altered, original)
        snap_path.write_bytes(altered)

        self.assertTrue(verify_release_tree(self.tree))
        with self.assertRaises(KnowledgeReleaseError):
            verify_provenance(self.tree)
        with self.assertRaises(KnowledgeReleaseError):
            export_package(self.tree, self.base / "altered.ofkp")

        # The package built before the alteration, with its snapshot bytes replaced in transit, is refused by P06.
        repacked = self.base / "repacked.ofkp"
        _repack_member(package.path, repacked, f"{SNAPSHOT_DIRNAME}/{self.snap['snapshot_id']}.json", altered)
        self._refused(repacked, self.base / "kb-repacked", "P06")

    def test_clone_remote_swapped_before_acquisition_builds_no_release(self):
        _git(self.repo, "remote", "set-url", "origin", EVIL_ORIGIN)
        registry = SourceRegistry(allow_list=ALLOW)
        spec = _spec(self.repo, self.revision)
        registry.add(spec)
        store = BlobStore(self.base / "store-swapped")
        with self.assertRaises(SourceError) as ctx:
            GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW).snapshot(spec, store, created_at=CREATED)
        self.assertEqual(ctx.exception.code, "OFFICIAL_IDENTITY_UNVERIFIED")
        registry.transition(SID, "FAILED", failure_reason=f"OFFICIAL_IDENTITY_UNVERIFIED: {ctx.exception.message}")
        failed = registry.get(SID)
        self.assertEqual(failed["status"], "FAILED")
        tree = self.base / "no-release"
        tree.mkdir()
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [], [failed])
        self.assertFalse((tree / PROVENANCE_RELPATH).exists())
        self.assertFalse((tree / SNAPSHOT_DIRNAME).exists())


if __name__ == "__main__":
    unittest.main()
