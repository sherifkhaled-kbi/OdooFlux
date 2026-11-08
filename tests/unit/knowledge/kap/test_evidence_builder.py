"""TST-011-057 (REQ-KAP-015, REQ-KAP-008): the evidence builder records locations with a content hash, status
DOCUMENTED_NOT_TESTED, origin KAP_DETERMINISTIC, the official flag, and never reuses an evidence id.

Contract candidate-rule-generation. Fixtures are built in memory; nothing under the repository tree is written.
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge import validator as v
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.release.canonical import canonical_bytes

SNAP = "ss-0123456789ab"
CHANGE_ID = "CH-0123456789abcdef"
RULE_ID = "17-18.python_orm.cand-0a1b2c3d"
SCHEMA = eb.KNOWLEDGE_ROOT / "schemas" / "evidence.schema.json"


def _source(**over):
    base = {"source_id": "odoo-community-17.0", "official": True, "url": "https://github.com/odoo/odoo/tree/" + "a" * 40,
            "repository": "odoo/odoo", "revision": "a" * 40, "branch": "17.0"}
    base.update(over)
    return base


def _change(**over):
    base = {"change_id": CHANGE_ID, "step": "17-18", "domain": "python_orm", "kind": "method",
            "subject_key": "res.partner::method::foo", "class": "REMOVED", "confirmed": False, "detail": {},
            "locations": [{"snapshot_id": SNAP, "path": "addons/base/models/res_partner.py", "line": 12,
                           "sha256": "ab" * 32}],
            "disposition": "UNRESOLVED", "proposed_by": "DETERMINISTIC"}
    base.update(over)
    return base


def _build(change=None, source=None, evidence_id="EV-548", **over):
    kwargs = {"evidence_id": evidence_id, "rule_ids": [RULE_ID], "source": source or _source(),
              "risk": "MEDIUM", "detection_method": "KAP deterministic diff classification",
              "proposed_transformation": "review the candidate", "checked_on": "2026-11-08"}
    kwargs.update(over)
    return eb.build_evidence(change or _change(), **kwargs)


class EvidenceBuilderTests(unittest.TestCase):
    def test_content_hash_present(self):
        record = _build()
        self.assertEqual(v.check(record, json.loads(SCHEMA.read_text(encoding="utf-8"))), [])
        for loc in record["locations"]:
            self.assertEqual(loc["content_sha256"], "ab" * 32)
            self.assertEqual(loc["snapshot_ref"], SNAP)
            self.assertEqual(loc["revision"], "a" * 40)

    def test_status_origin_and_identity(self):
        record = _build()
        self.assertEqual(record["status"], "DOCUMENTED_NOT_TESTED")
        self.assertEqual(record["origin"], "KAP_DETERMINISTIC")
        self.assertEqual(record["change_ids"], [CHANGE_ID])
        self.assertEqual(record["source_id"], "odoo-community-17.0")
        self.assertEqual(record["id"], "EV-548")
        self.assertEqual(record["source_applicability"], {"from": "17.0", "to": "18.0"})

    def test_ids_never_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            evidence.mkdir()
            (evidence / "EV-547.json").write_text("{}", encoding="utf-8")
            # EV-600 is referenced by a ledger disposition but its file is gone: still counts as used.
            referenced = [{"disposition_data": {"evidence_ids": ["EV-600"], "rule_ids": []}}]
            used = eb.used_evidence_ids(Path(tmp), referenced)
            self.assertIn("EV-547", used)
            self.assertIn("EV-600", used)
            self.assertEqual(eb.next_evidence_id(used), "EV-601")
        self.assertEqual(eb.next_evidence_id([]), "EV-001")

    def test_unofficial_flagged(self):
        record = _build(source=_source(official=False, source_id="oca-web-17.0"))
        self.assertIs(record["official"], False)
        self.assertEqual(record["source_id"], "oca-web-17.0")
        self.assertEqual(v.check(record, json.loads(SCHEMA.read_text(encoding="utf-8"))), [])

    def test_official_flag_true_for_official_source(self):
        self.assertIs(_build()["official"], True)

    def test_no_locations_refused(self):
        with self.assertRaises(eb.EvidenceError):
            _build(change=_change(locations=[]))

    def test_unknown_domain_refused(self):
        with self.assertRaises(eb.EvidenceError):
            _build(change=_change(domain="not_a_domain"))

    def test_deterministic_bytes(self):
        self.assertEqual(canonical_bytes(_build()), canonical_bytes(_build()))


LOCAL_PATH = "/home/maint/clones/odoo"


def _local(**over):
    """A local-clone source spec as `knowledge candidates generate --source` receives it (no repository field)."""
    base = {"source_id": "odoo-community-17.0", "official": True, "url": "local:" + LOCAL_PATH,
            "kind": "GIT_COMMUNITY", "expected_origin": "https://github.com/odoo/odoo", "revision": "a" * 40,
            "branch": "17.0"}
    base.update(over)
    return base


class SourceIdentityTests(unittest.TestCase):
    def test_slug_from_explicit_repository(self):
        src = eb.resolve_source(_local(repository="odoo/odoo", expected_origin=None))
        self.assertEqual(src["repository"], "odoo/odoo")

    def test_explicit_repository_wins_over_expected_origin(self):
        src = eb.resolve_source(_local(repository="maintainer/odoo-fork"))
        self.assertEqual(src["repository"], "maintainer/odoo-fork")

    def test_slug_from_expected_origin_https(self):
        self.assertEqual(eb.resolve_source(_local())["repository"], "odoo/odoo")

    def test_slug_from_expected_origin_ssh_form(self):
        src = eb.resolve_source(_local(expected_origin="git@github.com:odoo/odoo.git"))
        self.assertEqual(src["repository"], "odoo/odoo")

    def test_slug_from_expected_origin_trailing_slash_and_case(self):
        src = eb.resolve_source(_local(expected_origin="https://GitHub.com/Odoo/Odoo.git/"))
        self.assertEqual(src["repository"], "odoo/odoo")

    def test_no_slug_refused_and_names_both_ways(self):
        with self.assertRaises(eb.SourceIdentityError) as ctx:
            eb.resolve_source(_local(expected_origin=None))
        self.assertIn("repository", str(ctx.exception))
        self.assertIn("expected_origin", str(ctx.exception))

    def test_no_slug_never_falls_back_to_url(self):
        with self.assertRaises(eb.SourceIdentityError):
            eb.resolve_source(_local(expected_origin=None, url="local:/tmp/x"))

    def test_invalid_explicit_repository_refused(self):
        for bad in ("local:/home/maint/clones/odoo", "odoo", "Odoo/odoo", "odoo/odoo/extra"):
            with self.subTest(repository=bad), self.assertRaises(eb.SourceIdentityError):
                eb.resolve_source(_local(repository=bad))

    def test_expected_origin_with_extra_path_segment_refused(self):
        with self.assertRaises(eb.SourceIdentityError):
            eb.resolve_source(_local(expected_origin="https://gitlab.com/group/sub/repo"))

    def test_evidence_url_for_local_source_is_origin_tree_url(self):
        src = eb.resolve_source(_local())
        self.assertEqual(src["url"], "https://github.com/odoo/odoo/tree/" + "a" * 40)

    def test_evidence_url_for_local_source_without_origin_is_path_free_token(self):
        src = eb.resolve_source(_local(expected_origin=None, repository="odoo/odoo"))
        self.assertEqual(src["url"], "source:odoo-community-17.0@" + "a" * 40)

    def test_remote_url_kept_as_is(self):
        url = "https://github.com/odoo/odoo/tree/" + "a" * 40
        self.assertEqual(eb.resolve_source(_local(url=url))["url"], url)

    def test_resolve_source_is_pure(self):
        spec = _local()
        before = dict(spec)
        eb.resolve_source(spec)
        self.assertEqual(spec, before)


class LocalSourceEvidenceTests(unittest.TestCase):
    def _record(self, source=None):
        return _build(source=eb.resolve_source(source or _local()))

    def test_evidence_validates_and_has_no_local_path(self):
        record = self._record()
        self.assertEqual(v.check(record, json.loads(SCHEMA.read_text(encoding="utf-8"))), [])
        self.assertEqual(record["repository"], "odoo/odoo")
        text = json.dumps(record)
        self.assertNotIn("local:", text)
        self.assertNotIn(LOCAL_PATH, text)
        self.assertNotIn("/home/", text)

    def test_evidence_validates_without_expected_origin(self):
        record = self._record(_local(expected_origin=None, repository="maintainer/odoo-fork", official=False))
        self.assertEqual(v.check(record, json.loads(SCHEMA.read_text(encoding="utf-8"))), [])
        self.assertTrue(record["url"].startswith("source:"))
        self.assertNotIn(LOCAL_PATH, json.dumps(record))
        self.assertIs(record["official"], False)

    def test_build_evidence_applies_resolution_itself(self):
        # Callers that pass the raw spec (no resolved repository) get the same identity as the CLI.
        record = _build(source=_local())
        self.assertEqual(record["repository"], "odoo/odoo")
        self.assertEqual(record["url"], "https://github.com/odoo/odoo/tree/" + "a" * 40)

    def test_build_evidence_refuses_missing_identity(self):
        with self.assertRaises(eb.SourceIdentityError):
            _build(source=_local(expected_origin=None))

    def test_deterministic_bytes_for_local_source(self):
        self.assertEqual(canonical_bytes(self._record()), canonical_bytes(self._record()))


if __name__ == "__main__":
    unittest.main()
