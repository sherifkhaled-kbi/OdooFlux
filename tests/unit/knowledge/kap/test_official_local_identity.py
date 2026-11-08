"""Official local clone identity (feature 011 identity fix; source-adapter rules 3, 5, 6; release gate 1).

An official local clone (`official=true`, `local:` url) is trusted only when its `origin` remote matches
`expected_origin` (normalised) and is allow-listed, and the pinned commit exists in that clone. Every failure is
`OFFICIAL_IDENTITY_UNVERIFIED`; nothing is downgraded or substituted. A configured remote is a declared identity, not
cryptographic proof of authenticity (see `sources.official_origin`). Tests use local git repositories only; no network.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.cli.kap_source import _failure_transition
from odooflux.knowledge import validator as v
from odooflux.knowledge.acquisition import sources as s
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.blobstore import SOURCE_ERROR_CODES, BlobStore, SourceError
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj

GIT = shutil.which("git")
ORIGIN = "https://github.com/odoo/odoo"
ALLOW = s.load_allow_list()
SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "snapshot.schema.json").read_text("utf-8"))
IDENTITY = "OFFICIAL_IDENTITY_UNVERIFIED"


def _git(cwd, *args) -> str:
    proc = subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True, timeout=120)
    return proc.stdout


def _make_clone(root: Path, name="clone", content="x = 1\n"):
    """A one-commit git repository with an `origin` remote. Returns (path, commit sha)."""
    repo = root / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "addons").mkdir()
    (repo / "addons" / "sale_demo.py").write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=kap", "-c", "user.email=kap@example.invalid", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD").strip()


def _spec(repo, revision, *, kind="GIT_COMMUNITY", official=True, expected=ORIGIN) -> dict:
    spec = {
        "source_id": "odoo-community-17.0", "kind": kind, "official": official, "url": "local:" + str(repo),
        "licence_access": "PUBLIC_OPEN", "licence_id": "LGPL-3.0", "branch": "17.0", "revision": revision,
        "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }
    if expected is not None:
        spec["expected_origin"] = expected
    return spec


@unittest.skipUnless(GIT, "git is not installed; the identity check needs git")
class OfficialIdentityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo, self.sha = _make_clone(self.base)
        _git(self.repo, "remote", "add", "origin", ORIGIN + ".git")
        self.store_root = self.base / "store"
        self.store = BlobStore(self.store_root)
        self.adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=ALLOW)

    def _objects(self) -> int:
        objects = self.store_root / "objects"
        return sum(1 for p in objects.rglob("*") if p.is_file()) if objects.exists() else 0

    def test_correct_origin_registers_and_snapshots_official(self):
        spec = _spec(self.repo, self.sha)
        self.assertEqual(s.validate_spec(spec, ALLOW), [])
        reg = s.SourceRegistry()
        reg.add(spec)
        self.assertTrue(reg.get("odoo-community-17.0")["official"])
        snap = self.adapter.snapshot(spec, self.store, created_at="2026-11-08T10:00:00Z")
        self.assertEqual(snap["origin_url"], ORIGIN)
        self.assertEqual(snap["revision"], self.sha)
        self.assertRegex(snap["snapshot_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(v.check(snap, SCHEMA), [])

    def test_wrong_origin_fails_identity_and_stores_nothing(self):
        _git(self.repo, "remote", "set-url", "origin", "https://github.com/evil/odoo")
        spec = _spec(self.repo, self.sha)
        probe = self.adapter.probe(spec)
        self.assertEqual((probe["available"], probe["reason_code"]), (False, IDENTITY))
        with self.assertRaises(SourceError) as ctx:
            self.adapter.snapshot(spec, self.store)
        self.assertEqual(ctx.exception.code, IDENTITY)
        self.assertEqual(self._objects(), 0)

    def test_no_origin_remote_fails(self):
        _git(self.repo, "remote", "remove", "origin")
        probe = self.adapter.probe(_spec(self.repo, self.sha))
        self.assertEqual((probe["available"], probe["reason_code"]), (False, IDENTITY))

    def test_identity_failure_maps_to_failed_status(self):
        exc = SourceError(IDENTITY, "odoo-community-17.0", "origin mismatch")
        self.assertEqual(_failure_transition("GIT_COMMUNITY", exc),
                         ("FAILED", f"{IDENTITY}: origin mismatch"))
        reg = s.SourceRegistry()
        reg.add(_spec(self.repo, self.sha))
        reg.transition("odoo-community-17.0", "FAILED", failure_reason=f"{IDENTITY}: origin mismatch")
        rec = reg.get("odoo-community-17.0")
        self.assertEqual((rec["status"], rec.get("origin_url")), ("FAILED", None))
        self.assertIn(IDENTITY, s.FAILURE_CODES)
        self.assertIn(IDENTITY, SOURCE_ERROR_CODES)

    def test_expected_origin_missing_rejected(self):
        problems = s.validate_spec(_spec(self.repo, self.sha, expected=None), ALLOW)
        self.assertEqual([p for p, _ in problems], ["/expected_origin"])
        with self.assertRaises(s.RegistryError):
            s.SourceRegistry().add(_spec(self.repo, self.sha, expected=None))

    def test_expected_origin_not_allowlisted_rejected(self):
        for expected in ("https://github.com/evil/odoo/", "http://github.com/odoo/odoo",
                         "https://github.com/odoo/odoo-evil/", "https://github.com/odoo/enterprise/"):
            with self.subTest(expected=expected):
                problems = s.validate_spec(_spec(self.repo, self.sha, expected=expected), ALLOW)
                self.assertTrue(any(p == "/expected_origin" for p, _ in problems), problems)

    def test_ssh_form_remote_normalises_equal(self):
        for remote in ("git@github.com:odoo/odoo.git", "ssh://git@github.com/odoo/odoo.git",
                       "https://GitHub.com/odoo/odoo/", "https://github.com/odoo/odoo.git/"):
            with self.subTest(remote=remote):
                _git(self.repo, "remote", "set-url", "origin", remote)
                snap = self.adapter.snapshot(_spec(self.repo, self.sha), self.store)
                self.assertEqual(snap["origin_url"], ORIGIN)

    def test_normalisation_rules(self):
        self.assertEqual(s.normalize_origin("git@github.com:odoo/odoo.git"), ORIGIN)
        self.assertEqual(s.normalize_origin("https://GITHUB.com/odoo/odoo///"), ORIGIN)
        for hostile in ("https://github.com/odoo/odoo-evil", "https://user:tok@github.com/odoo/odoo",
                        "http://github.com/odoo/odoo"):
            with self.subTest(hostile=hostile):
                self.assertIsNone(s.official_origin("GIT_COMMUNITY", hostile, ALLOW))

    def test_oca_with_matching_origin_stays_unofficial(self):
        spec = _spec(self.repo, self.sha, kind="OCA", official=True)
        reg = s.SourceRegistry()
        reg.add(spec)
        self.assertFalse(reg.get("odoo-community-17.0")["official"])
        snap = GitLocalAdapter("OCA", allow_list=ALLOW).snapshot(spec, self.store)
        self.assertNotIn("origin_url", snap)

    def test_absent_pinned_commit_is_identity_failure(self):
        probe = self.adapter.probe(_spec(self.repo, "f" * 40))
        self.assertEqual(probe["reason_code"], IDENTITY)

    def test_pinned_commit_from_other_history_fails(self):
        other, other_sha = _make_clone(self.base, name="other", content="y = 2\n")
        self.assertNotEqual(other_sha, self.sha)
        probe = self.adapter.probe(_spec(self.repo, other_sha))
        self.assertEqual(probe["reason_code"], IDENTITY)

    def test_remote_swap_after_registration_fails_next_probe(self):
        spec = _spec(self.repo, self.sha)
        self.assertTrue(self.adapter.probe(spec)["available"])
        _git(self.repo, "remote", "set-url", "origin", "https://github.com/evil/odoo")
        self.assertEqual(self.adapter.probe(spec)["reason_code"], IDENTITY)

    def test_tracked_file_change_detected_by_recomputation(self):
        spec = _spec(self.repo, self.sha)
        snap = self.adapter.snapshot(spec, self.store)
        # the working tree is not the pinned source: an edit there leaves the commit snapshot unchanged
        (self.repo / "addons" / "sale_demo.py").write_text("x = 999\n", encoding="utf-8")
        again = self.adapter.snapshot(spec, self.store)
        self.assertEqual(again["snapshot_digest"], snap["snapshot_digest"])
        # a recorded entry edited after the fact no longer recomputes to the recorded digest
        tampered = json.loads(json.dumps(snap))
        tampered["entries"][0]["sha256"] = "e" * 64
        recomputed = digest_obj({"source_id": tampered["source_id"], "revision": tampered["revision"],
                                 "entries": tampered["entries"]})
        self.assertNotEqual(recomputed, snap["snapshot_digest"])

    def test_origin_not_on_allowlist_fails(self):
        adapter = GitLocalAdapter("GIT_COMMUNITY", allow_list=["https://github.com/odoo/enterprise/"])
        probe = adapter.probe(_spec(self.repo, self.sha))
        self.assertEqual((probe["available"], probe["reason_code"]), (False, IDENTITY))

    def test_expected_origin_absent_is_unverifiable_in_adapter(self):
        probe = self.adapter.probe(_spec(self.repo, self.sha, expected=None))
        self.assertEqual((probe["available"], probe["reason_code"]), (False, IDENTITY))

    def test_https_form_with_git_suffix_registers_official(self):
        spec = _spec(self.repo, self.sha, expected=ORIGIN + ".git")
        self.assertEqual(s.validate_spec(spec, ALLOW), [])
        self.assertEqual(self.adapter.snapshot(spec, self.store)["origin_url"], ORIGIN)

    def test_non_official_local_clone_snapshots_without_origin(self):
        # no identity is required for a non-official clone, even with a foreign origin; it is never marked official
        _git(self.repo, "remote", "set-url", "origin", "https://github.com/evil/odoo")
        spec = _spec(self.repo, self.sha, official=False, expected=None)
        self.assertEqual(s.validate_spec(spec, ALLOW), [])
        reg = s.SourceRegistry()
        reg.add(spec)
        self.assertFalse(reg.get("odoo-community-17.0")["official"])
        snap = self.adapter.snapshot(spec, self.store)
        self.assertNotIn("origin_url", snap)
        self.assertEqual(v.check(snap, SCHEMA), [])

    def test_tampered_blob_fails_verify_on_read(self):
        snap = self.adapter.snapshot(_spec(self.repo, self.sha), self.store)
        digest = snap["entries"][0]["sha256"]
        blob = self.store.path_for(digest)
        blob.write_bytes(b"tampered\n")
        with self.assertRaises(SourceError) as ctx:
            self.store.get(digest)
        self.assertEqual(ctx.exception.code, "SNAPSHOT_CORRUPT")


if __name__ == "__main__":
    unittest.main()
