"""TST-011-071 (REQ-KAP-029, 034, 032, 009): the full release pipeline on synthetic 16.0 to 17.0 repositories, offline.

Variants (each is a separate repository and kb-home; nothing shared is edited):
- B plain fixture: PARTIAL, the named limits G-FILES (broken_hooks.py FAILED, demo_widget.js UNSUPPORTED) and G-DISP.
- A clean fixture (JS and parse-error files removed on both sides): the pipeline reaches COMPLETE only after every
  unresolved change is triaged; before triage the only limit is G-DISP.
- C missing required source: STOPPED at step 1, nothing installed.
- D unsupported file only (the parse-error file removed): PARTIAL, the limit names demo_widget.js only.
- E the eight metrics printed by `coverage show --release`.
- F export of the built PARTIAL release, import into a second kb-home with default flags, verification and Gate 1.

Triage (variants A and D) is a test-local disposition of the changes the generator did not settle, written with the
ledger API (NO_CUSTOM_MODULE_IMPACT with a rationale). It is triage, not approval. The pipeline is stopped after step 6
and resumed from step 7, so the ledger edit happens before any release is published.
Sockets are patched to fail for the whole module.
"""

import contextlib
import io
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
from odooflux.cli import knowledge as cli
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.sources import load_allow_list
from odooflux.knowledge.extract import driver
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.release.manifest import verify_release_tree
from odooflux.knowledge.release.model import builtin_handle
from odooflux.knowledge.release.safety import fix_gate_findings
from odooflux.knowledge.release.store import list_installed
from tests.fixtures.kap import make_synth_repo as synth

CREATED = "2026-11-08T10:00:00Z"
JS_PATH = f"{synth.ADDON}/static/src/js/demo_widget.js"
BROKEN_PATH = f"{synth.ADDON}/models/broken_hooks.py"
TRIAGE_RATIONALE = "test triage: no custom-module impact for this synthetic change (not an approval)"


def _spec(sid, url, revision, branch):
    return {
        "source_id": sid, "kind": "GIT_COMMUNITY", "official": False, "url": url, "licence_access": "PUBLIC_OPEN",
        "licence_id": "LGPL-3", "branch": branch, "revision": revision,
        "scope": {"modules": "all", "include": [], "exclude": [], "file_kinds": []}, "retrieved_at": None,
        "checksum": None, "status": "DECLARED", "failure_reason": None, "required": True,
    }


def _build_variant(dest: Path, drop=()):
    """The synthetic 16.0 and 17.0 commits with the paths in `drop` removed from both trees (same commit recipe as
    `make_synth_repo.build_synth_repo`, which is not edited)."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="kap-variant-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        for version, tree in (("16.0", synth._TREE_16), ("17.0", synth._TREE_17)):
            files = {path: data for path, data in tree.items() if path not in drop}
            env = synth._git_env(home, template, synth._DATES[version])
            tree_sha = synth._write_tree(git_dir, env, files)
            args = ["commit-tree", tree_sha, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return str(dest), shas["16.0"], shas["17.0"]


class PipelineEndToEnd(unittest.TestCase):
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

    def _plan(self, repo_path, from_sha, to_sha, label, *, from_path=None):
        local = "local:" + repo_path
        toolkit = self.registries.extract_toolkit
        registry = full_registry()

        def extract(from_snap, to_snap, step, store):
            result = driver.extract_pair(from_snap, to_snap, None, registry, store=store, step=step, toolkit=toolkit)
            return result.drafts, result.accounting

        return pl.BuildPlan(
            label=label,
            specs=[_spec("odoo-community-16.0", ("local:" + from_path) if from_path else local, from_sha, "16.0"),
                   _spec("odoo-community-17.0", local, to_sha, "17.0")],
            pairs=[{"step": "16-17", "from": "odoo-community-16.0", "to": "odoo-community-17.0"}],
            base_tree=builtin_handle().root, adapters={"GIT_COMMUNITY": GitLocalAdapter("GIT_COMMUNITY")},
            extract=extract, known_detectors=toolkit.detectors, created_at=CREATED, checked_on="2026-11-08",
            author="e2e", tool_version="0.2.0", allow_list=load_allow_list(),
            source_meta={"odoo-community-16.0": {"repository": "odoo/odoo"},
                         "odoo-community-17.0": {"repository": "odoo/odoo"}})

    def _home(self, name):
        return self.base / name / "kb-home"

    def _triage(self, home, label):
        """Settle every change the generator left UNRESOLVED (test triage, rationale recorded)."""
        path = home / "staging" / label / "ledgers" / "16-17.json"
        ledger = Ledger.load(path)
        for cid in ledger.unresolved():
            ledger.mutate(cid, actor="TRIAGE", action="set_disposition", from_value="UNRESOLVED",
                          to_value="NO_CUSTOM_MODULE_IMPACT",
                          update={"disposition": "NO_CUSTOM_MODULE_IMPACT",
                                  "disposition_data": {"rule_ids": [], "evidence_ids": [],
                                                       "rationale": TRIAGE_RATIONALE, "reviewer": "e2e-triage",
                                                       "decided_at": CREATED}})
        self.assertEqual(Ledger.load(path).verify(), [])
        ledger.save(path)

    def _build_with_triage(self, plan, home):
        """Steps 1 to 6, triage of what remains UNRESOLVED, then resume from step 7 (the release is published only
        after the triage, so nothing is moved out of staging before it)."""
        first = pl.run_build(home, plan, steps=list(pl.REAL_STEPS)[:6])
        self.assertEqual(first.outcome, "OK", first.message)
        self._triage(home, plan.label)
        return pl.run_build(home, plan, from_step=7)

    def _manifest(self, release_dir):
        return json.loads((release_dir / "coverage" / "coverage-manifest.json").read_text(encoding="utf-8"))

    def _cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv), self.registries)
        return code, out.getvalue(), err.getvalue()

    def _limits_text(self, release_dir):
        return " | ".join(self._manifest(release_dir)["limits"])


class TestBuildVariants(PipelineEndToEnd):
    def test_b_plain_fixture_partial_with_named_limits(self):
        repo = synth.build_synth_repo(self.base / "b" / "repo")
        home = self._home("b")
        result = pl.run_build(home, self._plan(repo.path, repo.from_sha, repo.to_sha, "plain-b"))
        self.assertEqual(result.outcome, "OK", result.message)
        self.assertEqual(result.completeness, "PARTIAL")
        release = home / "releases" / result.release_id
        manifest = self._manifest(release)
        gates = {g["gate_id"]: g for g in manifest["gates"]}
        self.assertEqual(gates["G-FILES"]["status"], "FAIL")
        self.assertEqual(set(gates["G-FILES"]["reason_codes"]), {"FILES_FAILED", "FILES_UNSUPPORTED"})
        self.assertEqual(gates["G-DISP"]["status"], "FAIL")
        limits = manifest["limits"]
        self.assertTrue(any(l.startswith("G-FILES") and "broken_hooks.py" in l and "demo_widget.js" in l for l in limits))
        self.assertTrue(any(l.startswith("G-DISP") for l in limits))
        self.assertEqual(manifest["completeness"], "PARTIAL")
        self.assertEqual(list_installed(home)[0].state.value, "INSTALLED")
        self.assertFalse((home / "active.json").exists())

    def test_a_clean_fixture_complete_only_after_triage(self):
        path, from_sha, to_sha = _build_variant(self.base / "a" / "repo", drop=(JS_PATH, BROKEN_PATH))
        home = self._home("a")
        plan = self._plan(path, from_sha, to_sha, "clean-a")
        first = pl.run_build(home, plan, steps=list(pl.REAL_STEPS)[:6])
        self.assertEqual(first.outcome, "OK", first.message)
        self.assertEqual(first.rows[-1]["name"], "candidates")
        # Before triage the only blocking gate that fails is G-DISP (no G-FILES limit: every file is analysed).
        pre = pl.run_build(home, plan, from_step=7, dry_run=True)
        self.assertTrue(all(row["action"] == "RUN" for row in pre.rows if row["number"] >= 7))
        self._triage(home, plan.label)
        result = pl.run_build(home, plan, from_step=7)
        self.assertEqual(result.outcome, "OK", result.message)
        self.assertEqual(result.completeness, "COMPLETE", result.message)
        manifest = self._manifest(home / "releases" / result.release_id)
        self.assertEqual(manifest["limits"], [])
        self.assertTrue(all(g["status"] in ("PASS", "WARN") for g in manifest["gates"]))
        self.assertIn("test triage:", json.dumps(Ledger.load(
            home / "staging" / plan.label / "ledgers" / "16-17.json").records()))

    def test_c_missing_required_source_failed_nothing_installed(self):
        repo = synth.build_synth_repo(self.base / "c" / "repo")
        home = self._home("c")
        plan = self._plan(repo.path, repo.from_sha, repo.to_sha, "missing-c",
                          from_path=str(self.base / "c" / "no-such-clone"))
        result = pl.run_build(home, plan)
        self.assertEqual(result.outcome, "STOPPED")
        self.assertEqual((result.stopped_at, result.code), (1, "SOURCE_REQUIRED_FAILED"))
        self.assertEqual(list_installed(home), [])
        self.assertFalse((home / "releases").exists() and any((home / "releases").iterdir()))

    def test_d_unsupported_file_only_partial_names_it(self):
        path, from_sha, to_sha = _build_variant(self.base / "d" / "repo", drop=(BROKEN_PATH,))
        home = self._home("d")
        plan = self._plan(path, from_sha, to_sha, "unsupported-d")
        result = self._build_with_triage(plan, home)
        self.assertEqual(result.outcome, "OK", result.message)
        self.assertEqual(result.completeness, "PARTIAL")
        limits = self._manifest(home / "releases" / result.release_id)["limits"]
        self.assertEqual(len(limits), 1, limits)
        self.assertTrue(limits[0].startswith("G-FILES FILES_UNSUPPORTED"))
        self.assertIn("demo_widget.js", limits[0])

    def test_e_eight_metrics_printed_for_release(self):
        repo = synth.build_synth_repo(self.base / "e" / "repo")
        home = self._home("e")
        result = pl.run_build(home, self._plan(repo.path, repo.from_sha, repo.to_sha, "metrics-e"))
        self.assertEqual(result.outcome, "OK", result.message)
        code, out, err = self._cli("coverage", "show", "--release", result.release_id, "--kb-home", str(home))
        self.assertEqual(code, 0, out + err)
        metric_lines = [line for line in out.splitlines() if re.match(r"^M[1-8] ", line)]
        self.assertEqual([line.split()[0] for line in metric_lines], [f"M{i}" for i in range(1, 9)])
        self.assertIn("completeness PARTIAL", out)

    def test_f_export_import_second_home_verifies_gate_one(self):
        repo = synth.build_synth_repo(self.base / "f" / "repo")
        home = self._home("f")
        result = pl.run_build(home, self._plan(repo.path, repo.from_sha, repo.to_sha, "export-f"))
        self.assertEqual(result.outcome, "OK", result.message)
        release = home / "releases" / result.release_id
        package = export_package(release, self.base / "f" / "release.ofkp")

        # The pipeline never produces FIX_ENABLED rules. The release does carry the built-in FIX_ENABLED rules (the
        # parent content, note 4: built-ins have no provenance), so Gate 1 (P10) refuses them by default.
        fix_rules = []
        for path in (release / "knowledge" / "compatibility").glob("*.rules.json"):
            fix_rules += [r for r in json.loads(path.read_text(encoding="utf-8")) if r.get("maturity") == "FIX_ENABLED"]
        self.assertTrue(fix_rules)
        self.assertTrue(all(r.get("origin") in (None, "BUILTIN") for r in fix_rules), "no pipeline-made FIX_ENABLED")

        second = self.base / "f" / "kb-second"
        with self.assertRaises(PackageError) as ctx:
            import_package(package.path, second)
        self.assertEqual(ctx.exception.code, "P10")
        refused = {r["id"] for r in fix_rules}
        self.assertTrue(all(rid in str(ctx.exception) for rid in refused))
        self.assertEqual(list((second / "releases").iterdir()), [], "a refused import installs nothing")
        self.assertFalse((second / "active.json").exists())

        imported = import_package(package.path, second, downgrade_unverified=True)
        self.assertTrue(imported.installed)
        self.assertEqual(set(imported.downgraded_rules), refused)
        installed = second / "releases" / imported.release_id
        self.assertEqual(verify_release_tree(installed), [])
        self.assertEqual(fix_gate_findings(installed / "knowledge"), [])
        for path in (installed / "knowledge" / "compatibility").glob("*.rules.json"):
            for rule in json.loads(path.read_text(encoding="utf-8")):
                self.assertNotEqual(rule.get("maturity"), "FIX_ENABLED", rule.get("id"))

if __name__ == "__main__":
    unittest.main()
