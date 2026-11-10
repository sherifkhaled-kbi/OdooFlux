"""RC fix: `update --from N --to M` acquires only the Community (and, with credentials, Enterprise) sources of the
selected pair; the unscoped update keeps the full-catalog behaviour. Fake remotes only; no network, no process."""

import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux.knowledge.update import catalog as catalog_mod
from odooflux.knowledge.update import orchestrator as orch
from odooflux.knowledge.update import planner as pl
from odooflux.knowledge.update.remote_git import RemoteGitError
from tests.unit.knowledge.update.test_planner import ENTERPRISE, COMMUNITY, check, installed, plan, sha

PAIR = ("16", "17")
CLOCK = "2026-11-10T10:00:00Z"


def acquired(p):
    return sorted(s.source_id for s in p.sources if s.action == "ACQUIRE")


class PlannerScopeTests(unittest.TestCase):
    def test_scoped_plan_acquires_only_the_pair(self):
        p = plan(check(), installed(community=(), enterprise=()), only_pair=PAIR)
        self.assertEqual(acquired(p), ["odoo-community-16.0", "odoo-community-17.0"])
        self.assertEqual([x["step"] for x in p.pairs], ["16-17"])
        others = [s for s in p.sources if s.edition == "community" and s.version not in ("16.0", "17.0")]
        self.assertTrue(others)
        for s in others:
            self.assertEqual(s.action, "SKIP")
            self.assertFalse(s.required)
        self.assertEqual(sum("outside the selected pair" in r for r in p.reasons), len(others) * 2)  # community and enterprise

    def test_unscoped_plan_still_acquires_the_whole_catalog(self):
        p = plan(check(), installed(community=(), enterprise=()))
        self.assertEqual(len(acquired(p)), len(COMMUNITY))

    def test_enterprise_is_not_acquired_without_a_token_even_when_scoped(self):
        p = plan(check(), installed(community=(), enterprise=()), only_pair=PAIR, token=False)
        self.assertFalse([s for s in p.sources if s.edition == "enterprise" and s.action == "ACQUIRE"])

    def test_enterprise_with_a_token_is_scoped_to_the_pair(self):
        p = plan(check(ent_status="OK"), installed(community=(), enterprise=()), only_pair=PAIR, token=True)
        got = sorted(s.version for s in p.sources if s.edition == "enterprise" and s.action == "ACQUIRE")
        self.assertEqual(got, ["16.0", "17.0"])

    def test_installed_sources_outside_the_pair_are_carried_not_refetched(self):
        # 18.0 changed upstream, but it is outside the pair: keep the installed trusted revision
        p = plan(check(c_over={"18.0": sha("new", "18.0")}), installed(community=COMMUNITY), only_pair=PAIR)
        s18 = next(s for s in p.sources if s.source_id == "odoo-community-18.0")
        self.assertEqual(s18.action, "CARRY_FORWARD")
        self.assertEqual(s18.target_sha, sha("c", "18.0"))
        self.assertNotIn("odoo-community-18.0", acquired(p))

    def test_an_unread_source_outside_the_pair_does_not_block(self):
        chk = check()
        rows = tuple(r if r.version in ("16.0", "17.0") or r.edition != "community"
                     else r.__class__(r.source_id, r.edition, r.version, None, None, "UNAVAILABLE") for r in chk.sources)
        chk = chk.__class__(chk.schema, chk.statuses, rows, chk.new_versions, chk.affected_transitions,
                            chk.enterprise_freshness, chk.catalog_digest, chk.offline, chk.installed_release)
        p = plan(chk, installed(community=(), enterprise=()), only_pair=PAIR)
        self.assertIsNone(p.blocking_reason)
        self.assertEqual(acquired(p), ["odoo-community-16.0", "odoo-community-17.0"])


class OrchestratorScopeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        for target, kw in (("socket.socket", {}), ("socket.create_connection", {}), ("subprocess.Popen", {})):
            patcher = mock.patch(target, side_effect=AssertionError("no network or process"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.catalog = catalog_mod.load_catalog()
        self.heads = {}
        for e in self.catalog.entries:
            self.heads.setdefault(e.repository, {})[e.branch] = sha(e.edition, e.version)
        self.ls_calls, self.fetch_calls = [], []

    def ls_remote(self, repository, *, offline=False, credentials=None):
        self.ls_calls.append((repository, offline, credentials))
        return dict(self.heads[repository])

    def fetch(self, identity_url, *, branch, expected_sha, **kwargs):
        self.fetch_calls.append((identity_url, branch, kwargs.get("credentials")))
        raise RemoteGitError("UNAVAILABLE", "stop after recording the fetch")  # no build is wanted here

    def go(self, **kw):
        options = dict(toolkit=SimpleNamespace(detectors={}), catalog=self.catalog, ls_remote=self.ls_remote,
                       fetch=self.fetch, clock=lambda: CLOCK, cache_dir=self.dir / "cache")
        options.update(kw)
        return orch.run_update(self.dir / "kb", **options)

    def test_scoped_update_fetches_only_the_pair_and_never_enterprise(self):
        result = self.go(only_pair=PAIR)
        self.assertEqual(result.outcome, "FAILED")
        self.assertEqual([b for _u, b, _c in self.fetch_calls], ["16.0"])  # first failure stops the run
        self.assertTrue(all("enterprise" not in u for u, _b, _c in self.fetch_calls))

    def test_scoped_dry_run_plans_no_source_outside_the_pair(self):
        result = self.go(only_pair=PAIR, dry_run=True)
        acquire = sorted(x["source_id"] for x in result.plan["sources"] if x["action"] == "ACQUIRE")
        self.assertEqual(acquire, ["odoo-community-16.0", "odoo-community-17.0"])
        self.assertEqual(self.fetch_calls, [])

    def test_unscoped_update_starts_with_the_first_catalog_version(self):
        self.go()
        self.assertEqual(self.fetch_calls[0][1], "12.0")

    def test_offline_performs_no_remote_call(self):
        self.go(offline=True, only_pair=PAIR)
        self.assertEqual((self.ls_calls, self.fetch_calls), ([], []))

    def test_failed_acquisition_leaves_no_active_release(self):
        from odooflux.knowledge.release.store import read_active
        self.go(only_pair=PAIR)
        self.assertIsNone(read_active(self.dir / "kb"))


if __name__ == "__main__":
    unittest.main()
