"""Feature 012 Wave 3c (plan Addendum E): the knowledge update orchestrator end to end, on synthetic local repositories.

Real `pipeline.run_build` runs on two synthetic clones (a Community 16.0 -> 17.0 repository and an Enterprise repository
with a simulated official origin). The remote is faked with `ls_remote`, and the fetch goes to local bare repositories
through the `transport_for` seam. No socket is opened (sockets are patched for the whole module). Every kb-home is a
temporary directory; the user's knowledge base is never touched.

Covered: fresh Community-only install; fresh install with an Enterprise token (internal release, both families); an
unchanged second run (NOOP); a changed Community revision (ids rotate, activated without a manual supersede); a
Community-only update that carries the Enterprise release byte-identically; a tampered retained snapshot (fail closed); a
rejected Enterprise token (carried and reported); an injected fault at activation (rolled back, retried); a dry run (the
kb-home tree is unchanged); and the token value appearing in no text file of the kb-home.
"""

import hashlib
import json
import re
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.builtins import build_registries
from odooflux.knowledge.release.provenance import SNAPSHOT_DIRNAME
from odooflux.knowledge.release.store import read_active, read_release_state
from odooflux.knowledge.update import activation
from odooflux.knowledge.update import catalog as catalog_mod
from odooflux.knowledge.update import credentials
from odooflux.knowledge.update import orchestrator as orch
from odooflux.knowledge.update.history import UpdateHistory
from odooflux.knowledge.update.remote_git import RemoteGitError
from tests.fixtures.kap import make_synth_repo as synth

COM_REPO = "https://github.com/odoo/odoo.git"
ENT_REPO = "https://github.com/odoo/enterprise.git"
COM16, COM17 = "odoo-community-16.0", "odoo-community-17.0"
ENT16, ENT17 = "odoo-enterprise-16.0", "odoo-enterprise-17.0"
ENT_IDS = (ENT16, ENT17)
ENT_MODULE = "sale_ent"
TOKEN = "dummy-enterprise-token-0123456789"  # a dummy value; never a credential
_CLOCK = {"n": 0}


def _clock() -> str:
    _CLOCK["n"] += 1
    return f"2026-11-09T10:{_CLOCK['n'] // 60 % 60:02d}:{_CLOCK['n'] % 60:02d}Z"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _tree(root: Path) -> dict:
    """relative path -> sha256 of the file bytes, or None for a directory. Covers the whole tree."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _enterprise_tree(tree: dict) -> dict:
    """The synthetic tree with the addon renamed to ENT_MODULE. Its manifest depends only on a Community module that the
    Community inventory contains, so the carried-Enterprise dependency check can pass (the synthetic Community tree has no
    `base` or `sale` module)."""
    out = {}
    for path, text in tree.items():
        new_path = path.replace("sale_demo", ENT_MODULE)
        new_text = text.replace("sale_demo", ENT_MODULE)
        if path.endswith("__manifest__.py"):
            new_text = re.sub(r"'depends': \[[^\]]*\]", "'depends': ['sale_demo']", new_text)
        out[new_path] = new_text
    return out


def _enterprise_repo(dest: Path) -> dict:
    """Two-commit Enterprise clone (16.0 and 17.0 branches). Returns {version: sha}."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="upd-ent-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        for version, tree in (("16.0", synth._TREE_16), ("17.0", synth._TREE_17)):
            env = synth._git_env(home, template, synth._DATES[version])
            tree_sha = synth._write_tree(git_dir, env, _enterprise_tree(tree))
            args = ["commit-tree", tree_sha, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return shas


def _repin_community(repo: str, from_sha: str) -> str:
    """A new 17.0 commit with the same tree and a new message: the same content under a changed revision."""
    scratch = Path(tempfile.mkdtemp(prefix="upd-repin-"))
    try:
        env = synth._git_env(scratch, scratch, "1720000000 +0000")
        git_dir = Path(repo) / ".git"
        tree = synth._run(["rev-parse", "17.0^{tree}"], env, git_dir)
        sha = synth._run(["commit-tree", tree, "-m", "Synthetic 17.0 target (re-pinned, same tree)",
                          "-p", from_sha], env, git_dir)
        synth._run(["update-ref", "refs/heads/17.0", sha], env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return sha


def _bare_copy(source: Path, dest: Path) -> str:
    """A local bare repository with every branch of `source`. Used only as the transport of a fetch."""
    scratch = Path(tempfile.mkdtemp(prefix="upd-bare-"))
    try:
        env = synth._git_env(scratch, scratch, "")
        subprocess.run(["git", "clone", "--bare", "-q", "--no-hardlinks", str(source), str(dest)],
                       env=env, check=True, capture_output=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return str(dest)


def _write_catalog(path: Path) -> Path:
    """The shipped catalog reduced to the two versions the synthetic repositories provide (same entries, same digest rules)."""
    doc = json.loads(catalog_mod.CATALOG_PATH.read_text(encoding="utf-8"))
    doc["entries"] = [e for e in doc["entries"] if e["version"] in ("16.0", "17.0")]
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class FakeRemotes:
    """Metadata answers for `ls_remote`. An Enterprise remote can be made to reject the token."""

    def __init__(self):
        self.heads = {}
        self.calls = []
        self.reject_enterprise_token = False

    def ls_remote(self, repository, *, offline=False, credentials=None):
        self.calls.append((repository, credentials is not None))
        if repository == ENT_REPO and credentials is not None and self.reject_enterprise_token:
            raise RemoteGitError("AUTH_FAILED", None, "the remote rejected the credentials")
        return dict(self.heads[repository])


class UpdateOrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls._net = [mock.patch.object(socket, "socket", side_effect=AssertionError("network is disabled")),
                    mock.patch.object(socket, "create_connection", side_effect=AssertionError("network is disabled"))]
        for patch in cls._net:
            patch.start()
        cls.registries = build_registries()

    @classmethod
    def tearDownClass(cls):
        for patch in cls._net:
            patch.stop()
        cls._tmp.cleanup()

    def setUp(self):
        self.dir = self.base / self.id().rsplit(".", 1)[-1]
        self.dir.mkdir()
        self.home = self.dir / "kb"
        self.community = synth.build_synth_repo(self.dir / "community")
        self.enterprise = _enterprise_repo(self.dir / "enterprise")
        self.catalog = catalog_mod.load_catalog(_write_catalog(self.dir / "catalog.json"))
        self.remotes = FakeRemotes()
        self.bare = {"community": _bare_copy(Path(self.community.path), self.dir / "community.git"),
                     "enterprise": _bare_copy(self.dir / "enterprise", self.dir / "enterprise.git")}
        self._sync_remotes()
        self.token = credentials.Token(TOKEN)

    # --- helpers ----------------------------------------------------------------------------------------------------

    def _sync_remotes(self):
        self.remotes.heads[COM_REPO] = {"16.0": self.community.from_sha, "17.0": self.community.to_sha}
        self.remotes.heads[ENT_REPO] = {"16.0": self.enterprise["16.0"], "17.0": self.enterprise["17.0"]}

    def _repin(self):
        """Move the Community 17.0 branch to a new commit with the same tree (a changed revision)."""
        self.community_17 = _repin_community(self.community.path, self.community.to_sha)
        self.community.to_sha = self.community_17
        self.bare["community"] = _bare_copy(Path(self.community.path), self.dir / f"community-{self.community_17[:8]}.git")
        self._sync_remotes()
        self.remotes.heads[COM_REPO]["17.0"] = self.community_17

    def _transport(self, source_id):
        return self.bare["enterprise"] if source_id.startswith("odoo-enterprise-") else self.bare["community"]

    def _update(self, home=None, *, token=None, **kwargs):
        options = dict(toolkit=self.registries.extract_toolkit, catalog=self.catalog,
                       ls_remote=self.remotes.ls_remote, transport_for=self._transport, clock=_clock,
                       token=token)
        options.update(kwargs)
        return orch.run_update(self.home if home is None else home, **options)

    def _releases(self):
        return sorted(p.name for p in (self.home / "releases").iterdir()) if (self.home / "releases").is_dir() else []

    def _release_dir(self, release_id):
        return self.home / "releases" / release_id

    def _enterprise_rows(self, release: Path) -> dict:
        """The Enterprise-only content of a release: provenance entries, snapshot manifests, evidence and rules."""
        provenance = [e for e in _read(release / "provenance" / "sources.json") if e["source_id"] in ENT_IDS]
        snapshots = {e["snapshot_id"]: (release / SNAPSHOT_DIRNAME / f"{e['snapshot_id']}.json").read_bytes()
                     for e in provenance}
        evidence = {}
        for path in sorted((release / "knowledge" / "evidence").glob("EV-*.json")):
            record = _read(path)
            if record.get("source_id") in ENT_IDS:
                evidence[record["id"]] = record
        rules = {}
        for path in sorted((release / "knowledge" / "compatibility").glob("*.rules.json")):
            for rule in _read(path):
                cited = rule.get("evidence") or []
                if cited and all(eid in evidence for eid in cited):
                    rules[rule["id"]] = rule
        return {"provenance": provenance, "snapshots": snapshots, "evidence": evidence, "rules": rules}

    def _assert_no_token(self, root: Path):
        for path in root.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(TOKEN.encode(), data, f"token value found in {path.relative_to(root)}")

    # --- tests -------------------------------------------------------------------------------------------------------

    def test_fresh_community_only_install_activates_and_skips_enterprise(self):
        result = self._update()
        self.assertEqual(result.outcome, "ACTIVE", result.reasons)
        self.assertEqual(read_active(self.home)["release_id"], result.new_release)
        self.assertIsNone(result.previous_release)
        self.assertEqual(result.enterprise["status"], "SKIPPED_NO_CREDENTIALS")
        self.assertEqual(result.enterprise["freshness"], "NOT_INSTALLED")
        self.assertIn("migration support not established", result.limitations)
        self.assertIn("production certification not granted", result.limitations)
        self.assertGreater(result.changes["rules_added"], 0)

        release = self._release_dir(result.new_release)
        self.assertEqual({e["source_id"] for e in _read(release / "provenance" / "sources.json")}, {COM16, COM17})

        newest = UpdateHistory(self.home).read(limit=1)[0]
        self.assertEqual(newest["outcome"], "ACTIVE")
        self.assertEqual(sorted(newest["details"]["build_inputs"]["source_shas"]), [COM16, COM17])
        self.assertEqual(newest["details"]["build_inputs"]["parent_release_id"], result.new_release)
        self.assertRegex(newest["fingerprint"], r"^[0-9a-f]{64}$")

    def test_fresh_install_with_enterprise_token_builds_one_internal_release_with_both_families(self):
        result = self._update(token=self.token)
        self.assertEqual(result.outcome, "ACTIVE", result.reasons)
        release = self._release_dir(result.new_release)
        meta = _read(release / "release.json")
        self.assertEqual(meta["confidentiality"], "internal")
        self.assertEqual(sorted(s["source_id"] for s in meta["sources"]), sorted([COM16, COM17, ENT16, ENT17]))
        self.assertEqual(result.enterprise["status"], "ACQUIRED")
        self.assertEqual(result.enterprise["freshness"], "FRESH")
        self.assertIn((ENT_REPO, True), self.remotes.calls, "the Enterprise remote was read with the token")
        self.assertNotIn(TOKEN, json.dumps(result.to_dict()))
        self._assert_no_token(self.home)

    def test_unchanged_second_run_is_a_noop_with_no_new_release(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        releases_before = self._releases()
        second = self._update(token=self.token)
        self.assertEqual(second.outcome, "NOOP", second.reasons)
        self.assertEqual(self._releases(), releases_before)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(UpdateHistory(self.home).read(limit=1)[0]["outcome"], "NOOP")

    def test_changed_community_revision_activates_without_manual_supersede(self):
        first = self._update()
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()
        second = self._update()
        self.assertEqual(second.outcome, "ACTIVE", second.reasons)
        self.assertNotEqual(second.new_release, first.new_release)
        self.assertEqual(read_active(self.home)["release_id"], second.new_release)
        self.assertTrue(second.activation["allowed"])
        self.assertTrue(second.changes["superseded"], "the rotated rule ids are approved by the semantic policy")
        audit = (self.home / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("semantic replacement", audit)

    def test_community_only_update_carries_the_enterprise_release_byte_identically(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        first_rows = self._enterprise_rows(self._release_dir(first.new_release))
        self.assertTrue(first_rows["rules"] or first_rows["evidence"], "the Enterprise pair must contribute rows")

        self._repin()
        blocked = self._update(require_enterprise=True)
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertTrue(any("ENTERPRISE_REQUIRED_UNAVAILABLE" in r for r in blocked.reasons), blocked.reasons)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)

        second = self._update()
        self.assertEqual(second.outcome, "ACTIVE", second.reasons)
        self.assertEqual(second.enterprise["status"], "SKIPPED_NO_CREDENTIALS")
        self.assertEqual(second.enterprise["freshness"], "STALE_UNVERIFIED")
        self.assertIn("Enterprise freshness unverified (carried forward)", second.limitations)
        self.assertTrue(set(ENT_IDS) <= set(second.carried_forward), second.carried_forward)
        second_release = self._release_dir(second.new_release)
        second_rows = self._enterprise_rows(second_release)
        # Enterprise source records and Enterprise-only rules are byte-identical. An Enterprise evidence row also names the
        # rules that cite it; one of them is shared with Community and its id derives from the Community change, so a
        # Community revision moves that back-reference. The back-reference must still resolve in the new release.
        # The recorded `url` of a carried source is the declared allow-listed prefix (trailing slash); an acquired source
        # records the verified origin. Everything else in the provenance entry is identical.
        self.assertEqual([{k: v for k, v in e.items() if k != "url"} for e in second_rows["provenance"]],
                         [{k: v for k, v in e.items() if k != "url"} for e in first_rows["provenance"]])
        self.assertEqual(second_rows["snapshots"], first_rows["snapshots"])
        self.assertEqual(second_rows["rules"], first_rows["rules"])
        self.assertEqual({k: {f: v for f, v in r.items() if f != "rule_ids"} for k, r in second_rows["evidence"].items()},
                         {k: {f: v for f, v in r.items() if f != "rule_ids"} for k, r in first_rows["evidence"].items()})
        new_rule_ids = set()
        for path in (second_release / "knowledge" / "compatibility").glob("*.rules.json"):
            new_rule_ids |= {row["id"] for row in _read(path)}
        for record in second_rows["evidence"].values():
            self.assertTrue(set(record["rule_ids"]) <= new_rule_ids, record["rule_ids"])

    def test_tampered_retained_snapshot_fails_closed_and_keeps_the_previous_release(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        before = _tree(self._release_dir(first.new_release))
        retained = self.home / "staging" / "update" / "snapshots" / f"{ENT17}.json"
        altered = _read(retained)
        altered["snapshot_digest"] = "2" * 64
        retained.write_bytes(json.dumps(altered, sort_keys=True).encode("utf-8") + b"\n")
        self._repin()

        result = self._update()
        self.assertEqual(result.outcome, "FAILED", result.reasons)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(_tree(self._release_dir(first.new_release)), before)

    def test_missing_retained_snapshot_fails_closed_and_keeps_the_previous_release(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        before = _tree(self._release_dir(first.new_release))
        (self.home / "staging" / "update" / "snapshots" / f"{ENT16}.json").unlink()
        self._repin()

        result = self._update()
        self.assertEqual(result.outcome, "FAILED", result.reasons)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(_tree(self._release_dir(first.new_release)), before)
        self.assertNotIn(TOKEN, json.dumps(result.to_dict()))

    def test_rejected_enterprise_token_is_carried_and_reported(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()
        self.remotes.reject_enterprise_token = True

        result = self._update(token=self.token)
        self.assertEqual(result.outcome, "ACTIVE", result.reasons)
        self.assertEqual(result.enterprise["status"], "AUTH_FAILED")
        self.assertEqual(result.enterprise["freshness"], "STALE_UNVERIFIED")
        self.assertTrue(set(ENT_IDS) <= set(result.carried_forward), result.carried_forward)
        self.assertEqual(read_active(self.home)["release_id"], result.new_release)
        self._assert_no_token(self.home)

    def test_capability_losing_candidate_is_blocked_and_the_previous_release_stays_active(self):
        first = self._update()
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()
        real_evaluate = activation.evaluate

        def without_supersede(prev_dir, new_dir, **kwargs):
            # The rotated rule ids are removed from the candidate; with no approval they are capability losses.
            return real_evaluate(prev_dir, new_dir, **{**kwargs, "supersede": ()})

        with mock.patch.object(activation, "evaluate", side_effect=without_supersede):
            result = self._update()
        self.assertEqual(result.outcome, "BLOCKED", result.reasons)
        self.assertTrue(any(r.startswith("CAPABILITY_LOST") for r in result.reasons), result.reasons)
        self.assertEqual(result.activation["state"], "BLOCKED")
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(read_release_state(self._release_dir(result.new_release)).value, "INSTALLED")
        self.assertEqual(UpdateHistory(self.home).read(limit=1)[0]["outcome"], "BLOCKED")

    def test_enterprise_compatibility_finding_blocks_activation(self):
        first = self._update(token=self.token)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()
        finding = [{"module": ENT_MODULE, "missing": ["sale_demo"]}]
        with mock.patch.object(orch, "_enterprise_findings", return_value=finding):
            result = self._update()
        self.assertEqual(result.outcome, "BLOCKED", result.reasons)
        self.assertTrue(any(r.startswith("ENTERPRISE_COMPAT") for r in result.reasons), result.reasons)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(read_release_state(self._release_dir(result.new_release)).value, "INSTALLED")

    def test_fault_at_activation_rolls_back_and_a_retry_activates(self):
        first = self._update()
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()

        faulted = self._update(fault_at="pointer")
        self.assertEqual(faulted.outcome, "ROLLED_BACK", faulted.reasons)
        self.assertEqual(read_active(self.home)["release_id"], first.new_release)
        self.assertEqual(faulted.activation["state"], "ROLLED_BACK")
        self.assertEqual(UpdateHistory(self.home).read(limit=1)[0]["outcome"], "ROLLED_BACK")

        retry = self._update()
        self.assertEqual(retry.outcome, "ACTIVE", retry.reasons)
        self.assertEqual(read_active(self.home)["release_id"], retry.new_release)

    def test_dry_run_on_an_installed_home_changes_nothing(self):
        first = self._update()
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        self._repin()
        before = _tree(self.home)
        calls_before = len(self.remotes.calls)

        result = self._update(dry_run=True)
        self.assertEqual(result.outcome, "DRY_RUN", result.reasons)
        self.assertTrue(result.dry_run)
        self.assertIsNone(result.new_release)
        self.assertEqual(result.plan["decision"], "BUILD")
        self.assertGreater(len(self.remotes.calls), calls_before, "a dry run reads the remote metadata")
        self.assertEqual(_tree(self.home), before, "a dry run writes nothing to the kb-home")


if __name__ == "__main__":
    unittest.main()
