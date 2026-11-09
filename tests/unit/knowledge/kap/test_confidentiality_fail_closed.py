"""Regression: the confidentiality view fails CLOSED for an installed release whose provenance index is missing,
unreadable, malformed or duplicated. Knowledge with no release (no release.json beside the tree) keeps working.

Layout of an installed release: <release>/release.json, <release>/knowledge/ (the tree), and
<release>/provenance/sources.json (the index). Only temporary directories are used.
"""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux.knowledge.release import confidentiality_view as cv
from odooflux.knowledge.release.model import KnowledgeReleaseError

ENTERPRISE_SOURCE = {"source_id": "odoo-enterprise-12.0", "kind": "GIT_ENTERPRISE", "snapshot_id": "ss-e1e1e1e1e1e1"}
PUBLIC_SOURCE = {"source_id": "odoo-community-12.0", "kind": "GIT_COMMUNITY", "snapshot_id": "ss-c1c1c1c1c1c1"}
EVIDENCE = {
    "EV-001": {"id": "EV-001", "source_id": "odoo-enterprise-12.0", "revision": "r1"},
    "EV-002": {"id": "EV-002", "source_id": "odoo-community-12.0", "revision": "r2"},
}
SECRET_MESSAGE = "'SECRET_VALUE' does not match pattern"


@dataclass(frozen=True)
class _Finding:
    code: str
    file: str
    pointer: str
    message: str
    severity: str = "ERROR"


FINDINGS = [_Finding("E001", "evidence/EV-001.json", "/revision", SECRET_MESSAGE),
            _Finding("E001", "evidence/EV-002.json", "/revision", "public message")]


def _kb(root: Path):
    return SimpleNamespace(root=root, evidence=EVIDENCE,
                           evidence_files={"EV-001": "evidence/EV-001.json", "EV-002": "evidence/EV-002.json"})


class _Release(unittest.TestCase):
    """A temporary installed release. `index` is the raw text written to provenance/sources.json (None: no file)."""

    def make_release(self, index_text=None, manifest=True):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.release = Path(self._tmp.name) / "release-1"
        self.tree = self.release / "knowledge"
        self.tree.mkdir(parents=True)
        if manifest:
            (self.release / "release.json").write_text("{}", encoding="utf-8")
        if index_text is not None:
            (self.release / "provenance").mkdir()
            (self.release / "provenance" / "sources.json").write_text(index_text, encoding="utf-8")
        return self.tree

    def valid_index(self):
        return json.dumps({"sources": [ENTERPRISE_SOURCE, PUBLIC_SOURCE]})


class ReleaseWithUnusableIndexTests(_Release):
    BROKEN = {
        "missing": None,
        "unreadable": "{not json",
        "not_a_list": json.dumps({"sources": "odoo-enterprise-12.0"}),
        "entry_without_source_id": json.dumps({"sources": [{"kind": "GIT_ENTERPRISE"}]}),
        "duplicated": json.dumps({"sources": [ENTERPRISE_SOURCE, {**PUBLIC_SOURCE, "source_id": "odoo-enterprise-12.0"}]}),
    }

    def test_every_broken_index_refuses_the_view_and_withholds_findings(self):
        for label, text in self.BROKEN.items():
            with self.subTest(label=label):
                tree = self.make_release(text)
                kb = _kb(tree)
                with self.assertRaises(KnowledgeReleaseError):
                    cv.view_enterprise_source_ids(tree)
                out = cv.redact_kb_findings(kb, FINDINGS, None)
                self.assertEqual([f.message for f in out], [cv.WITHHELD_MESSAGE] * len(FINDINGS))
                self.assertNotIn("SECRET_VALUE", json.dumps([f.message for f in out]))
                self.assertEqual([(f.code, f.file, f.pointer) for f in out],
                                 [(f.code, f.file, f.pointer) for f in FINDINGS])

    def test_passed_index_does_not_reopen_the_view(self):
        # A caller that passes a usable index for a release whose own index is duplicated still gets the closed view.
        tree = self.make_release(self.BROKEN["duplicated"])
        out = cv.redact_kb_findings(_kb(tree), FINDINGS, {"odoo-community-12.0": PUBLIC_SOURCE})
        self.assertEqual([f.message for f in out], [cv.WITHHELD_MESSAGE] * len(FINDINGS))

    def test_active_release_snapshot_view_is_refused(self):
        for label in ("missing", "unreadable", "duplicated"):
            with self.subTest(label=label):
                tree = self.make_release(self.BROKEN[label])
                handle = SimpleNamespace(builtin=False, root=str(tree.parent), release_id="release-1")
                with mock.patch("odooflux.knowledge.release.resolver.resolve_knowledge", return_value=handle):
                    with self.assertRaises(KnowledgeReleaseError):
                        cv.active_enterprise_snapshot_ids(str(self.release))


class ReleaseWithValidIndexTests(_Release):
    def test_enterprise_evidence_is_withheld_and_public_kept(self):
        tree = self.make_release(self.valid_index())
        self.assertEqual(cv.view_enterprise_source_ids(tree), frozenset({"odoo-enterprise-12.0"}))
        out = cv.redact_kb_findings(_kb(tree), FINDINGS, None)
        self.assertEqual(out[0].message, cv.WITHHELD_MESSAGE)
        self.assertIs(out[1], FINDINGS[1])

    def test_snapshot_view_of_active_release(self):
        tree = self.make_release(self.valid_index())
        handle = SimpleNamespace(builtin=False, root=str(tree.parent), release_id="release-1")
        with mock.patch("odooflux.knowledge.release.resolver.resolve_knowledge", return_value=handle):
            self.assertEqual(cv.active_enterprise_snapshot_ids(str(self.release)), frozenset({"ss-e1e1e1e1e1e1"}))


class KnowledgeWithoutReleaseTests(_Release):
    def test_tree_without_release_manifest_keeps_the_open_behaviour(self):
        tree = self.make_release(None, manifest=False)
        self.assertIsNone(cv.strict_provenance_index(tree))
        self.assertEqual(cv.view_enterprise_source_ids(tree), frozenset())
        findings = list(FINDINGS)
        self.assertIs(cv.redact_kb_findings(_kb(tree), findings, None), findings)

    def test_tree_without_release_keeps_working_with_a_passed_index(self):
        tree = self.make_release(None, manifest=False)
        out = cv.redact_kb_findings(_kb(tree), FINDINGS, {"odoo-enterprise-12.0": ENTERPRISE_SOURCE})
        self.assertEqual(out[0].message, cv.WITHHELD_MESSAGE)

    def test_builtin_snapshot_view_is_empty(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(cv.active_enterprise_snapshot_ids(home), frozenset())


if __name__ == "__main__":
    unittest.main()
