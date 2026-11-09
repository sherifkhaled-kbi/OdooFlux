"""Feature 012 / T04: version discovery and the read-only update check (update/discovery.py).

Fakes only: `ls_remote` is injected, subprocess and sockets are patched to fail, tokens are dummy values, and no test
contacts a network. The shipped catalog is used so the expectations follow the catalog data.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_discovery.py' -t .
"""

import hashlib
import json
import os
import socket
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from odooflux.knowledge.release.model import KnowledgeHandle
from odooflux.knowledge.release.resolver import clear_cache
from odooflux.knowledge.release.store import build_pointer, ensure_layout
from odooflux.knowledge.update import discovery
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update.catalog import load_catalog
from odooflux.knowledge.update.credentials import Token
from odooflux.knowledge.update.model import (FRESHNESS, OVERALL_STATUSES, SOURCE_STATUSES, InstalledState,
                                             transition_label)

CATALOG = load_catalog()
COMMUNITY_REPO = "https://github.com/odoo/odoo.git"
ENTERPRISE_REPO = "https://github.com/odoo/enterprise.git"
TOKEN = "tok-TEST-1234567890"  # dummy
ENV_KEYS = ("ODOOFLUX_OFFLINE", "ODOOFLUX_KB_HOME", "XDG_DATA_HOME")
REPORT_KEYS = {"schema", "statuses", "sources", "new_versions", "affected_transitions", "enterprise_freshness",
               "catalog_digest", "offline", "installed_release"}
SOURCE_KEYS = {"source_id", "edition", "version", "remote_sha", "installed_sha", "status", "detail"}
NEW_VERSION_KEYS = {"edition", "version", "branch", "remote_sha"}


def sha(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def heads_for(edition: str, changed=()) -> dict:
    """Branch heads of one edition's catalog branches. Branches in `changed` get a different sha."""
    return {e.branch: sha(f"{edition}-{e.branch}" + ("-moved" if e.branch in changed else ""))
            for e in CATALOG.entries if e.edition == edition}


def default_remote() -> dict:
    return {COMMUNITY_REPO: heads_for("community"), ENTERPRISE_REPO: heads_for("enterprise")}


def revisions_for(*families, changed_branches=None) -> dict:
    """What an installed release pins for the given families (catalog source ids -> sha at the default remote)."""
    changed_branches = changed_branches or {}
    revs = {}
    for entry in CATALOG.entries:
        if entry.edition in families:
            revs[CATALOG.source_id(entry)] = heads_for(entry.edition)[entry.branch]
    for edition, branches in changed_branches.items():
        for branch in branches:
            revs[f"odoo-{edition}-{branch}"] = sha(f"{edition}-{branch}")
    return revs


class FakeRemote:
    """Injected `ls_remote`. Records every call; a response that is an exception instance is raised."""

    def __init__(self, responses=None):
        self.responses = responses if responses is not None else default_remote()
        self.calls = []

    def __call__(self, repository, *, offline=False, transport_url=None, timeout=None, runner=None, credentials=None):
        self.calls.append((repository, credentials))
        outcome = self.responses[repository]
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)


class NoNetwork(unittest.TestCase):
    """Every test in this module: any attempt to start a process or open a socket fails the test."""

    def setUp(self):
        self._patches = [
            mock.patch("subprocess.Popen", side_effect=AssertionError("no subprocess in discovery tests")),
            mock.patch.object(socket, "socket", side_effect=AssertionError("no socket in discovery tests")),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        clear_cache()
        self.addCleanup(clear_cache)


class ReadInstalledStateTests(NoNetwork):
    def test_no_active_pointer_is_builtin_knowledge(self):
        installed = discovery.read_installed_state(self.root / "empty-kb")
        self.assertTrue(installed.valid)
        self.assertIsNone(installed.release_id)
        self.assertEqual(installed.revisions, {})

    def test_revisions_come_from_release_json_sources(self):
        release = self.root / "release"
        release.mkdir()
        sources = [{"source_id": "odoo-community-17.0", "revision": "a" * 40},
                   {"source_id": "odoo-enterprise-17.0", "revision": "b" * 40}]
        (release / "release.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")
        handle = KnowledgeHandle(root=release, release_id="kr-0123456789ab", digest="d" * 64, builtin=False,
                                 completeness="COMPLETE")
        with mock.patch.object(discovery, "resolve_knowledge", return_value=handle):
            installed = discovery.read_installed_state(self.root)
        self.assertTrue(installed.valid)
        self.assertEqual(installed.release_id, "kr-0123456789ab")
        self.assertEqual(installed.digest, "d" * 64)
        self.assertEqual(installed.revisions, {"odoo-community-17.0": "a" * 40, "odoo-enterprise-17.0": "b" * 40})

    def test_malformed_sources_are_invalid_never_empty(self):
        bad_documents = {
            "no sources list": {},
            "sources not a list": {"sources": "odoo-community-17.0"},
            "entry not an object": {"sources": ["odoo-community-17.0"]},
            "revision too short": {"sources": [{"source_id": "odoo-community-17.0", "revision": "abc"}]},
            "revision upper case": {"sources": [{"source_id": "odoo-community-17.0", "revision": "A" * 40}]},
            "revision with newline": {"sources": [{"source_id": "odoo-community-17.0", "revision": "a" * 40 + "\n"}]},
            "revision not text": {"sources": [{"source_id": "odoo-community-17.0", "revision": 7}]},
            "duplicate source": {"sources": [{"source_id": "odoo-community-17.0", "revision": "a" * 40},
                                             {"source_id": "odoo-community-17.0", "revision": "b" * 40}]},
        }
        handle = KnowledgeHandle(root=self.root, release_id="kr-0123456789ab", digest="d" * 64, builtin=False,
                                 completeness="COMPLETE")
        for label, document in bad_documents.items():
            with self.subTest(label):
                (self.root / "release.json").write_text(json.dumps(document), encoding="utf-8")
                with mock.patch.object(discovery, "resolve_knowledge", return_value=handle):
                    installed = discovery.read_installed_state(self.root)
                self.assertFalse(installed.valid)
                self.assertTrue(installed.problem)
                self.assertEqual(installed.revisions, {})

    def test_unreadable_release_json_is_invalid(self):
        (self.root / "release.json").write_text("{not json", encoding="utf-8")
        handle = KnowledgeHandle(root=self.root, release_id="kr-0123456789ab", digest="d" * 64, builtin=False,
                                 completeness=None)
        with mock.patch.object(discovery, "resolve_knowledge", return_value=handle):
            installed = discovery.read_installed_state(self.root)
        self.assertFalse(installed.valid)

    def test_corrupt_active_pointer_is_invalid(self):
        kb = self.root / "kb"
        kb.mkdir()
        (kb / "active.json").write_text("{corrupt", encoding="utf-8")
        installed = discovery.read_installed_state(kb)
        self.assertFalse(installed.valid)
        self.assertIsNone(installed.release_id)
        self.assertTrue(installed.problem)

    def test_active_pointer_to_missing_release_is_invalid(self):
        kb = self.root / "kb"
        ensure_layout(kb)
        pointer = build_pointer(None, "kr-000000000000", "0" * 64, "2026-11-09T00:00:00Z")
        (kb / "active.json").write_text(json.dumps(pointer), encoding="utf-8")
        installed = discovery.read_installed_state(kb)
        self.assertFalse(installed.valid)
        self.assertTrue(installed.problem)

    def _read_with_sources(self, sources):
        (self.root / "release.json").write_text(json.dumps({"sources": sources}), encoding="utf-8")
        handle = KnowledgeHandle(root=self.root, release_id="kr-0123456789ab", digest="d" * 64, builtin=False,
                                 completeness="COMPLETE")
        with mock.patch.object(discovery, "resolve_knowledge", return_value=handle):
            return discovery.read_installed_state(self.root)

    def test_snapshot_digests_come_from_release_json(self):
        installed = self._read_with_sources([
            {"source_id": "odoo-community-17.0", "revision": "a" * 40, "snapshot_digest": "e" * 64},
            {"source_id": "odoo-enterprise-17.0", "revision": "b" * 40, "snapshot_digest": "f" * 64}])
        self.assertTrue(installed.valid)
        self.assertEqual(installed.snapshot_digests,
                         {"odoo-community-17.0": "e" * 64, "odoo-enterprise-17.0": "f" * 64})

    def test_source_without_a_snapshot_digest_key_gets_none_and_stays_valid(self):
        installed = self._read_with_sources([
            {"source_id": "odoo-community-17.0", "revision": "a" * 40, "snapshot_digest": "e" * 64},
            {"source_id": "odoo-enterprise-17.0", "revision": "b" * 40}])
        self.assertTrue(installed.valid)
        self.assertEqual(installed.snapshot_digests, {"odoo-community-17.0": "e" * 64})
        self.assertEqual(installed.revisions, {"odoo-community-17.0": "a" * 40, "odoo-enterprise-17.0": "b" * 40})

    def test_malformed_snapshot_digest_makes_the_state_invalid_never_empty(self):
        cases = {"too short": "e" * 63, "upper case": "E" * 64, "trailing newline": "e" * 64 + "\n",
                 "null": None, "integer": 7, "list": ["e" * 64]}
        for label, value in cases.items():
            with self.subTest(label):
                installed = self._read_with_sources(
                    [{"source_id": "odoo-community-17.0", "revision": "a" * 40, "snapshot_digest": value}])
                self.assertFalse(installed.valid)
                self.assertTrue(installed.problem)
                self.assertEqual(installed.snapshot_digests, {})
                self.assertEqual(installed.revisions, {})

    def test_default_installed_state_has_no_snapshot_digests(self):
        self.assertEqual(InstalledState().snapshot_digests, {})
        self.assertEqual(discovery.read_installed_state(self.root / "empty-kb").snapshot_digests, {})


class StatusMatrixTests(NoNetwork):
    def run_check(self, installed, remote=None, *, token=None, offline=False, credential_problem=None):
        fake = FakeRemote(remote)
        report = discovery.check(CATALOG, installed, offline=offline, token=token, ls_remote=fake,
                                 credential_problem=credential_problem)
        return report, fake

    def test_fresh_install_without_release_counts_as_update(self):
        report, fake = self.run_check(InstalledState())
        self.assertIn("SOURCE_REVISION_AVAILABLE", report.statuses)
        self.assertIn("KNOWLEDGE_UPDATE_AVAILABLE", report.statuses)
        self.assertNotIn("NO_UPDATE", report.statuses)
        self.assertIsNone(report.installed_release)
        self.assertEqual(report.enterprise_freshness, "NOT_INSTALLED")
        self.assertEqual(report.affected_transitions,
                         tuple(transition_label(a, b) for a, b in CATALOG.pairs("community")))
        for source in report.sources:
            self.assertIsNone(source.installed_sha)
            expected = "SKIPPED_NO_CREDENTIALS" if source.edition == "enterprise" else "OK"
            self.assertEqual(source.status, expected, source.source_id)
        self.assertEqual(fake.calls, [(COMMUNITY_REPO, None)])

    def test_unchanged_community_is_no_update(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        report, fake = self.run_check(installed)
        self.assertEqual(report.statuses, ("NO_UPDATE",))
        self.assertEqual(report.new_versions, ())
        self.assertEqual(report.affected_transitions, ())
        self.assertEqual(report.enterprise_freshness, "NOT_INSTALLED")
        self.assertEqual(len(fake.calls), 1)

    def test_changed_community_source_affects_adjacent_transitions(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        remote = default_remote()
        remote[COMMUNITY_REPO] = heads_for("community", changed=("17.0",))
        report, _ = self.run_check(installed, remote)
        self.assertIn("SOURCE_REVISION_AVAILABLE", report.statuses)
        self.assertIn("KNOWLEDGE_UPDATE_AVAILABLE", report.statuses)
        self.assertNotIn("NO_UPDATE", report.statuses)
        changed = [s.version for s in report.sources if s.changed()]
        self.assertEqual(changed, ["17.0"])
        self.assertEqual(report.affected_transitions, ("16-17", "17-18"))

    def test_changed_enterprise_source_is_outdated_with_token(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        remote = default_remote()
        remote[ENTERPRISE_REPO] = heads_for("enterprise", changed=("17.0",))
        token = Token(TOKEN)
        report, fake = self.run_check(installed, remote, token=token)
        self.assertEqual(report.enterprise_freshness, "OUTDATED")
        self.assertIn("SOURCE_REVISION_AVAILABLE", report.statuses)
        self.assertEqual(report.affected_transitions, ("16-17", "17-18"))
        self.assertEqual([c[0] for c in fake.calls], [COMMUNITY_REPO, ENTERPRISE_REPO])
        self.assertIs(fake.calls[1][1], token)
        self.assertIsNone(fake.calls[0][1])

    def test_enterprise_equal_with_token_is_fresh(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        report, _ = self.run_check(installed, token=Token(TOKEN))
        self.assertEqual(report.enterprise_freshness, "FRESH")
        self.assertEqual(report.statuses, ("NO_UPDATE",))

    def test_installed_enterprise_without_token_is_unknown_and_blocks_no_update(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        report, fake = self.run_check(installed)
        self.assertEqual(report.enterprise_freshness, "UNKNOWN")
        self.assertEqual(report.statuses, ())  # community equal, but Enterprise unverified: no NO_UPDATE claim
        self.assertNotIn("CHECK_UNAVAILABLE", report.statuses)
        self.assertEqual([c[0] for c in fake.calls], [COMMUNITY_REPO])
        enterprise = [s for s in report.sources if s.edition == "enterprise"]
        self.assertTrue(all(s.status == "SKIPPED_NO_CREDENTIALS" for s in enterprise))

    def test_skipped_enterprise_never_causes_check_unavailable(self):
        report, _ = self.run_check(InstalledState(), token=None)
        self.assertNotIn("CHECK_UNAVAILABLE", report.statuses)

    def test_new_version_is_reported_not_supported(self):
        latest = CATALOG.versions("community")[-1]
        remote = default_remote()
        remote[COMMUNITY_REPO] = dict(heads_for("community"), **{"20.0": sha("new-20"), "saas-17.0": sha("s"),
                                                                 "master": sha("m")})
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        report, _ = self.run_check(installed, remote)
        self.assertIn("NEW_VERSION_DISCOVERED", report.statuses)
        self.assertIn("TRANSITION_NOT_YET_SUPPORTED", report.statuses)
        self.assertNotIn("NO_UPDATE", report.statuses)
        self.assertEqual([(n.edition, n.version, n.branch) for n in report.new_versions],
                         [("community", "20.0", "20.0")])
        self.assertEqual(report.new_versions[0].remote_sha, sha("new-20"))
        self.assertEqual(report.affected_transitions, (transition_label(latest, "20.0"),))
        listed = {s.version for s in report.sources} | {n.version for n in report.new_versions}
        self.assertNotIn("saas-17.0", listed)
        self.assertNotIn("master", listed)

    def test_auth_failed_is_distinct_from_unavailable(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        cases = {
            "AUTH_FAILED": "AUTH_FAILED",
            "UNAVAILABLE": "UNAVAILABLE",
            "IO_ERROR": "UNAVAILABLE",
            "REVISION_UNAVAILABLE": "UNAVAILABLE",
            "AUTH_REQUIRED": "SKIPPED_NO_CREDENTIALS",
        }
        for code, expected in cases.items():
            with self.subTest(code):
                remote = default_remote()
                remote[ENTERPRISE_REPO] = rg.RemoteGitError(code, None, f"refused for {TOKEN}")
                report, _ = self.run_check(installed, remote, token=Token(TOKEN))
                enterprise = {s.status for s in report.sources if s.edition == "enterprise"}
                self.assertEqual(enterprise, {expected})
                self.assertNotIn(TOKEN, json.dumps(report.to_dict()))
                # Community was read OK and nothing differs; Enterprise is not installed, so it does not block.
                self.assertEqual(report.statuses, ("NO_UPDATE",))

    def test_auth_failed_enterprise_has_no_freshness_claim(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        remote = default_remote()
        remote[ENTERPRISE_REPO] = rg.RemoteGitError("AUTH_FAILED", None, "rejected")
        report, _ = self.run_check(installed, remote, token=Token(TOKEN))
        self.assertEqual(report.enterprise_freshness, "UNKNOWN")

    def test_community_unavailable_is_check_unavailable(self):
        remote = default_remote()
        remote[COMMUNITY_REPO] = rg.RemoteGitError("UNAVAILABLE", None, "could not resolve host")
        report, _ = self.run_check(InstalledState(), remote)
        self.assertEqual(report.statuses, ("CHECK_UNAVAILABLE",))
        self.assertTrue(all(s.status == "UNAVAILABLE" for s in report.sources if s.edition == "community"))
        self.assertTrue(all(s.remote_sha is None for s in report.sources))

    def test_missing_branch_is_unavailable_for_that_source_only(self):
        remote = default_remote()
        remote[COMMUNITY_REPO] = {k: v for k, v in heads_for("community").items() if k != "17.0"}
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        report, _ = self.run_check(installed, remote)
        by_version = {s.version: s for s in report.sources if s.edition == "community"}
        self.assertEqual(by_version["17.0"].status, "UNAVAILABLE")
        self.assertEqual(by_version["17.0"].detail, "branch not found on the remote")
        self.assertEqual(by_version["16.0"].status, "OK")
        self.assertNotIn("NO_UPDATE", report.statuses)

    def test_offline_argument_makes_zero_calls(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        report, fake = self.run_check(installed, token=Token(TOKEN), offline=True)
        self.assertEqual(fake.calls, [])
        self.assertEqual(report.statuses, ("CHECK_UNAVAILABLE",))
        self.assertTrue(report.offline)
        self.assertTrue(all(s.status == "SKIPPED_OFFLINE" for s in report.sources))
        self.assertEqual(report.enterprise_freshness, "UNKNOWN")
        self.assertNotIn("NO_UPDATE", report.statuses)

    def test_offline_environment_makes_zero_calls(self):
        os.environ["ODOOFLUX_OFFLINE"] = "1"
        fake = FakeRemote()
        report = discovery.check(CATALOG, InstalledState(), ls_remote=fake, token=Token(TOKEN))
        self.assertEqual(fake.calls, [])
        self.assertTrue(report.offline)
        self.assertEqual(report.statuses, ("CHECK_UNAVAILABLE",))

    def test_offline_default_remote_never_spawns_git(self):
        with mock.patch.object(rg, "ls_remote_heads", side_effect=AssertionError("must not be called")):
            report = discovery.check(CATALOG, InstalledState(), offline=True)
        self.assertEqual(report.statuses, ("CHECK_UNAVAILABLE",))

    def test_invalid_local_state_makes_no_network_call(self):
        fake = FakeRemote()
        report = discovery.check(CATALOG, InstalledState(valid=False, problem="broken"), ls_remote=fake,
                                 token=Token(TOKEN))
        self.assertEqual(fake.calls, [])
        self.assertEqual(report.statuses, ("LOCAL_STATE_INVALID",))
        self.assertEqual(report.sources, ())
        self.assertEqual(report.enterprise_freshness, "UNKNOWN")

    def test_exactly_one_call_per_repository(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community", "enterprise"))
        report, fake = self.run_check(installed, token=Token(TOKEN))
        counts = Counter(repository for repository, _ in fake.calls)
        self.assertEqual(counts, Counter({COMMUNITY_REPO: 1, ENTERPRISE_REPO: 1}))
        self.assertGreater(len([s for s in report.sources if s.status == "OK"]), 2)

    def test_credential_problem_is_enterprise_only_and_makes_no_call(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        report, fake = self.run_check(installed, credential_problem="TOKEN_FILE_PERMISSIONS")
        self.assertEqual([c[0] for c in fake.calls], [COMMUNITY_REPO])
        enterprise = {s.status for s in report.sources if s.edition == "enterprise"}
        self.assertEqual(enterprise, {"AUTH_FAILED"})
        self.assertEqual(report.statuses, ("NO_UPDATE",))

    def test_report_schema_and_field_sets(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        remote = default_remote()
        remote[COMMUNITY_REPO] = dict(heads_for("community", changed=("18.0",)), **{"20.0": sha("n")})
        report, _ = self.run_check(installed, remote)
        payload = report.to_dict()
        self.assertEqual(set(payload), REPORT_KEYS)
        self.assertEqual(payload["schema"], discovery.SCHEMA)
        self.assertEqual(payload["schema"], "odooflux.knowledge-check/1")
        self.assertTrue(payload["sources"])
        for row in payload["sources"]:
            self.assertEqual(set(row), SOURCE_KEYS)
            self.assertIn(row["status"], SOURCE_STATUSES)
        for row in payload["new_versions"]:
            self.assertEqual(set(row), NEW_VERSION_KEYS)
        for status in payload["statuses"]:
            self.assertIn(status, OVERALL_STATUSES)
        self.assertIn(payload["enterprise_freshness"], FRESHNESS)
        self.assertEqual(payload["catalog_digest"], CATALOG.digest)

    def test_check_does_not_mutate_inputs(self):
        installed = InstalledState(release_id="kr-0123456789ab", digest="d" * 64,
                                   revisions=revisions_for("community"))
        before = dict(installed.revisions)
        self.run_check(installed, token=Token(TOKEN))
        self.assertEqual(installed.revisions, before)


if __name__ == "__main__":
    unittest.main()
