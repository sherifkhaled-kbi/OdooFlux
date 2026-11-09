"""Feature 012 Wave 3c (plan Addendum E): the knowledge update orchestrator with fakes. No network, no git, no real release.

The remote is a fake `ls_remote`; the fetch is a fake that returns a directory named by the commit under the managed cache
(enough for the acquisition contract, because the build itself is replaced by a fake `pipeline.run_build` where a test
needs one). Subprocess and sockets are patched to fail for the whole module, so any network or process use is an error.
The real build, activation and rollback are covered by tests/integration/kap/test_update_orchestrator.py.
"""

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.release.store import read_active
from odooflux.knowledge.update import catalog as catalog_mod, credentials, inventory, planner
from odooflux.knowledge.update import orchestrator as orch
from odooflux.knowledge.update.history import UpdateHistory
from odooflux.knowledge.update.remote_git import RemoteGitError

COM_REPO = "https://github.com/odoo/odoo.git"
ENT_REPO = "https://github.com/odoo/enterprise.git"
COM16, COM17 = "odoo-community-16.0", "odoo-community-17.0"
ENT16, ENT17 = "odoo-enterprise-16.0", "odoo-enterprise-17.0"
TOKEN = "dummy-enterprise-token-0123456789"  # a dummy value; never a credential
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40
CLOCK = "2026-11-09T10:00:00Z"


def _tree(root: Path) -> dict:
    if not root.exists():
        return {}
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _write_catalog(path: Path) -> Path:
    shipped = json.loads(catalog_mod.CATALOG_PATH.read_text(encoding="utf-8"))
    shipped["entries"] = [e for e in shipped["entries"] if e["version"] in ("16.0", "17.0")]
    path.write_text(json.dumps(shipped, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class FakeRemote:
    def __init__(self, heads=None):
        self.heads = heads if heads is not None else {
            COM_REPO: {"16.0": SHA_A, "17.0": SHA_B},
            ENT_REPO: {"16.0": SHA_C, "17.0": SHA_D},
        }
        self.calls = []
        self.error = None

    def ls_remote(self, repository, *, offline=False, credentials=None):
        self.calls.append((repository, credentials is not None))
        if self.error is not None:
            raise self.error
        return dict(self.heads[repository])

    def fetch(self, identity_url, *, branch, expected_sha, cache_dir, offline, transport_url, credentials):
        path = Path(cache_dir) / expected_sha
        path.mkdir(parents=True, exist_ok=True)
        return path


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._net = [mock.patch.object(socket, "socket", side_effect=AssertionError("network is disabled")),
                    mock.patch.object(socket, "create_connection", side_effect=AssertionError("network is disabled")),
                    mock.patch.object(subprocess, "Popen", side_effect=AssertionError("no process may start"))]
        for patch in cls._net:
            patch.start()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        for patch in cls._net:
            patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.dir = self.base / self.id().rsplit(".", 1)[-1]
        self.dir.mkdir()
        self.home = self.dir / "kb"
        self.catalog = catalog_mod.load_catalog(_write_catalog(self.dir / "catalog.json"))
        self.remote = FakeRemote()
        self.toolkit = SimpleNamespace(detectors={})

    def _run(self, home=None, **kwargs):
        options = dict(toolkit=self.toolkit, catalog=self.catalog, ls_remote=self.remote.ls_remote,
                       fetch=self.remote.fetch, clock=lambda: CLOCK, cache_dir=self.dir / "cache")
        options.update(kwargs)
        return orch.run_update(self.home if home is None else home, **options)

    def _history(self):
        return UpdateHistory(self.home).read()


class RefusalTests(_Base):
    def test_missing_toolkit_is_blocked_and_the_home_is_not_created(self):
        result = self._run(toolkit=None)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn("extract toolkit not attached", result.reasons)
        self.assertFalse(self.home.exists())
        self.assertEqual(self.remote.calls, [])

    def test_bad_arguments_are_refused_before_any_work(self):
        with self.assertRaises(ValueError):
            self._run(fault_at="nowhere")
        with self.assertRaises(ValueError):
            self._run(only_pair="16-17")
        self.assertFalse(self.home.exists())

    def test_offline_makes_no_network_call_and_blocks_on_check_unavailable(self):
        result = self._run(offline=True)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.reasons[0].startswith("CHECK_UNAVAILABLE"), result.reasons)
        self.assertEqual(self.remote.calls, [], "offline: the remote is never read")
        self.assertEqual([e["outcome"] for e in self._history()], ["BLOCKED"])
        self.assertEqual(read_active(self.home), None)

    def test_invalid_active_state_is_blocked_before_any_network_call(self):
        self.home.mkdir()
        (self.home / "active.json").write_text("{not a pointer", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.reasons[0].startswith("LOCAL_STATE_INVALID"), result.reasons)
        self.assertEqual(self.remote.calls, [])
        self.assertEqual([e["outcome"] for e in self._history()], ["BLOCKED"])

    def test_broken_history_chain_is_blocked_and_never_extended(self):
        (self.home / "updates").mkdir(parents=True)
        history = self.home / "updates" / "history.jsonl"
        history.write_bytes(b"this is not a history line\n")
        before = history.read_bytes()
        result = self._run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.reasons[0].startswith("HISTORY_INVALID"), result.reasons)
        self.assertEqual(history.read_bytes(), before, "a broken chain is never appended to")
        self.assertEqual(self.remote.calls, [])

    def test_require_enterprise_without_a_token_is_blocked_and_recorded(self):
        result = self._run(require_enterprise=True)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any(r.startswith("ENTERPRISE_REQUIRED_UNAVAILABLE") for r in result.reasons), result.reasons)
        self.assertNotIn(ENT_REPO, [call[0] for call in self.remote.calls], "Enterprise is not contacted without a token")
        self.assertEqual([e["outcome"] for e in self._history()], ["BLOCKED"])
        self.assertIsNone(read_active(self.home))

    def test_unknown_only_pair_is_refused_as_a_value_error(self):
        with self.assertRaises(ValueError):
            self._run(only_pair=("16",))


class DryRunTests(_Base):
    def test_dry_run_reads_metadata_and_writes_nothing(self):
        with mock.patch.object(pl, "run_build", side_effect=AssertionError("a dry run never builds")):
            result = self._run(dry_run=True)
        self.assertEqual(result.outcome, "DRY_RUN")
        self.assertTrue(result.dry_run)
        self.assertEqual(result.plan["decision"], "BUILD")
        self.assertIsNone(result.new_release)
        self.assertTrue(self.remote.calls, "the metadata is read as the check reads it")
        self.assertEqual(_tree(self.home), {}, "nothing is created under the kb-home")

    def test_dry_run_with_a_blocked_plan_reports_blocked_and_writes_nothing(self):
        result = self._run(dry_run=True, require_enterprise=True)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(_tree(self.home), {})


class LockTests(_Base):
    def test_concurrent_update_is_blocked_and_nothing_is_recorded(self):
        (self.home / "updates").mkdir(parents=True)
        holder = os.open(self.home / "updates" / orch.UPDATE_LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, holder)
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with mock.patch.object(orch, "LOCK_WAIT_SECONDS", 0.1):
            result = self._run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.reasons[0].startswith("CONCURRENT_UPDATE"), result.reasons)
        self.assertFalse((self.home / "updates" / "history.jsonl").exists(), "no history append on contention")
        self.assertEqual(self.remote.calls, [])
        self.assertIsNone(read_active(self.home))

    def test_the_update_lock_is_released_after_a_blocked_run(self):
        result = self._run(offline=True)
        self.assertEqual(result.outcome, "BLOCKED")
        fd = os.open(self.home / "updates" / orch.UPDATE_LOCK_NAME, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # would raise if the run still held it
        finally:
            os.close(fd)

    def test_the_updates_directory_is_created_private(self):
        self._run(offline=True)
        mode = (self.home / "updates").stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)


class FailureTests(_Base):
    def test_an_exception_after_the_lock_is_failed_with_the_token_scrubbed_and_unlocked(self):
        token = credentials.Token(TOKEN)
        with mock.patch.object(planner, "plan_update", side_effect=RuntimeError(f"boom {TOKEN}")):
            result = self._run(token=token)
        self.assertEqual(result.outcome, "FAILED")
        text = json.dumps(result.to_dict())
        self.assertNotIn(TOKEN, text)
        self.assertIn("RuntimeError", text)
        self.assertNotIn(TOKEN, (self.home / "updates" / "history.jsonl").read_text(encoding="utf-8"))
        fd = os.open(self.home / "updates" / orch.UPDATE_LOCK_NAME, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_a_remote_error_text_carrying_the_token_never_reaches_the_result(self):
        token = credentials.Token(TOKEN)
        self.remote.error = RemoteGitError("UNAVAILABLE", None, f"remote said {TOKEN}")
        result = self._run(token=token, require_enterprise=False)
        self.assertNotIn(TOKEN, json.dumps(result.to_dict()))
        self.assertNotIn(TOKEN, (self.home / "updates" / "history.jsonl").read_text(encoding="utf-8")
                         if (self.home / "updates" / "history.jsonl").exists() else "")


class BuildMappingTests(_Base):
    """Fresh Community install with a fake fetch. The build itself is replaced by a fake that returns a chosen result."""

    def _build_result(self, **fields):
        return pl.BuildResult(**fields)

    def test_the_build_plan_composes_community_pairs_and_policy(self):
        captured = {}

        def fake_build(home, plan, **kwargs):
            captured["plan"] = plan
            return self._build_result(outcome="STOPPED", code="SOURCE_REQUIRED_FAILED", message="stop",
                                      stopped_at=1)

        with mock.patch.object(pl, "run_build", side_effect=fake_build):
            result = self._run()
        plan = captured["plan"]
        self.assertEqual(plan.label, "update")
        self.assertEqual(plan.pairs, [{"step": "16-17", "from": COM16, "to": COM17, "key": "16-17"}])
        self.assertEqual(sorted(spec["source_id"] for spec in plan.specs), [COM16, COM17])
        self.assertEqual(set(plan.adapters), {"GIT_COMMUNITY", "GIT_ENTERPRISE"})
        self.assertTrue(plan.emit_inventory)
        self.assertEqual(plan.author, "update")
        self.assertEqual(plan.created_at, CLOCK)
        self.assertEqual(plan.checked_on, "2026-11-09")
        self.assertEqual(plan.supersede_policy.policy_name, "semantic-replacement/1")
        self.assertEqual(plan.secrets, ())
        self.assertEqual(plan.parent_dir, None)
        self.assertEqual(plan.adapter_by_source, {})
        self.assertEqual(result.outcome, "FAILED")
        self.assertIn("SOURCE_REQUIRED_FAILED", result.reasons[0])

    def test_a_gate_stop_is_blocked_with_its_code_and_nothing_is_installed(self):
        with mock.patch.object(pl, "run_build", return_value=self._build_result(
                outcome="STOPPED", code="DESTRUCTIVE_NEEDS_SUPERSEDE", message="removed without approval: x",
                stopped_at=12)):
            result = self._run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(result.reasons[0].startswith("BLOCKED: DESTRUCTIVE_NEEDS_SUPERSEDE"), result.reasons)
        self.assertIsNone(read_active(self.home))
        self.assertEqual([e["outcome"] for e in self._history()], ["BLOCKED"])

    def test_a_failed_build_outcome_is_failed_and_nothing_is_installed(self):
        with mock.patch.object(pl, "run_build", return_value=self._build_result(outcome="FAILED", completeness="FAILED")):
            result = self._run()
        self.assertEqual(result.outcome, "FAILED")
        self.assertIsNone(read_active(self.home))
        self.assertEqual([e["outcome"] for e in self._history()], ["FAILED"])

    def test_a_required_source_failure_stops_before_any_build(self):
        self.remote.error = None

        def failing_fetch(identity_url, **kwargs):
            raise RemoteGitError("UNAVAILABLE", None, "the remote is down")

        with mock.patch.object(pl, "run_build", side_effect=AssertionError("no build after a failed acquisition")):
            result = self._run(fetch=failing_fetch)
        self.assertEqual(result.outcome, "FAILED")
        self.assertIn("UNAVAILABLE", result.reasons[0])
        self.assertIsNone(read_active(self.home))


class PairCompletionTests(_Base):
    def test_carried_enterprise_pair_is_added_when_both_sources_participate(self):
        plan = SimpleNamespace(
            sources=[SimpleNamespace(source_id=COM16, edition="community"), SimpleNamespace(source_id=COM17, edition="community"),
                     SimpleNamespace(source_id=ENT16, edition="enterprise"), SimpleNamespace(source_id=ENT17, edition="enterprise")],
            pairs=[{"step": "16-17", "from": COM16, "to": COM17}])
        acquisition = SimpleNamespace(specs=[{"source_id": s} for s in (COM16, COM17, ENT16, ENT17)])
        pairs = orch._pairs(self.catalog, plan, acquisition, None)
        self.assertEqual(pairs, [
            {"step": "16-17", "from": COM16, "to": COM17, "key": "16-17"},
            {"step": "16-17", "from": ENT16, "to": ENT17, "key": "16-17.enterprise"},
        ])

    def test_a_pair_with_an_unavailable_source_is_not_built(self):
        plan = SimpleNamespace(
            sources=[SimpleNamespace(source_id=COM16, edition="community"), SimpleNamespace(source_id=COM17, edition="community")],
            pairs=[{"step": "16-17", "from": COM16, "to": COM17}])
        acquisition = SimpleNamespace(specs=[{"source_id": COM16}])
        self.assertEqual(orch._pairs(self.catalog, plan, acquisition, None), [])

    def test_only_pair_restricts_the_completed_pairs(self):
        plan = SimpleNamespace(
            sources=[SimpleNamespace(source_id=COM16, edition="community"), SimpleNamespace(source_id=COM17, edition="community")],
            pairs=[])
        acquisition = SimpleNamespace(specs=[{"source_id": COM16}, {"source_id": COM17}])
        self.assertEqual(len(orch._pairs(self.catalog, plan, acquisition, ("16", "17"))), 1)
        self.assertEqual(orch._pairs(self.catalog, plan, acquisition, ("17", "18")), [])


class EnterpriseSummaryTests(unittest.TestCase):
    def _check(self, *rows):
        sources = tuple(SimpleNamespace(source_id=sid, edition="enterprise", status=st, detail="")
                        for sid, st in rows)
        return SimpleNamespace(sources=sources)

    def test_no_enterprise_is_not_installed(self):
        summary = orch._enterprise_summary(SimpleNamespace(sources=()), SimpleNamespace(revisions={}), None, [])
        self.assertEqual((summary["status"], summary["freshness"]), ("NOT_INSTALLED", "NOT_INSTALLED"))

    def test_skipped_without_a_token_and_not_installed(self):
        check = self._check((ENT16, "SKIPPED_NO_CREDENTIALS"), (ENT17, "SKIPPED_NO_CREDENTIALS"))
        acquisition = SimpleNamespace(results=[SimpleNamespace(source_id=ENT16, status="SKIPPED_NO_CREDENTIALS", detail=""),
                                               SimpleNamespace(source_id=ENT17, status="SKIPPED_NO_CREDENTIALS", detail="")])
        summary = orch._enterprise_summary(check, SimpleNamespace(revisions={}), acquisition, [])
        self.assertEqual((summary["status"], summary["freshness"]), ("SKIPPED_NO_CREDENTIALS", "NOT_INSTALLED"))

    def test_acquired_in_this_run_is_fresh(self):
        check = self._check((ENT16, "OK"), (ENT17, "OK"))
        acquisition = SimpleNamespace(results=[SimpleNamespace(source_id=ENT16, status="ACQUIRED", detail=""),
                                               SimpleNamespace(source_id=ENT17, status="ACQUIRED", detail="")])
        summary = orch._enterprise_summary(check, SimpleNamespace(revisions={}), acquisition, [])
        self.assertEqual((summary["status"], summary["freshness"]), ("ACQUIRED", "FRESH"))

    def test_installed_and_carried_is_never_fresh(self):
        check = self._check((ENT17, "SKIPPED_NO_CREDENTIALS"))
        installed = SimpleNamespace(revisions={ENT17: SHA_A})
        summary = orch._enterprise_summary(check, installed, None, [ENT17])
        self.assertEqual((summary["status"], summary["freshness"]), ("SKIPPED_NO_CREDENTIALS", "STALE_UNVERIFIED"))
        self.assertEqual(summary["carried"], [ENT17])

    def test_a_rejected_token_is_reported_while_the_installed_source_is_carried(self):
        check = self._check((ENT17, "AUTH_FAILED"))
        installed = SimpleNamespace(revisions={ENT17: SHA_A})
        acquisition = SimpleNamespace(results=[SimpleNamespace(source_id=ENT17, status="CARRIED", detail="")])
        summary = orch._enterprise_summary(check, installed, acquisition, [ENT17])
        self.assertEqual(summary["status"], "AUTH_FAILED")
        self.assertEqual(summary["freshness"], "STALE_UNVERIFIED")
        self.assertEqual(summary["carried"], [ENT17])


class EnterpriseCompatibilityTests(_Base):
    """The carried-Enterprise dependency check on real inventory documents (built with the inventory module)."""

    def _release(self, name, document):
        root = self.dir / name
        (root / "knowledge" / "inventory").mkdir(parents=True)
        (root / "knowledge" / "inventory" / "17.0.json").write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        return root

    def setUp(self):
        super().setUp()
        self.store = BlobStore(self.dir / "blobs")

    def test_a_dropped_community_dependency_of_a_carried_enterprise_module_is_a_finding(self):
        prev_doc = self._merge_two(COM17, {"sale_demo": ()}, ENT17, {"sale_ent": ("sale_demo",)})
        new_doc = self._merge_two(COM17, {"sale_other": ()}, ENT17, {"sale_ent": ("sale_demo",)})
        prev = self._release("prev", prev_doc)
        new = self._release("new", new_doc)
        findings = orch._enterprise_findings(prev, new, ["17.0"])
        self.assertEqual(findings, [{"module": "sale_ent", "missing": ["sale_demo"]}])
        self.assertEqual(orch._enterprise_findings(prev, prev, ["17.0"]), [])

    def test_a_missing_inventory_on_either_side_fails_closed(self):
        prev_doc = self._merge_two(COM17, {"sale_demo": ()}, ENT17, {"sale_ent": ("sale_demo",)})
        prev = self._release("prev2", prev_doc)
        empty = self.dir / "empty"
        empty.mkdir()
        findings = orch._enterprise_findings(prev, empty, ["17.0"])
        self.assertEqual(findings[0]["missing"], ["new inventory not emitted"])
        findings = orch._enterprise_findings(empty, prev, ["17.0"])
        self.assertEqual(findings[0]["missing"], ["previous inventory not recorded"])

    def _merge_two(self, com_id, com_modules, ent_id, ent_modules):
        com = inventory.build_part(
            {"source_id": com_id, "entries": self._entries(com_modules)}, self.store, source_id=com_id,
            confidentiality="public")
        ent = inventory.build_part(
            {"source_id": ent_id, "entries": self._entries(ent_modules)}, self.store, source_id=ent_id,
            confidentiality="enterprise")
        return inventory.merge([com, ent])

    def _entries(self, modules):
        out = []
        for name, depends in modules.items():
            data = f"{{'name': '{name}', 'depends': {list(depends)!r}}}".encode("utf-8")
            out.append({"path": f"addons/{name}/__manifest__.py", "sha256": self.store.put(data), "size": len(data)})
        return out


class HistoryInputsTests(_Base):
    def test_the_last_build_inputs_come_from_the_newest_active_or_noop_record(self):
        history = UpdateHistory(self.home, clock=lambda: CLOCK)
        inputs = {"source_shas": {COM16: SHA_A}, "snapshot_digests": {COM16: "e" * 64}, "catalog_digest": "x",
                  "extractor_version": "1", "rule_schema_version": "1", "build_config": {}, "parent_release_id": None}
        history.append({"outcome": "ACTIVE", "fingerprint": "f" * 64, "previous_release": None,
                        "new_release": None, "source_revisions": {}, "reason": None,
                        "details": {"build_inputs": inputs}})
        self.assertEqual(orch._last_build_inputs(UpdateHistory(self.home)), inputs)
        history.append({"outcome": "BLOCKED", "fingerprint": None, "previous_release": None, "new_release": None,
                        "source_revisions": {}, "reason": "BLOCKED: x"})
        self.assertEqual(orch._last_build_inputs(UpdateHistory(self.home)), inputs, "BLOCKED records are skipped")
        history.append({"outcome": "NOOP", "fingerprint": None, "previous_release": None, "new_release": None,
                        "source_revisions": {}, "reason": "no change"})
        self.assertIsNone(orch._last_build_inputs(UpdateHistory(self.home)), "a NOOP without inputs has none")


if __name__ == "__main__":
    unittest.main()
