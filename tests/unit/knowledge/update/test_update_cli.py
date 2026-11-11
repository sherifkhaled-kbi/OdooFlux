"""Feature 012 / Wave 3c: `odooflux knowledge update|status|history` (cli/kap_update.py) through `cli/knowledge.main`.

The orchestrator is replaced by a fake through the `kap_update._run_update` seam, so these tests never need it. Remotes
are never contacted: `socket.socket` and `subprocess.Popen` raise if anything tries. Dummy tokens must never appear in any
output. `status` and `history` are checked against real installed releases built with the check-CLI helpers, and the
kb-home tree digest must not change.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_update_cli.py' -t .
"""

import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from odooflux.cli import kap_update
from odooflux.cli.knowledge import main as knowledge_main
from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_active_knowledge, load_knowledge
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import ReleaseState
from odooflux.knowledge.release.resolver import clear_cache, resolve_knowledge
from odooflux.knowledge.release.store import set_release_state
from odooflux.knowledge.update import credentials as cred
from odooflux.knowledge.update.history import UpdateHistory
from odooflux.knowledge.update.model import UpdateResult
from odooflux.cli import kap_release
from odooflux.core.orchestrator import knowledge_rules as kr
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.experimental import registry as experimental_registry

FIXTURE_RELEASE = Path(__file__).resolve().parents[3] / "fixtures" / "kap" / "fixture_release"
TOKEN = "tok-TEST-1234567890"  # dummy
EXPERIMENTAL = kr.ExperimentalFixers(entries=experimental_registry.ENTRIES, modules=experimental_registry.MODULES)
# the composition root injects the read-time maturity function (builtins.build_context): same wiring here
TOOLKIT = SimpleNamespace(
    extract_toolkit=object(),
    rule_maturity=partial(kr.effective_maturity, modules=BINDABLE_MODULES, experimental=EXPERIMENTAL))
PREVIOUS = "rel-previous"
NEW = "rel-new"
DIGEST = "d" * 64
SHA_A = "a" * 40
SHA_B = "b" * 40
ENV_KEYS = ("ODOOFLUX_OFFLINE", "ODOOFLUX_KB_HOME", "ODOOFLUX_ENTERPRISE_TOKEN", "ODOOFLUX_ENTERPRISE_TOKEN_FILE",
            "ODOOFLUX_GIT_SECRET", "XDG_DATA_HOME")
META = {
    "label": "update-cli-fixture",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
UPDATE_SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "update_report.schema.json").read_text(encoding="utf-8"))
STATUS_SCHEMA = json.loads((KNOWLEDGE_ROOT / "schemas" / "knowledge_status.schema.json").read_text(encoding="utf-8"))
UNUSUAL = {"rules_added": 7, "rules_changed": 0, "rules_lost": 2, "rules_superseded": 3, "rules_downgraded": 5,
           "fix_enabled_added": 13}


def tree_snapshot(root: Path) -> dict:
    """Every path under `root` with its bytes (None for directories). Used to prove a verb writes nothing."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


def source(version, *, status="OK", remote=SHA_A, installed=SHA_B):
    return {"source_id": f"community-{version}", "edition": "community", "version": version, "remote_sha": remote,
            "installed_sha": installed, "status": status, "detail": ""}


def check_block(statuses=("SOURCE_REVISION_AVAILABLE",), sources=None):
    if sources is None:
        sources = [source("12.0"), source("13.0", installed=SHA_A)]
    return {"schema": "odooflux.knowledge-check/1", "statuses": list(statuses), "sources": sources,
            "new_versions": [], "affected_transitions": [], "enterprise_freshness": "FRESH",
            "catalog_digest": "c" * 64, "offline": False, "installed_release": PREVIOUS}


def make_result(outcome="ACTIVE", **overrides) -> UpdateResult:
    fields = dict(outcome=outcome, reasons=(), dry_run=outcome == "DRY_RUN", offline=False,
                  previous_release=PREVIOUS, new_release=NEW if outcome == "ACTIVE" else None,
                  release_digest=DIGEST, completeness="COMPLETE", check=check_block(), plan=None, acquisition=None,
                  build=None, activation={"state": "ACTIVE"} if outcome == "ACTIVE" else None, changes=dict(UNUSUAL),
                  carried_forward=(), enterprise={"status": "OK", "freshness": "FRESH"},
                  limitations=("limitation one", "limitation two"), history_seq=None)
    fields.update(overrides)
    return UpdateResult(**fields)


class FakeUpdate:
    """Stands in for orchestrator.run_update. Records the call and returns a fixed result."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, kb_home, **kwargs):
        self.calls.append((kb_home, kwargs))
        return self.result


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "kb"
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        for target, name in ((socket, "socket"), (subprocess, "Popen")):
            patcher = mock.patch.object(target, name, side_effect=AssertionError("no network or subprocess"))
            patcher.start()
            self.addCleanup(patcher.stop)
        clear_cache()
        self.addCleanup(clear_cache)

    def run_cli(self, argv, *, result=None, fake=None, registries=TOOLKIT):
        """Run through `cli/knowledge.main` with the real parser. Returns (code, stdout, stderr, fake)."""
        fake = fake if fake is not None else FakeUpdate(result if result is not None else make_result("NOOP"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(kap_update, "_run_update", fake), redirect_stdout(out), redirect_stderr(err):
            code = knowledge_main(argv, registries)
        return code, out.getvalue(), err.getvalue(), fake

    def install_release(self, revisions, *, completeness="COMPLETE") -> str:
        """A real INSTALLED and ACTIVE release (knowledge tree from the synthetic fixture) pinning `revisions`."""
        tree = self.root / "tree"
        shutil.copytree(FIXTURE_RELEASE, tree)
        (tree / "payload.txt").write_text("knowledge payload\n", encoding="utf-8")
        sources = [{"source_id": sid, "revision": rev, "snapshot_digest": "ab" * 32, "official": True,
                    "status": "VERIFIED", "origin_url": "https://github.com/odoo/odoo", "snapshot_id": f"snap-{i}"}
                   for i, (sid, rev) in enumerate(sorted(revisions.items()))]
        manifest = write_release_manifest(tree, dict(META, sources=sources, completeness=completeness))
        release_id = manifest["release_id"]
        self.home.mkdir(exist_ok=True)
        shutil.copytree(tree, self.home / "releases" / release_id)
        set_release_state(self.home, release_id, ReleaseState.INSTALLED)
        kap_release.activate(self.home, release_id)
        shutil.rmtree(tree)
        clear_cache()
        return release_id

    def record(self, **fields):
        base = {"outcome": "NOOP", "fingerprint": None, "previous_release": None, "new_release": None,
                "source_revisions": {}, "reason": None}
        base.update(fields)
        return UpdateHistory(self.home).append(base)


class UpdateHelpAndUsageTests(CliTestCase):
    def test_help_lists_every_update_flag(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = knowledge_main(["update", "--help"])
        self.assertEqual(code, 0)
        for flag in ("--dry-run", "--offline", "--from", "--to", "--require-enterprise", "--json", "--kb-home"):
            self.assertIn(flag, out.getvalue())

    def test_help_for_status_and_history(self):
        for verb, flags in (("status", ("--json", "--kb-home")), ("history", ("--json", "--limit", "--kb-home"))):
            with self.subTest(verb=verb):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = knowledge_main([verb, "--help"])
                self.assertEqual(code, 0)
                for flag in flags:
                    self.assertIn(flag, out.getvalue())

    def test_from_without_to_is_usage_error(self):
        code, _, err, fake = self.run_cli(["update", "--from", "12"])
        self.assertEqual(code, 2)
        self.assertIn("--from and --to", err)
        self.assertEqual(fake.calls, [])

    def test_to_without_from_is_usage_error(self):
        code, _, _, fake = self.run_cli(["update", "--to", "13"])
        self.assertEqual(code, 2)
        self.assertEqual(fake.calls, [])

    def test_non_numeric_or_non_positive_majors_are_usage_errors(self):
        for argv in (["update", "--from", "x", "--to", "13"], ["update", "--from", "0", "--to", "13"],
                     ["update", "--from", "12.0", "--to", "13"]):
            with self.subTest(argv=argv):
                code, _, _, fake = self.run_cli(argv)
                self.assertEqual(code, 2)
                self.assertEqual(fake.calls, [])

    def test_limit_must_be_a_positive_integer(self):
        for value in ("0", "-1", "many"):
            with self.subTest(value=value):
                code, out, _, _ = self.run_cli(["history", "--limit", value, "--kb-home", str(self.home)])
                self.assertEqual(code, 2)
                self.assertEqual(out, "")

    def test_missing_extract_toolkit_is_usage_error(self):
        code, _, err, fake = self.run_cli(["update", "--kb-home", str(self.home)], registries=None)
        self.assertEqual(code, 2)
        self.assertIn("extract toolkit", err)
        self.assertEqual(fake.calls, [])


class UpdateOutcomeTests(CliTestCase):
    def test_exit_codes_per_outcome(self):
        expected = {"NOOP": 0, "ACTIVE": 0, "DRY_RUN": 0, "BLOCKED": 1, "ROLLED_BACK": 3, "FAILED": 4}
        for outcome, code_expected in expected.items():
            with self.subTest(outcome=outcome):
                code, _, _, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=make_result(outcome))
                self.assertEqual(code, code_expected)

    def test_unavailable_comparison_makes_success_exit_4(self):
        for outcome in ("ACTIVE", "NOOP", "DRY_RUN"):
            with self.subTest(outcome=outcome):
                result = make_result(outcome, check=check_block(statuses=("CHECK_UNAVAILABLE",), sources=[]))
                code, _, _, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=result)
                self.assertEqual(code, 4)

    def test_human_output_numbers_come_from_the_result(self):
        result = make_result("ACTIVE")
        code, out, _, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=result)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("OdooFlux Knowledge Update\n"))
        self.assertIn("outcome: ACTIVE", out)
        self.assertIn("sources checked: 2 (compared 2)", out)
        self.assertIn("updated versions: 1 (12.0)", out)
        self.assertIn("  new detection rules: 7", out)
        self.assertIn("  updated rules: 0", out)
        self.assertIn("  new verified fixes: 13", out)
        self.assertIn("  removed/superseded rules: 5", out)
        self.assertIn("  unverified fixes: 5", out)
        self.assertIn(f"active release id: {NEW}", out)
        self.assertIn("production certification: NOT_GRANTED", out)
        self.assertIn("migration support: not established by an update", out)
        self.assertIn("  - limitation two", out)

    def test_unavailable_comparison_is_not_printed_as_zero(self):
        result = make_result("FAILED", check=None, changes=None, activation=None, new_release=None)
        code, out, _, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=result)
        self.assertEqual(code, 4)
        self.assertIn("updated versions: comparison unavailable", out)
        self.assertIn("knowledge changes:\n  not computed (no build ran)", out)

    def test_zero_changes_are_reported_as_zero(self):
        result = make_result("NOOP", check=check_block(sources=[source("12.0", installed=SHA_A)],
                                                       statuses=("NO_UPDATE",)),
                             changes=None, activation=None, new_release=None)
        code, out, _, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=result)
        self.assertEqual(code, 0)
        self.assertIn("updated versions: 0", out)
        self.assertNotIn("comparison unavailable", out)

    def test_json_output_is_the_result_dict_with_sorted_keys(self):
        result = make_result("BLOCKED", reasons=("capability regression",), new_release=None)
        code, out, _, _ = self.run_cli(["update", "--kb-home", str(self.home), "--json"], result=result)
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload, json.loads(json.dumps(result.to_dict())))
        self.assertEqual(list(payload), sorted(payload))
        self.assertEqual(v.check(payload, UPDATE_SCHEMA), [])

    def test_dry_run_and_require_enterprise_are_passed_through(self):
        _, _, _, fake = self.run_cli(["update", "--dry-run", "--require-enterprise", "--kb-home", str(self.home)],
                                     result=make_result("DRY_RUN"))
        kwargs = fake.calls[0][1]
        self.assertTrue(kwargs["dry_run"])
        self.assertTrue(kwargs["require_enterprise"])
        self.assertIs(kwargs["toolkit"], TOOLKIT.extract_toolkit)

    def test_from_to_pair_is_passed_as_only_pair(self):
        _, _, _, fake = self.run_cli(["update", "--from", "12", "--to", "13", "--kb-home", str(self.home)])
        self.assertEqual(fake.calls[0][1]["only_pair"], (12, 13))

    def test_default_kb_home_comes_from_the_environment(self):
        os.environ["ODOOFLUX_KB_HOME"] = str(self.home)
        _, _, _, fake = self.run_cli(["update"])
        self.assertEqual(Path(fake.calls[0][0]), self.home)


class UpdateNetworkAndTokenTests(CliTestCase):
    def test_offline_flag_passes_offline_and_no_token(self):
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        with mock.patch.object(cred, "resolve_enterprise_token", side_effect=AssertionError("no token read")):
            code, _, _, fake = self.run_cli(["update", "--offline", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        kwargs = fake.calls[0][1]
        self.assertTrue(kwargs["offline"])
        self.assertIsNone(kwargs["token"])

    def test_offline_environment_variable_is_honoured(self):
        os.environ["ODOOFLUX_OFFLINE"] = "1"
        _, _, _, fake = self.run_cli(["update", "--kb-home", str(self.home)])
        self.assertTrue(fake.calls[0][1]["offline"])
        self.assertIsNone(fake.calls[0][1]["token"])

    def test_online_run_passes_the_token_and_never_prints_it(self):
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        code, out, err, fake = self.run_cli(["update", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        token = fake.calls[0][1]["token"]
        self.assertIsNotNone(token)
        self.assertEqual(token.reveal(), TOKEN)
        self.assertFalse(fake.calls[0][1]["offline"])
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn(TOKEN, repr(token))

    def test_json_output_never_contains_the_token(self):
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        _, out, err, _ = self.run_cli(["update", "--kb-home", str(self.home), "--json"])
        self.assertNotIn(TOKEN, out + err)

    def test_a_result_that_echoes_the_token_is_masked(self):
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN"] = TOKEN
        leaking = make_result("BLOCKED", reasons=(f"fetch failed with {TOKEN}",))
        code, out, err, _ = self.run_cli(["update", "--kb-home", str(self.home)], result=leaking)
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, out + err)
        self.assertIn("reason: fetch failed with", out)

    def test_bad_token_file_is_a_warning_naming_the_class_only(self):
        secret_location = self.root / "secret-token-location-XYZ"
        os.environ["ODOOFLUX_ENTERPRISE_TOKEN_FILE"] = str(secret_location)
        code, out, err, fake = self.run_cli(["update", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertIsNone(fake.calls[0][1]["token"])
        self.assertIn("TOKEN_FILE_MISSING", err)
        self.assertNotIn("secret-token-location-XYZ", out + err)


class StatusTests(CliTestCase):
    def test_builtin_only_kb_home(self):
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0, err)
        self.assertIn("knowledge: built-in", out)
        self.assertIn("active release: none (built-in knowledge only)", out)
        self.assertIn("installed sources: none recorded", out)
        self.assertIn("last successful update: none recorded", out)
        self.assertIn("migration support not established", out)
        self.assertIn("production certification not granted", out)
        self.assertIn("Enterprise freshness unknown without a check", out)
        self.assertNotIn("knowledge completeness is PARTIAL", out)

    def test_builtin_json_matches_the_builtin_rule_count_and_schema(self):
        builtin_rules = [r for r in load_knowledge(KNOWLEDGE_ROOT).rules if isinstance(r, dict)]
        code, out, _, _ = self.run_cli(["status", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], "odooflux.knowledge-status/1")
        self.assertEqual(payload["kind"], "built-in")
        self.assertIsNone(payload["release_id"])
        self.assertEqual(payload["rules"]["total"], len(builtin_rules))
        self.assertEqual(v.check(payload, STATUS_SCHEMA), [])

    def test_installed_release_is_described_from_its_manifest(self):
        revisions = {"community-12.0": SHA_A, "community-13.0": SHA_B}
        release_id = self.install_release(revisions)
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0, err)
        self.assertIn("knowledge: external", out)
        self.assertIn(f"active release: {release_id}", out)
        self.assertIn(f"  community-12.0: {SHA_A}", out)
        self.assertIn(f"  community-13.0: {SHA_B}", out)
        self.assertIn("steps covered: none recorded", out)

    def test_installed_json_counts_come_from_the_effective_rules(self):
        self.install_release({"community-12.0": SHA_A})
        loaded = load_active_knowledge(resolve_knowledge(self.home))
        rules = [r for r in loaded.rules if isinstance(r, dict)]
        expected_total = len(rules)
        expected_fix = len([r for r in rules
                            if kr.effective_maturity(r, BINDABLE_MODULES, EXPERIMENTAL) == "FIX_ENABLED"])
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["rules"]["total"], expected_total)
        self.assertEqual(payload["rules"]["fix_enabled"], expected_fix)
        self.assertEqual(payload["installed_sources"], {"community-12.0": SHA_A})
        self.assertEqual(v.check(payload, STATUS_SCHEMA), [])

    def test_builtin_fix_enabled_counts_registry_bound_detect_only_rows(self):
        # AF-3: two DETECT_ONLY rows (16-17 attrs/states) bind a registry fixer, so they count as FIX_ENABLED
        stored = [r for r in load_knowledge(KNOWLEDGE_ROOT).rules if isinstance(r, dict)]
        stored_fix = sum(1 for r in stored if r.get("maturity") == "FIX_ENABLED")
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["rules"]["fix_enabled"], stored_fix + 2)
        self.assertEqual(sum(payload["rules"]["by_maturity"].values()), payload["rules"]["total"])
        self.assertEqual(payload["rules"]["by_maturity"]["DRAFT"], 3)
        self.assertIn("16-17.xml.attrs-removed", [r["id"] for r in stored if r.get("maturity") == "DETECT_ONLY"])

    def test_registry_bound_rows_are_disclosed_in_the_limitations(self):
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0, err)
        self.assertIn("fix-enabled rules: 12", out)
        self.assertIn("includes 2 DETECT_ONLY rule(s) bound to an experimental registry fixer", out)

    def test_partial_release_adds_the_completeness_limitation(self):
        self.install_release({"community-12.0": SHA_A}, completeness="PARTIAL")
        code, out, _, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertIn("knowledge completeness is PARTIAL", out)

    def test_status_shows_the_last_successful_update(self):
        self.install_release({"community-12.0": SHA_A})
        self.record(outcome="ACTIVE", new_release=NEW, previous_release=PREVIOUS,
                    source_revisions={"community-12.0": SHA_A})
        code, out, _, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertIn("last successful update:", out)
        self.assertIn(f"(release {NEW}, seq 1)", out)

    def test_invalid_active_pointer_exits_1_with_nothing_on_stdout(self):
        self.home.mkdir()
        (self.home / "active.json").write_text("{corrupt", encoding="utf-8")
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("ERROR: "))

    def test_broken_history_chain_exits_1(self):
        self.home.mkdir()
        self.record(outcome="NOOP", reason="first")
        history = self.home / "updates" / "history.jsonl"
        history.write_text(history.read_text(encoding="utf-8").replace("NOOP", "ACTIVE"), encoding="utf-8")
        code, out, err, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("update history is not valid", err)

    def test_status_never_writes_or_touches_the_network(self):
        self.install_release({"community-12.0": SHA_A})
        self.record(outcome="NOOP", reason="first")
        before = tree_snapshot(self.home)
        for extra in ([], ["--json"]):
            with self.subTest(extra=extra):
                code, _, _, _ = self.run_cli(["status", "--kb-home", str(self.home), *extra])
                self.assertEqual(code, 0)
                self.assertEqual(tree_snapshot(self.home), before)

    def test_builtin_status_does_not_create_anything(self):
        self.home.mkdir()
        before = tree_snapshot(self.home)
        code, _, _, _ = self.run_cli(["status", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertEqual(tree_snapshot(self.home), before)


class HistoryTests(CliTestCase):
    def test_empty_history(self):
        code, out, _, _ = self.run_cli(["history", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertIn("no update history recorded", out)
        code, out, _, _ = self.run_cli(["history", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["entries"], [])

    def populate(self):
        self.home.mkdir(exist_ok=True)
        self.record(outcome="NOOP", reason="nothing changed")
        self.record(outcome="ACTIVE", previous_release=PREVIOUS, new_release=NEW,
                    source_revisions={"community-12.0": SHA_A},
                    details={"changes": {"rules_added": 7, "fix_enabled_added": 13},
                             "activation": {"state": "ACTIVE"}})
        self.record(outcome="BLOCKED", previous_release=PREVIOUS, reason="capability regression")

    def test_populated_history_is_newest_first(self):
        self.populate()
        code, out, _, _ = self.run_cli(["history", "--kb-home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertLess(out.index("#3 "), out.index("#2 "))
        self.assertLess(out.index("#2 "), out.index("#1 "))
        self.assertIn("changes: fix_enabled_added=13, rules_added=7", out)
        self.assertIn("activation: ACTIVE", out)
        self.assertIn("failure reason: capability regression", out)

    def test_populated_json_rows(self):
        self.populate()
        code, out, _, _ = self.run_cli(["history", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["schema"], "odooflux.knowledge-history/1")
        self.assertEqual(payload["chain"], "verified")
        self.assertEqual([row["outcome"] for row in payload["entries"]], ["BLOCKED", "ACTIVE", "NOOP"])
        self.assertEqual(payload["entries"][0]["failure_reason"], "capability regression")
        self.assertEqual(payload["entries"][1]["changes"], {"rules_added": 7, "fix_enabled_added": 13})
        self.assertEqual(payload["entries"][1]["activation"], {"state": "ACTIVE"})
        self.assertEqual(payload["entries"][1]["source_revisions"], {"community-12.0": SHA_A})

    def test_limit_keeps_the_newest_entries(self):
        self.populate()
        code, out, _, _ = self.run_cli(["history", "--kb-home", str(self.home), "--json", "--limit", "2"])
        self.assertEqual(code, 0)
        self.assertEqual([row["seq"] for row in json.loads(out)["entries"]], [3, 2])

    def test_broken_chain_exits_1_and_prints_nothing_as_valid(self):
        self.populate()
        history = self.home / "updates" / "history.jsonl"
        for label, damaged in (
            ("edited line", history.read_text(encoding="utf-8").replace("nothing changed", "edited")),
            ("garbage line", history.read_text(encoding="utf-8") + "not json\n"),
        ):
            with self.subTest(label=label):
                history.write_text(damaged, encoding="utf-8")
                for extra in ([], ["--json"]):
                    code, out, err, _ = self.run_cli(["history", "--kb-home", str(self.home), *extra])
                    self.assertEqual(code, 1)
                    self.assertEqual(out, "")
                    self.assertIn("update history is not valid", err)
                self.populate_reset()

    def populate_reset(self):
        shutil.rmtree(self.home / "updates")
        self.populate()

    def test_history_never_writes(self):
        self.populate()
        before = tree_snapshot(self.home)
        code, _, _, _ = self.run_cli(["history", "--kb-home", str(self.home), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(tree_snapshot(self.home), before)


if __name__ == "__main__":
    unittest.main()
