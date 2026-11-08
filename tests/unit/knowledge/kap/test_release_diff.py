"""TST-011-014 (REQ-KAP-030): release diff, record level for rules and evidence, destructive-change detection."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.release.diff import diff_releases
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError

META = {
    "label": "diff-test",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}


def _rule(rid, message="m"):
    return {"id": rid, "step": "16-17", "maturity": "DETECT_ONLY", "evidence": ["EV-900"], "message": message}


def _evidence(eid, status="DOCUMENTED_NOT_TESTED"):
    return {"id": eid, "status": status, "rule_ids": []}


def _release(root: Path, rules, evidence, extra=None) -> Path:
    (root / "compatibility").mkdir(parents=True)
    (root / "evidence").mkdir(parents=True)
    (root / "compatibility" / "16-17.rules.json").write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n",
                                                             encoding="utf-8")
    for record in evidence:
        (root / "evidence" / f"{record['id']}.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                                                encoding="utf-8")
    for rel, text in (extra or {}).items():
        (root / rel).write_text(text, encoding="utf-8")
    write_release_manifest(root, META)
    return root


def _index(diff):
    return {(e["family"], e["id"]): e for e in diff.entries if e["kind"] == "record"}


class ReleaseDiffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_diff_lists_added_removed_changed(self):
        a = _release(self.base / "a", [_rule("16-17.python.one", "old"), _rule("16-17.python.two")],
                     [_evidence("EV-900")])
        b = _release(self.base / "b", [_rule("16-17.python.one", "new"), _rule("16-17.python.three")],
                     [_evidence("EV-900"), _evidence("EV-901")])
        diff = diff_releases(a, b)
        index = _index(diff)
        self.assertEqual("CHANGED", index[("rules", "16-17.python.one")]["change"])
        self.assertEqual("REMOVED", index[("rules", "16-17.python.two")]["change"])
        self.assertEqual("ADDED", index[("rules", "16-17.python.three")]["change"])
        self.assertEqual("ADDED", index[("evidence", "EV-901")]["change"])
        self.assertNotIn(("evidence", "EV-900"), index)
        self.assertEqual({"added": 1, "removed": 0, "changed": 0}, diff.counts["evidence"])
        self.assertEqual({"added": 1, "removed": 1, "changed": 1}, diff.counts["rules"])

    def test_removal_flagged_destructive(self):
        a = _release(self.base / "a", [_rule("16-17.python.one"), _rule("16-17.python.two")],
                     [_evidence("EV-900", "VERIFIED"), _evidence("EV-901")])
        b = _release(self.base / "b", [_rule("16-17.python.one")], [])
        diff = diff_releases(a, b)
        index = _index(diff)
        self.assertTrue(index[("rules", "16-17.python.two")]["destructive"])
        self.assertTrue(index[("evidence", "EV-900")]["destructive"])
        self.assertFalse(index[("evidence", "EV-901")]["destructive"])
        self.assertTrue(diff.has_destructive)
        self.assertEqual(2, len(diff.destructive_entries()))

    def test_unchanged_bytes_identical(self):
        files = {"gaps.json": "[]\n"}
        a = _release(self.base / "a", [_rule("16-17.python.one")], [_evidence("EV-900")], files)
        b = _release(self.base / "b", [_rule("16-17.python.one")], [_evidence("EV-900")], files)
        diff = diff_releases(a, b)
        self.assertEqual([], diff.entries)
        self.assertFalse(diff.has_destructive)
        self.assertGreaterEqual(diff.unchanged, 3)
        self.assertEqual((a / "compatibility" / "16-17.rules.json").read_bytes(),
                         (b / "compatibility" / "16-17.rules.json").read_bytes())

    def test_file_level_change_for_other_files(self):
        a = _release(self.base / "a", [_rule("16-17.python.one")], [], {"gaps.json": "[]\n"})
        b = _release(self.base / "b", [_rule("16-17.python.one")], [], {"gaps.json": "[1]\n"})
        diff = diff_releases(a, b)
        self.assertEqual([{"kind": "file", "family": "gaps.json", "id": "gaps.json", "change": "CHANGED",
                           "destructive": False}], diff.entries)

    def test_tampered_release_refused(self):
        a = _release(self.base / "a", [_rule("16-17.python.one")], [_evidence("EV-900")])
        b = _release(self.base / "b", [_rule("16-17.python.one")], [_evidence("EV-900")])
        (b / "evidence" / "EV-900.json").write_text('{"id": "EV-900", "status": "VERIFIED"}\n', encoding="utf-8")
        with self.assertRaises(KnowledgeReleaseError):
            diff_releases(a, b)


if __name__ == "__main__":
    unittest.main()
