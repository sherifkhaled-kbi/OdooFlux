"""Release provenance writer (feature 011 notes 15, 19, 20; release gate 1 in release/safety.py).

`write_provenance` ships each verified snapshot manifest under `snapshots/` and writes `provenance/sources.json`; the
release manifest carries the same identity through `sources_meta`; `verify_provenance` cross-checks the three. The
origin is a declared identity, not cryptographic authenticity. Offline: no network, no git; the snapshots are built
from plain directories and their verified origin is set the way the git-local adapter sets it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.acquisition.snapshot import build_snapshot
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.manifest import verify_release_tree, write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.provenance import (
    ENTRY_FIELDS, PROVENANCE_RELPATH, SOURCE_META_FIELDS, SNAPSHOT_DIRNAME, sources_meta, verify_provenance,
    write_provenance,
)

ORIGIN = "https://github.com/odoo/odoo"
REV = "a" * 40
DIR_REV = "sha256:" + "b" * 64
META = {
    "label": "community-17.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-08T10:00:00Z", "host_free": True},
}


def _write_source_tree(root: Path, name: str, text: str) -> Path:
    tree = root / name
    (tree / "addons" / "demo").mkdir(parents=True)
    (tree / "addons" / "demo" / "models.py").write_text(text, encoding="utf-8")
    return tree


class ProvenanceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.store = BlobStore(self.base / "store")
        self.official_snap = build_snapshot(_write_source_tree(self.base, "odoo", "x = 1\n"),
                                            "odoo-community-17.0", REV, self.store,
                                            created_at="2026-11-08T10:00:00Z")
        # Recorded the way git_local.py records a verified official clone: origin_url is not digested.
        self.official_snap["origin_url"] = ORIGIN
        self.official_rec = {
            "source_id": "odoo-community-17.0", "kind": "GIT_COMMUNITY", "official": True,
            "url": "local:" + str(self.base / "clone-17"), "expected_origin": ORIGIN, "revision": REV,
            "status": "VERIFIED", "checksum": self.official_snap["snapshot_digest"],
        }
        self.dir_snap = build_snapshot(_write_source_tree(self.base, "pack", "y = 2\n"), "dir-pack-01", DIR_REV,
                                       self.store, created_at="2026-11-08T10:00:00Z")
        self.dir_rec = {
            "source_id": "dir-pack-01", "kind": "DIRECTORY", "official": False,
            "url": "local:" + str(self.base / "pack"), "revision": DIR_REV, "status": "VERIFIED",
            "checksum": self.dir_snap["snapshot_digest"],
        }

    def _release(self, name="release") -> Path:
        tree = self.base / name
        (tree / "coverage").mkdir(parents=True)
        (tree / "coverage" / "coverage-manifest.json").write_text('{"items": []}\n', encoding="utf-8")
        return tree

    def _write(self, tree: Path, snapshots=None, records=None):
        snaps = [self.official_snap, self.dir_snap] if snapshots is None else snapshots
        recs = [self.official_rec, self.dir_rec] if records is None else records
        entries = write_provenance(tree, snaps, recs)
        write_release_manifest(tree, {**META, "sources": sources_meta(entries)})
        return entries


class TestWriteProvenance(ProvenanceTestCase):
    def test_entries_sorted_with_exact_fields_and_no_local_path(self):
        tree = self._release()
        entries = self._write(tree)
        self.assertEqual([e["source_id"] for e in entries], ["dir-pack-01", "odoo-community-17.0"])
        for entry in entries:
            self.assertEqual(set(entry), set(ENTRY_FIELDS))
        official = entries[1]
        self.assertEqual(official["url"], ORIGIN)  # the verified origin, never the local clone path
        self.assertEqual(official["origin_url"], ORIGIN)
        self.assertEqual(official["snapshot_id"], self.official_snap["snapshot_id"])
        self.assertEqual(official["snapshot_digest"], self.official_snap["snapshot_digest"])
        self.assertIs(official["official"], True)
        self.assertEqual(entries[0]["url"], "local:redacted")
        self.assertIsNone(entries[0]["origin_url"])
        text = (tree / PROVENANCE_RELPATH).read_text(encoding="utf-8")
        self.assertNotIn(str(self.base), text)
        self.assertFalse(any(part in text for part in ("/home/", "/tmp/")))

    def test_snapshot_manifest_copied_canonically_and_digest_unchanged(self):
        tree = self._release()
        self._write(tree)
        shipped = tree / SNAPSHOT_DIRNAME / f"{self.official_snap['snapshot_id']}.json"
        self.assertEqual(shipped.read_bytes(), canonical_bytes(self.official_snap) + b"\n")
        self.assertFalse((tree / SNAPSHOT_DIRNAME / "blobs").exists())
        self.assertEqual(json.loads(shipped.read_text(encoding="utf-8"))["snapshot_digest"],
                         self.official_snap["snapshot_digest"])

    def test_refuses_missing_snapshot_and_writes_nothing(self):
        tree = self._release()
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [self.official_snap], [self.official_rec, self.dir_rec])
        self.assertFalse((tree / PROVENANCE_RELPATH).exists())
        self.assertFalse((tree / SNAPSHOT_DIRNAME).exists())

    def test_refuses_recomputed_digest_mismatch(self):
        tree = self._release()
        tampered = json.loads(canonical_bytes(self.official_snap))
        tampered["entries"][0]["size"] += 1
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [tampered, self.dir_snap], [self.official_rec, self.dir_rec])
        self.assertFalse((tree / PROVENANCE_RELPATH).exists())

    def test_refuses_status_not_verified(self):
        for status in ("RETRIEVED", "FAILED", "UNAVAILABLE", "DECLARED"):
            with self.subTest(status=status):
                tree = self._release(f"release-{status}")
                rec = {**self.official_rec, "status": status}
                with self.assertRaises(KnowledgeReleaseError):
                    write_provenance(tree, [self.official_snap, self.dir_snap], [rec, self.dir_rec])

    def test_refuses_official_without_verified_origin(self):
        cases = {
            "origin missing": {"origin_url": None},
            "origin not allow-listed": {"origin_url": "https://github.com/evil/odoo"},
            "origin is a lookalike": {"origin_url": "https://github.com/odoo/odoo-evil"},
        }
        for label, change in cases.items():
            with self.subTest(label=label):
                snap = {**self.official_snap, **change}
                tree = self._release(f"release-{len(label)}")
                with self.assertRaises(KnowledgeReleaseError):
                    write_provenance(tree, [snap, self.dir_snap], [self.official_rec, self.dir_rec])
                self.assertFalse((tree / PROVENANCE_RELPATH).exists())

    def test_refuses_origin_that_disagrees_with_expected_origin(self):
        tree = self._release()
        rec = {**self.official_rec, "expected_origin": "https://github.com/odoo/documentation"}
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [self.official_snap, self.dir_snap], [rec, self.dir_rec])

    def test_refuses_revision_disagreeing_with_snapshot(self):
        tree = self._release()
        rec = {**self.official_rec, "revision": "c" * 40}
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [self.official_snap, self.dir_snap], [rec, self.dir_rec])

    def test_refuses_unbound_extra_snapshot(self):
        tree = self._release()
        extra = build_snapshot(_write_source_tree(self.base, "extra", "z = 3\n"), "extra-src-01", DIR_REV,
                               self.store, created_at="2026-11-08T10:00:00Z")
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [self.official_snap, self.dir_snap, extra], [self.official_rec, self.dir_rec])

    def test_official_kind_must_be_community_or_docs(self):
        tree = self._release()
        rec = {**self.official_rec, "kind": "UPGRADE_SCRIPTS"}
        with self.assertRaises(KnowledgeReleaseError):
            write_provenance(tree, [self.official_snap, self.dir_snap], [rec, self.dir_rec])

    def test_deterministic_across_two_builds(self):
        first, second = self._release("first"), self._release("second")
        self._write(first)
        self._write(second)
        self.assertEqual((first / PROVENANCE_RELPATH).read_bytes(), (second / PROVENANCE_RELPATH).read_bytes())
        self.assertEqual(sorted(p.name for p in (first / SNAPSHOT_DIRNAME).iterdir()),
                         sorted(p.name for p in (second / SNAPSHOT_DIRNAME).iterdir()))
        self.assertEqual(json.loads((first / "release.json").read_text(encoding="utf-8"))["release_digest"],
                         json.loads((second / "release.json").read_text(encoding="utf-8"))["release_digest"])


class TestSourcesMeta(ProvenanceTestCase):
    def test_meta_keys_and_order(self):
        entries = write_provenance(self._release(), [self.official_snap, self.dir_snap],
                                   [self.official_rec, self.dir_rec])
        meta = sources_meta(entries)
        self.assertEqual([m["source_id"] for m in meta], ["dir-pack-01", "odoo-community-17.0"])
        for item in meta:
            self.assertEqual(set(item), set(SOURCE_META_FIELDS))
        self.assertEqual(meta[1]["origin_url"], ORIGIN)
        self.assertEqual(meta[1]["snapshot_id"], self.official_snap["snapshot_id"])

    def test_release_json_binds_the_identity(self):
        tree = self._release()
        self._write(tree)
        release = json.loads((tree / "release.json").read_text(encoding="utf-8"))
        bound = {s["source_id"]: s for s in release["sources"]}
        self.assertEqual(bound["odoo-community-17.0"]["origin_url"], ORIGIN)
        self.assertEqual(bound["odoo-community-17.0"]["snapshot_id"], self.official_snap["snapshot_id"])
        self.assertEqual(verify_release_tree(tree), [])


class TestVerifyProvenance(ProvenanceTestCase):
    def test_intact_release_verifies(self):
        tree = self._release()
        self._write(tree)
        verify_provenance(tree)

    def _rewrite_manifest_with(self, tree: Path, entries) -> None:
        write_release_manifest(tree, {**META, "sources": sources_meta(entries)})

    def test_alterations_fail_closed(self):
        cases = {}

        def edit_entry(tree, field, value):
            path = tree / PROVENANCE_RELPATH
            entries = json.loads(path.read_text(encoding="utf-8"))
            for entry in entries:
                if entry["source_id"] == "odoo-community-17.0":
                    entry[field] = value
            path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return entries

        def case_revision(tree):
            entries = edit_entry(tree, "revision", "c" * 40)
            self._rewrite_manifest_with(tree, entries)

        def case_digest(tree):
            entries = edit_entry(tree, "snapshot_digest", "e" * 64)
            self._rewrite_manifest_with(tree, entries)

        def case_origin_removed(tree):
            entries = edit_entry(tree, "origin_url", None)
            self._rewrite_manifest_with(tree, entries)

        def case_origin_swapped(tree):
            entries = edit_entry(tree, "origin_url", "https://github.com/odoo/odoo-evil")
            self._rewrite_manifest_with(tree, entries)

        def case_entry_removed(tree):
            path = tree / PROVENANCE_RELPATH
            entries = [e for e in json.loads(path.read_text(encoding="utf-8")) if e["source_id"] != "dir-pack-01"]
            path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self._rewrite_manifest_with(tree, entries)

        def case_extra_entry(tree):
            path = tree / PROVENANCE_RELPATH
            entries = json.loads(path.read_text(encoding="utf-8"))
            ghost = {**entries[0], "source_id": "ghost-src-01"}
            entries = sorted(entries + [ghost], key=lambda e: e["source_id"])
            path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self._rewrite_manifest_with(tree, entries)

        def case_provenance_missing(tree):
            (tree / PROVENANCE_RELPATH).unlink()

        def case_meta_disagrees(tree):
            # provenance changed, release.json left at the original identity: the manifest sources disagree.
            edit_entry(tree, "revision", "c" * 40)

        def case_snapshot_missing(tree):
            (tree / SNAPSHOT_DIRNAME / f"{self.official_snap['snapshot_id']}.json").unlink()

        def case_snapshot_altered(tree):
            path = tree / SNAPSHOT_DIRNAME / f"{self.official_snap['snapshot_id']}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["entries"][0]["size"] += 1
            path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")

        def case_extra_snapshot(tree):
            (tree / SNAPSHOT_DIRNAME / "ss-000000000000.json").write_text("{}\n", encoding="utf-8")

        cases.update({
            "revision altered": case_revision, "snapshot_digest altered": case_digest,
            "origin_url removed": case_origin_removed, "origin_url swapped": case_origin_swapped,
            "entry removed": case_entry_removed, "extra entry": case_extra_entry,
            "provenance missing": case_provenance_missing, "release.json disagrees": case_meta_disagrees,
            "snapshot file missing": case_snapshot_missing, "snapshot file altered": case_snapshot_altered,
            "extra snapshot file": case_extra_snapshot,
        })
        for label, mutate in cases.items():
            with self.subTest(label=label):
                tree = self._release(f"tamper-{len(label)}-{label.replace(' ', '-')}")
                self._write(tree)
                mutate(tree)
                with self.assertRaises(KnowledgeReleaseError):
                    verify_provenance(tree)

    def test_identity_change_is_visible_to_release_digest(self):
        tree = self._release()
        self._write(tree)
        before = json.loads((tree / "release.json").read_text(encoding="utf-8"))["release_digest"]
        path = tree / PROVENANCE_RELPATH
        entries = json.loads(path.read_text(encoding="utf-8"))
        entries[-1]["origin_url"] = None
        path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertTrue(verify_release_tree(tree))  # the file is hashed by the release manifest
        write_release_manifest(tree, {**META, "sources": sources_meta(entries)})
        after = json.loads((tree / "release.json").read_text(encoding="utf-8"))["release_digest"]
        self.assertNotEqual(before, after)



class TestEnterpriseDerivedRefused(ProvenanceTestCase):
    """Note 35: a snapshot of an Enterprise-derived source is metadata about licensed content and is never shipped."""

    def test_enterprise_derived_source_refused_with_code_and_nothing_written(self):
        tree = self._release("enterprise")
        rec = {**self.official_rec, "enterprise_derived": True}
        with self.assertRaises(KnowledgeReleaseError) as ctx:
            write_provenance(tree, [self.official_snap], [rec])
        self.assertIn("ENTERPRISE_DERIVED_REFUSED", str(ctx.exception))
        self.assertFalse((tree / PROVENANCE_RELPATH).exists())
        self.assertFalse((tree / SNAPSHOT_DIRNAME).exists())

    def test_enterprise_flag_false_is_not_refused(self):
        tree = self._release("not-enterprise")
        entries = write_provenance(tree, [self.official_snap], [{**self.official_rec, "enterprise_derived": False}])
        self.assertEqual([e["source_id"] for e in entries], ["odoo-community-17.0"])


if __name__ == "__main__":
    unittest.main()
