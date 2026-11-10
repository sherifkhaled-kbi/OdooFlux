"""RC hardening: the central confidentiality policy for symbol names, rule text and Enterprise source metadata."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from odooflux.knowledge.release import confidentiality_view as cv

REV = "ab" * 20
ENT = "odoo-enterprise-17.0"
COM = "odoo-community-17.0"
SNAP = "ss-" + "e1" * 6


def make_home(root: Path, entries, *, name="rel1", manifest=True):
    rel = root / "releases" / name
    (rel / "knowledge").mkdir(parents=True)
    (rel / "provenance").mkdir()
    (rel / "provenance" / "sources.json").write_text(json.dumps({"sources": entries}), encoding="utf-8")
    if manifest:
        (rel / "release.json").write_text("{}", encoding="utf-8")
    return rel


def entry(sid, kind, rev=REV, snap=SNAP):
    return {"source_id": sid, "kind": kind, "revision": rev, "snapshot_id": snap}


class ScrubOutputTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.home = Path(self._t.name)

    def test_enterprise_id_revision_and_snapshot_are_withheld_public_untouched(self):
        make_home(self.home, [entry(ENT, "GIT_ENTERPRISE"), entry(COM, "GIT_COMMUNITY", rev="cd" * 20, snap="ss-c")])
        out = cv.scrub_enterprise_output(f"{ENT}={REV} {COM}={'cd' * 20} {SNAP}", self.home)
        self.assertNotIn(ENT, out)
        self.assertNotIn(REV, out)
        self.assertNotIn(SNAP, out)
        self.assertIn(COM, out)
        self.assertIn("cd" * 20, out)

    def test_unusable_provenance_withholds_every_commit_like_value(self):
        make_home(self.home, [{"kind": "GIT_COMMUNITY"}])  # entry without a source_id
        out = cv.scrub_enterprise_output(f"x={'cd' * 20}", self.home)
        self.assertNotIn("cd" * 20, out)

    def test_extra_tokens_cover_remote_revisions_not_yet_in_any_index(self):
        remote = "ef" * 20
        out = cv.scrub_enterprise_output(f"remote {remote}", self.home, {remote})
        self.assertNotIn(remote, out)

    def test_no_releases_is_unchanged(self):
        self.assertEqual(cv.scrub_enterprise_output("a b", self.home), "a b")


class RuleRowTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.rel = make_home(Path(self._t.name), [entry(ENT, "GIT_ENTERPRISE"), entry(COM, "GIT_COMMUNITY")])
        self.kb = SimpleNamespace(root=self.rel / "knowledge",
                                  evidence={"EV-1": {"id": "EV-1", "source_id": ENT},
                                            "EV-2": {"id": "EV-2", "source_id": COM}})

    def test_only_enterprise_derived_rows_lose_text(self):
        rows = [{"id": "r1", "evidence": ["EV-1"], "message": "secret_symbol", "suggestion": "use secret_new"},
                {"id": "r2", "evidence": ["EV-2"], "message": "public text", "suggestion": "s"}]
        out = cv.redact_rule_rows(self.kb, rows)
        self.assertEqual(out[0]["message"], cv.WITHHELD_MESSAGE)
        self.assertNotIn("secret", json.dumps(out[0]))
        self.assertEqual(out[1], rows[1])
        self.assertEqual(rows[0]["message"], "secret_symbol")  # input untouched

    def test_unusable_index_withholds_all(self):
        (self.rel / "provenance" / "sources.json").write_text("not json", encoding="utf-8")
        out = cv.redact_rule_rows(self.kb, [{"id": "r2", "evidence": ["EV-2"], "message": "m", "suggestion": "s"}])
        self.assertEqual(out[0]["message"], cv.WITHHELD_MESSAGE)


class SymbolTests(unittest.TestCase):
    def test_enterprise_change_symbol_is_withheld_but_stable(self):
        rec = {"change_id": "c", "subject_key": "sale.order::field::secret_name", "detail": {"a": 1},
               "locations": [{"snapshot_id": SNAP, "path": "p", "line": 1, "sha256": "a"}]}
        a = cv.redact_change_record(rec, frozenset({SNAP}))
        self.assertNotIn("secret_name", json.dumps(a))
        self.assertEqual(a["subject_key"], cv.redact_change_record(rec, frozenset({SNAP}))["subject_key"])
        public = {**rec, "locations": [{"snapshot_id": "ss-pub", "path": "p", "line": 1, "sha256": "a"}]}
        self.assertIs(cv.redact_change_record(public, frozenset({SNAP})), public)


if __name__ == "__main__":
    unittest.main()
