"""Feature 012 update acquisition (acquire.py, plan Addendum B4 and C1): ACQUIRE / CARRY_FORWARD / SKIP handling, credential
scope, offline gate, blocking rules, status mapping, scrubbing, carried sources, spec shape against the real allow-list
and SourceRegistry, and determinism.

Local bare repositories are the only transport (the `transport_for` seam). Fetches are recorded by a fake `fetch`
unless a test needs the real `remote_git.fetch_commit`. No test contacts the network. Tokens are dummy values.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_acquire.py' -t .
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.acquisition import sources as registry
from odooflux.knowledge.update import acquire as acq
from odooflux.knowledge.update import catalog as cat
from odooflux.knowledge.update import planner as pl
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update.credentials import Token
from odooflux.knowledge.update.model import CheckReport, InstalledState, SourceCheck
from tests.unit.knowledge.update.test_remote_git import _git, _key, _make_commit

CATALOG = cat.load_catalog()
ALLOW = registry.load_allow_list()
TOKEN = "tok-TEST-1234567890"  # dummy value
NO_SHA = "1" * 40  # well-formed, present in no repository
REPOSITORY = re.compile(r"[a-z0-9-]+/[a-z0-9._-]+")
BUILD_CONFIG = {"profile": "default"}


def sha(tag: str, version: str) -> str:
    return hashlib.sha1(f"{tag}:{version}".encode("utf-8")).hexdigest()


def entry(edition: str, version: str):
    return CATALOG.entry_for(version, edition)


def sid(edition: str, version: str) -> str:
    return CATALOG.source_id(entry(edition, version))


def declared_spec(e, revision: str, required: bool) -> dict:
    """A DECLARED record shaped like planner._declared_spec (the planner's own output is used where a test needs it)."""
    return {
        "source_id": CATALOG.source_id(e), "kind": e.kind, "official": True, "url": e.expected_origin + "/",
        "licence_access": e.licence_access, "licence_id": e.licence_id, "branch": e.branch, "revision": revision,
        "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None, "checksum": None, "status": "DECLARED", "failure_reason": None,
        "required": required, "expected_origin": e.expected_origin,
    }


def planned(e, action: str, target, required: bool, spec=None, installed=None) -> pl.PlannedSource:
    return pl.PlannedSource(CATALOG.source_id(e), e.edition, e.version, e.repository, e.branch, target, action,
                            required, dict(spec or {}), e.redistribution, installed)


def make_plan(sources) -> pl.UpdatePlan:
    sources = list(sources)
    return pl.UpdatePlan("BUILD", None, [], sources, [], [s.source_id for s in sources if s.action == "CARRY_FORWARD"],
                         None, {}, [])


def planner_plan(*, token=False, ent_ok=False, installed=None, release_id=None):
    """A real plan from the shipped catalog. Community remotes are sha('c', v). Enterprise remotes are sha('e', v) when
    `ent_ok`, otherwise the Enterprise check is SKIPPED_NO_CREDENTIALS."""
    rows = []
    for e in CATALOG.entries:
        if e.edition == "community":
            rows.append(SourceCheck(CATALOG.source_id(e), "community", e.version, sha("c", e.version), None, "OK"))
        elif ent_ok:
            rows.append(SourceCheck(CATALOG.source_id(e), "enterprise", e.version, sha("e", e.version), None, "OK"))
        else:
            rows.append(SourceCheck(CATALOG.source_id(e), "enterprise", e.version, None, None,
                                    "SKIPPED_NO_CREDENTIALS"))
    check = CheckReport("odooflux.knowledge-check/1", ("KNOWLEDGE_UPDATE_AVAILABLE",), tuple(rows), (), (), "FRESH",
                        CATALOG.digest, False, None)
    state = InstalledState(release_id=release_id, digest=None, revisions=dict(installed or {}), valid=True)
    return pl.plan_update(CATALOG, check, state, token_available=token, extractor_version="1",
                          rule_schema_version="1", build_config=BUILD_CONFIG)


class _Fetch:
    """A recording fake for the `fetch` seam. It creates `<cache>/<key>/<sha>` like fetch_commit does. `errors` maps a
    normalised origin to an exception to raise. `outside` makes every call return that path instead."""

    def __init__(self, *, errors=None, outside=None):
        self.calls = []
        self.errors = dict(errors or {})
        self.outside = outside

    def __call__(self, identity_url, *, branch, expected_sha, cache_dir, offline, transport_url, credentials):
        origin = rg.validate_remote(identity_url)
        self.calls.append({"origin": origin, "branch": branch, "sha": expected_sha, "offline": offline,
                           "transport_url": transport_url, "credentials": credentials})
        if origin in self.errors:
            raise self.errors[origin]
        if self.outside is not None:
            return self.outside
        path = Path(cache_dir) / _key(origin) / expected_sha
        path.mkdir(parents=True, exist_ok=True)
        return path

    def origins(self):
        return [c["origin"] for c in self.calls]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="acq-test-")
        self.root = Path(self._tmp)
        self.cache = self.root / "cache"
        self.kb_home = self.root / "kb-home"
        self.kb_home.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        _git(["init", "-q", "--template="], cwd=self.work)
        _git(["symbolic-ref", "HEAD", "refs/heads/16.0"], cwd=self.work)
        self.sha = _make_commit(self.work, "first")
        self.source = self.root / "source.git"
        _git(["init", "-q", "--bare", "--template=", str(self.source)])
        _git(["push", "-q", str(self.source), "16.0:refs/heads/16.0"], cwd=self.work)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def cache_repo(self, origin: str, revision: str) -> Path:
        return self.cache / _key(origin) / revision


class CommunityLocalRepoTests(_Base):
    def test_community_acquired_from_local_bare_repo_and_registers(self):
        e = entry("community", "16.0")
        spec = declared_spec(e, self.sha, required=True)
        plan = make_plan([planned(e, "ACQUIRE", self.sha, True, spec)])
        result = acq.acquire(plan, cache_dir=self.cache, transport_for=lambda _sid: str(self.source))
        self.assertIsNone(result.blocking)
        (row,) = result.results
        self.assertEqual(row.status, "ACQUIRED")
        self.assertEqual(row.revision, self.sha)
        repo = Path(row.repo_path)
        self.assertTrue(repo.is_absolute())
        self.assertEqual(repo, self.cache_repo("https://github.com/odoo/odoo", self.sha))
        self.assertEqual(_git(["-C", str(repo), "rev-parse", "--verify", f"{self.sha}^{{commit}}"]), self.sha)
        self.assertEqual(_git(["-C", str(repo), "remote", "get-url", "origin"]), "https://github.com/odoo/odoo")
        (out,) = result.specs
        self.assertEqual(out["url"], f"local:{repo}")
        self.assertEqual(out["revision"], self.sha)
        self.assertEqual(out["expected_origin"], "https://github.com/odoo/odoo")
        self.assertEqual((out["kind"], out["official"], out["branch"]), ("GIT_COMMUNITY", True, "16.0"))
        self.assertEqual(out["licence_id"], e.licence_id)
        self.assertEqual(out["licence_access"], e.licence_access)
        self.assertEqual(out["required"], True)
        self.assertEqual(registry.validate_spec(out, ALLOW), [])
        reg = registry.SourceRegistry(allow_list=ALLOW)
        reg.add(out)
        self.assertEqual(reg.get(out["source_id"])["url"], out["url"])
        self.assertEqual(result.source_meta, {out["source_id"]: {"repository": "odoo/odoo"}})
        self.assertEqual(os.listdir(self.kb_home), [], "acquisition never writes into kb-home")

    def test_absent_revision_from_real_remote_is_revision_unavailable_and_leaves_no_entry(self):
        # fetch_commit reports an absent commit as REVISION_UNAVAILABLE; acquire keeps that status.
        e = entry("community", "16.0")
        plan = make_plan([planned(e, "ACQUIRE", NO_SHA, False, declared_spec(e, NO_SHA, False))])
        result = acq.acquire(plan, cache_dir=self.cache, transport_for=lambda _sid: str(self.source))
        self.assertEqual(result.results[0].status, "REVISION_UNAVAILABLE")
        self.assertIsNone(result.results[0].repo_path)
        self.assertEqual(result.specs, [])
        self.assertFalse(self.cache_repo("https://github.com/odoo/odoo", NO_SHA).exists())


class PlannerOutputTests(_Base):
    def test_community_only_plan_acquires_every_community_source_with_fake_fetch(self):
        plan = planner_plan()
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        community = [s.source_id for s in plan.sources if s.edition == "community"]
        self.assertEqual([r.source_id for r in result.results if r.status == "ACQUIRED"], community)
        self.assertEqual(fake.origins(), ["https://github.com/odoo/odoo"] * len(community))
        self.assertTrue(all(c["credentials"] is None for c in fake.calls))
        self.assertEqual([s["source_id"] for s in result.specs], community)
        for spec in result.specs:
            self.assertTrue(spec["url"].startswith("local:"))
            self.assertEqual(registry.validate_spec(spec, ALLOW), [], spec["source_id"])
            reg = registry.SourceRegistry(allow_list=ALLOW)
            reg.add(spec)
        for sid_, meta in result.source_meta.items():
            self.assertRegex(meta["repository"], REPOSITORY)
            self.assertEqual(meta["repository"], "odoo/odoo")
        self.assertEqual(set(result.source_meta), set(community))

    def test_enterprise_skipped_without_token_is_not_in_specs_and_never_fetched(self):
        plan = planner_plan(token=False)
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        by = {r.source_id: r for r in result.results}
        for e in CATALOG.entries:
            if e.edition == "enterprise":
                self.assertEqual(by[CATALOG.source_id(e)].status, "SKIPPED_NO_CREDENTIALS")
        self.assertNotIn("https://github.com/odoo/enterprise", fake.origins())
        spec_ids = {s["source_id"] for s in result.specs}
        self.assertTrue(all(sid_.startswith("odoo-community-") for sid_ in spec_ids))
        self.assertIsNone(result.blocking)

    def test_enterprise_with_token_fetches_enterprise_with_credentials_and_community_without(self):
        token = Token(TOKEN)
        plan = planner_plan(token=True, ent_ok=True)
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, token=token, fetch=fake)
        self.assertIsNone(result.blocking)
        for call in fake.calls:
            if call["origin"] == rg.ENTERPRISE_IDENTITY:
                self.assertIs(call["credentials"], token)
            else:
                self.assertIsNone(call["credentials"], call["origin"])
        ent_calls = [c for c in fake.calls if c["origin"] == rg.ENTERPRISE_IDENTITY]
        self.assertEqual(len(ent_calls), sum(1 for e in CATALOG.entries if e.edition == "enterprise"))
        self.assertNotIn(TOKEN, json.dumps(result.to_dict()))

    def test_carried_source_keeps_installed_revision_and_is_not_fetched(self):
        installed_sha = sha("c", "16.0")
        plan = planner_plan(installed={"odoo-community-16.0": installed_sha}, release_id="rel-1")
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        carried_id = sid("community", "16.0")
        self.assertEqual(result.carried_source_ids, [carried_id])
        row = {r.source_id: r for r in result.results}[carried_id]
        self.assertEqual((row.status, row.repo_path, row.revision), ("CARRIED", None, installed_sha))
        self.assertEqual(len(fake.calls), 7, "the other seven community sources are fetched, the carried one is not")
        self.assertNotIn(installed_sha, [c["sha"] for c in fake.calls])
        carried_spec = next(s for s in result.specs if s["source_id"] == carried_id)
        self.assertEqual(carried_spec["url"], "https://github.com/odoo/odoo/")
        self.assertEqual(carried_spec["revision"], installed_sha)
        self.assertEqual(carried_spec["branch"], "16.0")
        self.assertEqual(result.source_meta[carried_id], {"repository": "odoo/odoo"})

    def test_results_follow_plan_order_and_are_deterministic(self):
        plan = planner_plan()
        first = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch()).to_dict()
        second = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch()).to_dict()
        self.assertEqual(first, second)
        self.assertEqual([r["source_id"] for r in first["results"]], [s.source_id for s in plan.sources])

    def test_result_is_json_safe(self):
        plan = planner_plan(token=True, ent_ok=True)
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=_Fetch())
        json.dumps(result.to_dict())


class CredentialScopeTests(_Base):
    def test_enterprise_without_token_is_skipped_with_zero_fetches(self):
        e = entry("enterprise", "16.0")
        spec = declared_spec(e, sha("e", "16.0"), required=False)
        plan = make_plan([planned(e, "ACQUIRE", sha("e", "16.0"), False, spec)])
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, token=None, fetch=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(result.results[0].status, "SKIPPED_NO_CREDENTIALS")
        self.assertEqual(result.specs, [])
        self.assertIsNone(result.blocking, "a non-required Enterprise source never blocks")

    def test_required_enterprise_without_token_blocks(self):
        e = entry("enterprise", "16.0")
        spec = declared_spec(e, sha("e", "16.0"), required=True)
        plan = make_plan([planned(e, "ACQUIRE", sha("e", "16.0"), True, spec)])
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(result.blocking, (CATALOG.source_id(e), "SKIPPED_NO_CREDENTIALS"))

    def test_community_never_receives_credentials_even_when_token_given(self):
        e = entry("community", "16.0")
        plan = make_plan([planned(e, "ACQUIRE", sha("c", "16.0"), True, declared_spec(e, sha("c", "16.0"), True))])
        fake = _Fetch()
        acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertIsNone(fake.calls[0]["credentials"])

    def test_auth_failed_and_unavailable_are_distinct_and_token_is_scrubbed(self):
        ent = entry("enterprise", "16.0")
        com = entry("community", "16.0")
        leaky = rg.RemoteGitError("AUTH_FAILED", None, f"the remote rejected the supplied credentials {TOKEN}")
        plan = make_plan([
            planned(ent, "ACQUIRE", sha("e", "16.0"), False, declared_spec(ent, sha("e", "16.0"), False)),
            planned(com, "ACQUIRE", sha("c", "16.0"), True, declared_spec(com, sha("c", "16.0"), True)),
        ])
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: leaky,
                              "https://github.com/odoo/odoo": rg.RemoteGitError("UNAVAILABLE", None, "down")})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        ent_row, com_row = result.results
        self.assertEqual(ent_row.status, "AUTH_FAILED")
        self.assertEqual(com_row.status, "UNAVAILABLE")
        self.assertNotEqual(ent_row.status, com_row.status)
        self.assertNotIn(TOKEN, ent_row.detail)
        self.assertIn("AUTH_FAILED", ent_row.detail)
        self.assertNotIn(TOKEN, json.dumps(result.to_dict()))
        self.assertEqual(result.blocking, (CATALOG.source_id(com), "UNAVAILABLE"))

    def test_error_detail_with_token_is_scrubbed_even_if_the_error_repeats_it(self):
        ent = entry("enterprise", "16.0")
        leaky = rg.RemoteGitError("UNAVAILABLE", None, f"connection to host failed while using {TOKEN}")
        plan = make_plan([planned(ent, "ACQUIRE", sha("e", "16.0"), False, declared_spec(ent, sha("e", "16.0"), False))])
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: leaky})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        self.assertEqual(result.results[0].status, "UNAVAILABLE")
        self.assertNotIn(TOKEN, result.results[0].detail)
        self.assertLessEqual(len(result.results[0].detail), 200)

    def test_remote_auth_required_maps_to_skipped_no_credentials(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), False, declared_spec(com, sha("c", "16.0"), False))])
        fake = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("AUTH_REQUIRED", None, "needs creds")})
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(result.results[0].status, "SKIPPED_NO_CREDENTIALS")


class OfflineTests(_Base):
    def test_offline_argument_makes_zero_fetch_calls_and_no_subprocess(self):
        ent = entry("enterprise", "16.0")
        com = entry("community", "16.0")
        plan = make_plan([
            planned(com, "ACQUIRE", sha("c", "16.0"), False, declared_spec(com, sha("c", "16.0"), False)),
            planned(ent, "ACQUIRE", sha("e", "16.0"), False, declared_spec(ent, sha("e", "16.0"), False)),
        ])
        fake = _Fetch()
        with mock.patch("subprocess.run", side_effect=AssertionError("no process")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("no process")):
            result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), offline=True, fetch=fake)
            default = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), offline=True)
        self.assertEqual(fake.calls, [])
        for res in (result, default):
            self.assertEqual([r.status for r in res.results], ["SKIPPED_OFFLINE", "SKIPPED_OFFLINE"])
            self.assertEqual(res.specs, [])
            self.assertFalse(any(r.status == "ACQUIRED" for r in res.results))
        self.assertIsNone(result.blocking, "non-required sources never block")

    def test_required_source_offline_blocks_at_once(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), True, declared_spec(com, sha("c", "16.0"), True))])
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, offline=True, fetch=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(result.blocking, (CATALOG.source_id(com), "SKIPPED_OFFLINE"))

    def test_offline_never_reads_the_token(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), False, declared_spec(com, sha("c", "16.0"), False))])
        with mock.patch.object(Token, "reveal", side_effect=AssertionError("token read while offline")):
            result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), offline=True, fetch=_Fetch())
        self.assertEqual(result.results[0].status, "SKIPPED_OFFLINE")

    def test_environment_offline_flag_is_honoured(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), False, declared_spec(com, sha("c", "16.0"), False))])
        fake = _Fetch()
        with mock.patch.dict(os.environ, {"PATH": os.environ.get("PATH", ""), "ODOOFLUX_OFFLINE": "1"}, clear=True):
            result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual(result.results[0].status, "SKIPPED_OFFLINE")

    def test_carried_sources_still_reported_offline(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "CARRY_FORWARD", sha("c", "16.0"), True, {}, installed=sha("c", "16.0"))])
        result = acq.acquire(plan, cache_dir=self.cache, offline=True, fetch=_Fetch())
        self.assertEqual(result.results[0].status, "CARRIED")
        self.assertEqual(result.carried_source_ids, [CATALOG.source_id(com)])
        self.assertIsNone(result.blocking)


class BlockingTests(_Base):
    def test_required_failure_fails_fast_and_stops_further_fetches(self):
        a = entry("community", "16.0")
        b = entry("community", "17.0")
        plan = make_plan([
            planned(a, "ACQUIRE", sha("c", "16.0"), True, declared_spec(a, sha("c", "16.0"), True)),
            planned(b, "ACQUIRE", sha("c", "17.0"), True, declared_spec(b, sha("c", "17.0"), True)),
        ])
        fake = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("UNAVAILABLE", None, "down")})
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(len(fake.calls), 1, "the second source is never fetched")
        self.assertEqual(result.blocking, (CATALOG.source_id(a), "UNAVAILABLE"))
        self.assertEqual(result.specs, [])

    def test_non_required_enterprise_failure_does_not_block_community(self):
        ent = entry("enterprise", "16.0")
        com = entry("community", "16.0")
        plan = make_plan([
            planned(ent, "ACQUIRE", sha("e", "16.0"), False, declared_spec(ent, sha("e", "16.0"), False)),
            planned(com, "ACQUIRE", sha("c", "16.0"), True, declared_spec(com, sha("c", "16.0"), True)),
        ])
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: rg.RemoteGitError("AUTH_FAILED", None, "rejected")})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        self.assertIsNone(result.blocking)
        self.assertEqual([r.status for r in result.results], ["AUTH_FAILED", "ACQUIRED"])
        self.assertEqual([s["source_id"] for s in result.specs], [CATALOG.source_id(com)])
        self.assertNotIn(CATALOG.source_id(ent), result.source_meta)

    def test_required_carried_source_does_not_block(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "CARRY_FORWARD", sha("c", "16.0"), True, {}, installed=sha("c", "16.0"))])
        result = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch())
        self.assertIsNone(result.blocking)


class BadRevisionTests(_Base):
    def test_malformed_sha_is_revision_unavailable_without_fetch(self):
        com = entry("community", "16.0")
        for bad in ("not-a-sha", "A" * 40, "a" * 39, "", None):
            with self.subTest(sha=bad):
                plan = make_plan([planned(com, "ACQUIRE", bad, False, declared_spec(com, sha("c", "16.0"), False))])
                fake = _Fetch()
                result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
                self.assertEqual(fake.calls, [])
                self.assertEqual(result.results[0].status, "REVISION_UNAVAILABLE")

    def test_remote_revision_unavailable_maps_to_revision_unavailable(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), True, declared_spec(com, sha("c", "16.0"), True))])
        fake = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("REVISION_UNAVAILABLE", None, "no")})
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(result.results[0].status, "REVISION_UNAVAILABLE")
        self.assertEqual(result.blocking, (CATALOG.source_id(com), "REVISION_UNAVAILABLE"))


class CarriedSpecTests(_Base):
    def test_carried_source_without_repository_is_listed_without_spec(self):
        orphan = pl.PlannedSource("odoo-community-99.0", "community", "99.0", None, None, sha("c", "99.0"),
                                  "CARRY_FORWARD", False, {}, None, sha("c", "99.0"))
        result = acq.acquire(make_plan([orphan]), cache_dir=self.cache, fetch=_Fetch())
        self.assertEqual(result.results[0].status, "CARRIED")
        self.assertEqual(result.carried_source_ids, ["odoo-community-99.0"])
        self.assertEqual(result.specs, [])
        self.assertEqual(result.source_meta, {})

    def test_carried_spec_is_the_plan_spec_at_the_installed_revision_and_is_not_rebuilt(self):
        com = entry("community", "16.0")
        plan_spec = declared_spec(com, sha("c", "16.0"), required=True)
        plan_spec["scope"] = {"modules": "*", "include": ["base"], "exclude": [], "file_kinds": []}  # a marker
        plan_spec["url"] = com.expected_origin + "/"
        installed = sha("i", "16.0")
        plan = make_plan([planned(com, "CARRY_FORWARD", sha("c", "16.0"), True, plan_spec, installed=installed)])
        fake = _Fetch()
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual(fake.calls, [])
        (spec,) = result.specs
        self.assertEqual(spec["revision"], installed)
        self.assertEqual(spec["scope"]["include"], ["base"], "the plan spec is used as emitted")
        expected = dict(plan_spec, revision=installed)
        self.assertEqual(spec, expected)
        self.assertEqual(result.source_meta, {CATALOG.source_id(com): {"repository": "odoo/odoo"}})

    def test_carried_without_valid_installed_revision_is_unavailable_and_blocks_when_required(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "CARRY_FORWARD", sha("c", "16.0"), True,
                                  declared_spec(com, sha("c", "16.0"), True), installed=None)])
        result = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch())
        self.assertEqual(result.results[0].status, "UNAVAILABLE")
        self.assertEqual(result.carried_source_ids, [])
        self.assertEqual(result.blocking, (CATALOG.source_id(com), "UNAVAILABLE"))

    def test_non_required_carried_without_installed_revision_is_left_out(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "CARRY_FORWARD", "x", False, declared_spec(com, sha("c", "16.0"), False),
                                  installed="not-hex")])
        result = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch())
        self.assertEqual(result.results[0].status, "UNAVAILABLE")
        self.assertEqual(result.specs, [])
        self.assertEqual(result.carried_source_ids, [])
        self.assertIsNone(result.blocking)


class FallbackTests(_Base):
    """A failed NON-required ACQUIRE with a known installed revision becomes a carried participant (plan item b)."""

    def _ent_plan(self, *, installed=True, required=False, target=None):
        ent = entry("enterprise", "16.0")
        inst = sha("i", "16.0") if installed else None
        spec = declared_spec(ent, target or sha("e", "16.0"), required)
        return ent, make_plan([planned(ent, "ACQUIRE", target or sha("e", "16.0"), required, spec, installed=inst)])

    def test_auth_failed_with_installed_revision_is_carried_and_keeps_failure_row(self):
        ent, plan = self._ent_plan()
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: rg.RemoteGitError("AUTH_FAILED", None, "rejected")})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        (row,) = result.results
        self.assertEqual(row.status, "AUTH_FAILED")
        self.assertIn("rejected", row.detail)
        self.assertEqual(result.carried_source_ids, [CATALOG.source_id(ent)])
        (spec,) = result.specs
        self.assertEqual(spec["revision"], sha("i", "16.0"))
        self.assertEqual(spec["url"], "https://github.com/odoo/enterprise/")
        self.assertEqual(result.source_meta, {CATALOG.source_id(ent): {"repository": "odoo/enterprise"}})
        self.assertIsNone(result.blocking)

    def test_every_fallback_status_becomes_carried_with_installed_revision(self):
        ent_no_token, plan_a = self._ent_plan()
        res_a = acq.acquire(plan_a, cache_dir=self.cache, token=None, fetch=_Fetch())
        self.assertEqual(res_a.results[0].status, "SKIPPED_NO_CREDENTIALS")
        self.assertEqual(res_a.carried_source_ids, [CATALOG.source_id(ent_no_token)])

        com = entry("community", "16.0")
        offline_plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), False,
                                          declared_spec(com, sha("c", "16.0"), False), installed=sha("i", "16.0"))])
        res_b = acq.acquire(offline_plan, cache_dir=self.cache, offline=True, fetch=_Fetch())
        self.assertEqual(res_b.results[0].status, "SKIPPED_OFFLINE")
        self.assertEqual(res_b.carried_source_ids, [CATALOG.source_id(com)])

        unavailable = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("UNAVAILABLE", None, "down")})
        res_c = acq.acquire(offline_plan, cache_dir=self.cache, fetch=unavailable)
        self.assertEqual(res_c.results[0].status, "UNAVAILABLE")
        self.assertEqual(res_c.carried_source_ids, [CATALOG.source_id(com)])

        malformed = make_plan([planned(com, "ACQUIRE", "bad", False, declared_spec(com, sha("c", "16.0"), False),
                                       installed=sha("i", "16.0"))])
        res_d = acq.acquire(malformed, cache_dir=self.cache, fetch=_Fetch())
        self.assertEqual(res_d.results[0].status, "REVISION_UNAVAILABLE")
        self.assertEqual(res_d.carried_source_ids, [CATALOG.source_id(com)])
        self.assertEqual(res_d.specs[0]["revision"], sha("i", "16.0"))

        auth = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("AUTH_FAILED", None, "no")})
        res_e = acq.acquire(offline_plan, cache_dir=self.cache, fetch=auth)
        self.assertEqual(res_e.results[0].status, "AUTH_FAILED")
        self.assertEqual(res_e.carried_source_ids, [CATALOG.source_id(com)])

    def test_failure_without_installed_revision_is_left_out(self):
        ent, plan = self._ent_plan(installed=False)
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: rg.RemoteGitError("AUTH_FAILED", None, "rejected")})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        self.assertEqual(result.results[0].status, "AUTH_FAILED")
        self.assertEqual(result.carried_source_ids, [])
        self.assertEqual(result.specs, [])
        self.assertNotIn(CATALOG.source_id(ent), result.source_meta)

    def test_required_failure_still_blocks_even_with_installed_revision(self):
        ent, plan = self._ent_plan(required=True)
        fake = _Fetch(errors={rg.ENTERPRISE_IDENTITY: rg.RemoteGitError("AUTH_FAILED", None, "rejected")})
        result = acq.acquire(plan, cache_dir=self.cache, token=Token(TOKEN), fetch=fake)
        self.assertEqual(result.blocking, (CATALOG.source_id(ent), "AUTH_FAILED"))
        self.assertEqual(result.carried_source_ids, [])
        self.assertEqual(result.specs, [])


class DecisionAndNotAttemptedTests(_Base):
    def test_blocked_plan_raises_value_error_before_any_fetch(self):
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", sha("c", "16.0"), True, declared_spec(com, sha("c", "16.0"), True))])
        blocked = pl.UpdatePlan("BLOCKED", "CHECK_UNAVAILABLE", ["blocked"], plan.sources, [], [], None, {}, [])
        fake = _Fetch()
        with self.assertRaises(ValueError):
            acq.acquire(blocked, cache_dir=self.cache, fetch=fake)
        self.assertEqual(fake.calls, [])

    def test_rows_after_a_blocking_source_are_not_attempted_with_no_detail(self):
        a = entry("community", "16.0")
        b = entry("community", "17.0")
        c = entry("community", "18.0")
        plan = make_plan([
            planned(a, "ACQUIRE", sha("c", "16.0"), True, declared_spec(a, sha("c", "16.0"), True)),
            planned(b, "ACQUIRE", sha("c", "17.0"), False, declared_spec(b, sha("c", "17.0"), False)),
            planned(c, "CARRY_FORWARD", sha("c", "18.0"), False, declared_spec(c, sha("c", "18.0"), False),
                    installed=sha("c", "18.0")),
        ])
        fake = _Fetch(errors={"https://github.com/odoo/odoo": rg.RemoteGitError("UNAVAILABLE", None, "down")})
        result = acq.acquire(plan, cache_dir=self.cache, fetch=fake)
        self.assertEqual([r.status for r in result.results], ["UNAVAILABLE", "NOT_ATTEMPTED", "NOT_ATTEMPTED"])
        self.assertEqual([r.source_id for r in result.results], [s.source_id for s in plan.sources])
        for row in result.results[1:]:
            self.assertEqual((row.detail, row.repo_path, row.revision), ("", None, None))
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(result.specs, [])
        self.assertEqual(result.carried_source_ids, [])
        self.assertIn("NOT_ATTEMPTED", acq.STATUSES)


class DefenceTests(_Base):
    def test_fetch_result_outside_the_cache_is_refused(self):
        outside = self.root / "elsewhere" / self.sha
        outside.mkdir(parents=True)
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", self.sha, True, declared_spec(com, self.sha, True))])
        result = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch(outside=outside))
        self.assertEqual(result.results[0].status, "UNAVAILABLE")
        self.assertIsNone(result.results[0].repo_path)
        self.assertEqual(result.specs, [])

    def test_symlink_inside_the_cache_pointing_outside_is_refused(self):
        outside = self.root / "elsewhere" / self.sha
        outside.mkdir(parents=True)
        link_dir = self.cache / "links"
        link_dir.mkdir(parents=True)
        link = link_dir / self.sha
        link.symlink_to(outside, target_is_directory=True)
        com = entry("community", "16.0")
        plan = make_plan([planned(com, "ACQUIRE", self.sha, True, declared_spec(com, self.sha, True))])
        result = acq.acquire(plan, cache_dir=self.cache, fetch=_Fetch(outside=link))
        self.assertEqual(result.results[0].status, "UNAVAILABLE")

    def test_token_must_be_a_token_object(self):
        plan = make_plan([])
        with self.assertRaises(TypeError):
            acq.acquire(plan, cache_dir=self.cache, token=TOKEN, fetch=_Fetch())

    def test_nothing_is_written_when_plan_has_only_skipped_sources(self):
        skipped = pl.PlannedSource(CATALOG.source_id(entry("enterprise", "16.0")), "enterprise", "16.0", None, None,
                                   None, "SKIP", False, {}, None)
        fake = _Fetch()
        result = acq.acquire(make_plan([skipped]), cache_dir=self.cache, fetch=fake)
        self.assertEqual([r.status for r in result.results], ["SKIPPED_NO_CREDENTIALS"])
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
