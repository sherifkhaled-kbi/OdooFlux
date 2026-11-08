"""TST-011-006 (REQ-KAP-022, REQ-KAP-024): release manifest build, digest and tree verification."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.release.manifest import (
    build_manifest,
    require_intact,
    verify_release_tree,
    write_release_manifest,
)
from odooflux.knowledge.release.model import KnowledgeReleaseError, release_id_from_digest

META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}

FILES = {
    "knowledge/rules/RULE-001.json": b'{"id": "RULE-001"}\n',
    "knowledge/evidence/EV-001.json": b'{"id": "EV-001", "note": "x"}\n',
}


def _make_tree(root: Path, files: dict) -> Path:
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


class ReleaseManifestTests(unittest.TestCase):
    def test_digest_function_of_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tree_a = _make_tree(base / "a", FILES)
            # same bytes, opposite creation order, different directory: same digest
            reversed_files = dict(reversed(list(FILES.items())))
            tree_b = _make_tree(base / "b", reversed_files)
            manifest_a = build_manifest(tree_a, META)
            manifest_b = build_manifest(tree_b, META)
            self.assertEqual(manifest_a["release_digest"], manifest_b["release_digest"])
            self.assertEqual(manifest_a["release_id"], manifest_b["release_id"])

            # the digest is sha256 of the canonical manifest without release_id and release_digest
            body = {k: v for k, v in manifest_a.items() if k not in ("release_id", "release_digest")}
            self.assertEqual(manifest_a["release_digest"], digest_obj(body))
            self.assertEqual(manifest_a["release_id"], release_id_from_digest(manifest_a["release_digest"]))

            # file entries are sorted, carry sha256 and size, and release.json is never listed
            paths = [entry["path"] for entry in manifest_a["files"]]
            self.assertEqual(paths, sorted(FILES))
            first = manifest_a["files"][0]
            self.assertEqual(first["size"], len(FILES[first["path"]]))
            self.assertEqual(len(first["sha256"]), 64)

            # one changed byte in one file gives a different digest
            changed = dict(FILES)
            changed["knowledge/rules/RULE-001.json"] = b'{"id": "RULE-002"}\n'
            tree_c = _make_tree(base / "c", changed)
            self.assertNotEqual(build_manifest(tree_c, META)["release_digest"], manifest_a["release_digest"])

    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = _make_tree(Path(tmp), FILES)
            write_release_manifest(tree, META)
            self.assertEqual(verify_release_tree(tree), [])
            require_intact(tree)

            # edit one byte of a release file: verification names that path
            (tree / "knowledge/rules/RULE-001.json").write_bytes(b'{"id": "RULE-999"}\n')
            problems = verify_release_tree(tree)
            self.assertTrue(any("knowledge/rules/RULE-001.json" in p for p in problems), problems)
            with self.assertRaises(KnowledgeReleaseError):
                require_intact(tree)

            # restore the bytes, then edit the manifest's digest: the release is rejected
            (tree / "knowledge/rules/RULE-001.json").write_bytes(FILES["knowledge/rules/RULE-001.json"])
            release_json = tree / "release.json"
            data = json.loads(release_json.read_text(encoding="utf-8"))
            data["release_digest"] = "ef" * 32
            release_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.assertTrue(verify_release_tree(tree))
            with self.assertRaises(KnowledgeReleaseError):
                require_intact(tree)

    def test_extra_file_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = _make_tree(Path(tmp), FILES)
            write_release_manifest(tree, META)

            (tree / "knowledge/rules/UNLISTED.json").write_bytes(b"{}\n")
            problems = verify_release_tree(tree)
            self.assertTrue(any("extra" in p and "UNLISTED.json" in p for p in problems), problems)
            (tree / "knowledge/rules/UNLISTED.json").unlink()
            self.assertEqual(verify_release_tree(tree), [])

            # a listed file that disappears is reported as missing
            (tree / "knowledge/evidence/EV-001.json").unlink()
            problems = verify_release_tree(tree)
            self.assertTrue(any("missing" in p and "EV-001.json" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
