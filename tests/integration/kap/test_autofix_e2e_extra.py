"""Feature 012, Addendum F4 (extra cases): the automatic FIX pipeline on the cases the first autofix e2e left unexecuted.

Built on the same synthetic fixtures as `test_autofix_e2e` (its helpers are reused by import; no test class is re-run here):
the 16.0 -> 17.0 Community repository with the `odoo/` pairs, plus a synthetic Enterprise repository (its own `ent_core/`
package, renamed Enterprise addon) that carries an Enterprise-only replacement pair and keyword-changed pairs. The remote
is faked, the fetch goes to local bare repositories, sockets fail. The token is the dummy value of the orchestrator fixture.

Covered: (1) an Enterprise-sourced replacement pair in a unified Community+Enterprise update is FIX_ENABLED only in the
internal release, `migrate --fix` applies it, the package export is refused, and no Enterprise source text reaches the
release files; (2) keyword rename and keyword removal stay DETECT_ONLY with a coded reason; (3) edits from two certified
rules on one custom-module import line apply once, deterministically, and a second run is a no-op; (4) a corrupted retained
blob during a full update either demotes the rule or fails the update with the previous release still active; (5) an
AI-proposed pair and an insufficient-evidence pair stay DETECT_ONLY through a full update.

Synthetic only. Every kb-home and module is a temporary directory; the user's knowledge base is never touched.
"""

import ast
import contextlib
import io
import json
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.builtins import build_registries
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.candidates import ai_proposer as ap
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.release import safety
from odooflux.knowledge.release.store import read_active
from odooflux.knowledge.update import catalog as catalog_mod
from odooflux.knowledge.update import credentials
from odooflux.knowledge.update import orchestrator as orch
from tests.fixtures.kap import make_synth_repo as synth
from tests.integration.kap import test_autofix_e2e as base
from tests.integration.kap import test_update_orchestrator as ou

ENT_PATH = "ent_core/tools/helpers.py"
ENT_MODULE = "ent_core.tools.helpers"
ENT_MARKER = "90417263"  # a literal in the Enterprise bodies only; it must never reach a release file
ENT_HELPERS_16 = '''"""Synthetic Enterprise helpers (16.0)."""


def ent_old_round(value):
    """Round to two places."""
    return round(value + 90417263, 2)


def ent_kw_old(value, digits=2):
    """Round a value. Replaced by ``ent_kw_new``."""
    return round(value, digits)


def ent_sig(value, digits=2):
    return round(value, digits)
'''
ENT_HELPERS_17 = '''"""Synthetic Enterprise helpers (17.0)."""


def ent_new_round(value):
    """Round to two places. Replaces ``ent_old_round``."""
    return round(value + 90417263, 2)


def ent_kw_new(value, precision=2):
    """Round a value. Replaces ``ent_kw_old``."""
    return round(value, precision)


def ent_sig(value):
    return round(value, 2)
'''
MANIFEST = "{'name': 'fix_extra', 'version': '17.0.1.0.0', 'depends': [], 'installable': True}\n"
ENT_CALL_BEFORE = '''from ent_core.tools.helpers import ent_old_round


class EntSale(object):
    def action(self, x):
        return ent_old_round(x)
'''
ENT_CALL_AFTER = '''from ent_core.tools.helpers import ent_new_round


class EntSale(object):
    def action(self, x):
        return ent_new_round(x)
'''
KEYWORD_CALLS = '''from ent_core.tools.helpers import ent_kw_old, ent_sig


class EntKeywords(object):
    def run(self, x):
        return ent_kw_old(x, digits=3), ent_sig(x, digits=1)
'''
OVERLAP_BEFORE = '''from odoo.api import multi
from odoo.tools.helpers import legacy_sum, old_round


class Overlap(object):
    @multi
    def run(self, x):
        return legacy_sum(old_round(legacy_sum(old_round(x), 1)), old_round(2))
'''
OVERLAP_AFTER = '''from odoo.api import multi
from odoo.tools.helpers import new_sum, new_round


class Overlap(object):
    def run(self, x):
        return new_sum(new_round(new_sum(new_round(x), 1)), new_round(2))
'''
PLAIN_CALL = '''from odoo.tools.helpers import plain_old


class PlainUse(object):
    def run(self, x):
        return plain_old(x)
'''


def _enterprise_repo(dest: Path) -> dict:
    """Two-commit Enterprise clone: the renamed synthetic addon plus the `ent_core` helpers. Returns {version: sha}."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="autofix-ent-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        trees = {"16.0": {**ou._enterprise_tree(synth._TREE_16), ENT_PATH: ENT_HELPERS_16},
                 "17.0": {**ou._enterprise_tree(synth._TREE_17), ENT_PATH: ENT_HELPERS_17}}
        for version in ("16.0", "17.0"):
            env = synth._git_env(home, template, synth._DATES[version])
            tree = synth._write_tree(git_dir, env, trees[version])
            args = ["commit-tree", tree, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return shas


def _custom_module(root: Path, name: str, files: dict) -> Path:
    """A custom module under `root` whose models package holds `files` ({module name: source})."""
    mod = root / name
    (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text(MANIFEST, encoding="utf-8")
    (mod / "models" / "__init__.py").write_text("".join(f"from . import {m}\n" for m in files), encoding="utf-8")
    for module, text in files.items():
        (mod / "models" / f"{module}.py").write_text(text, encoding="utf-8")
    return mod


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class _World:
    """One synthetic Community (with the odoo/ pairs) and Enterprise repository pair, a catalog, a faked remote and the
    bare transports. Updates run through the real orchestrator; `repin` moves the Community 17.0 revision."""

    def __init__(self, registries, directory: Path):
        directory.mkdir(parents=True)
        self.dir = directory
        self.registries = registries
        self.com = base._two_version_repo(directory / "community")
        self.ent = _enterprise_repo(directory / "enterprise")
        self.catalog = catalog_mod.load_catalog(ou._write_catalog(directory / "catalog.json"))
        self.remotes = ou.FakeRemotes()
        self.bare = {}
        self.sync()
        self.bare["community"] = ou._bare_copy(Path(self.com.path), directory / "community.git")
        self.bare["enterprise"] = ou._bare_copy(directory / "enterprise", directory / "enterprise.git")

    def sync(self):
        self.remotes.heads[ou.COM_REPO] = {"16.0": self.com.from_sha, "17.0": self.com.to_sha}
        self.remotes.heads[ou.ENT_REPO] = {"16.0": self.ent["16.0"], "17.0": self.ent["17.0"]}

    def repin(self):
        self.com.to_sha = ou._repin_community(self.com.path, self.com.to_sha)
        self.bare["community"] = ou._bare_copy(Path(self.com.path), self.dir / f"community-{self.com.to_sha[:8]}.git")
        self.sync()

    def _transport(self, source_id):
        return self.bare["enterprise"] if source_id.startswith("odoo-enterprise-") else self.bare["community"]

    def update(self, home: Path, *, token=True):
        return orch.run_update(home, toolkit=self.registries.extract_toolkit, catalog=self.catalog,
                               ls_remote=self.remotes.ls_remote, transport_for=self._transport,
                               clock=base.FIXED_CLOCK,
                               token=credentials.Token(ou.TOKEN) if token else None)


class _UpdateFixture(unittest.TestCase):
    """Shared plumbing: network patched for the class, the registries built once; helpers read release files."""

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

    @staticmethod
    def _release_dir(home: Path, release_id: str) -> Path:
        return home / "releases" / release_id

    @staticmethod
    def _tree(home: Path, release_id: str) -> Path:
        return home / "releases" / release_id / "knowledge"

    @staticmethod
    def _confirmations(tree: Path) -> dict:
        return {_read(p)["subject"]["subject_key"]: _read(p) for p in sorted((tree / "confirmations").glob("*.json"))}

    @staticmethod
    def _rules(tree: Path) -> dict:
        rows = {}
        for path in sorted((tree / "compatibility").glob("*.rules.json")):
            for row in _read(path):
                rows[row["id"]] = row
        return rows

    @staticmethod
    def _ledger(home: Path, name: str) -> dict:
        return {e["subject_key"]: e for e in _read(home / "staging" / "update" / "ledgers" / name)["entries"]}

    @staticmethod
    def _migrate(module: Path, home: Path, state: Path, report=None):
        argv = ["migrate", "--module", str(module), "--kb-home", str(home), "--state-dir", str(state),
                "--from-version", "16", "--to-version", "17", "--fix"]
        if report is not None:
            argv += ["--report", str(report), "--report-format", "json"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(argv)
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def _tree_bytes(root: Path) -> dict:
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class UnifiedEnterpriseFixTests(_UpdateFixture):
    """One unified Community + Enterprise update (token present), shared by the tests of this class, and one Community-only
    update of the same inputs (no token)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.world = _World(cls.registries, cls.base / "sources")
        cls.home = cls.base / "kb"
        cls.result = cls.world.update(cls.home, token=True)
        cls.tree = cls._tree(cls.home, cls.result.new_release) if cls.result.new_release else None
        cls.community_only_home = cls.base / "kb-community-only"
        cls.community_only = cls.world.update(cls.community_only_home, token=False)

    def setUp(self):
        self.assertEqual(self.result.outcome, "ACTIVE", self.result.reasons)
        self.work = Path(tempfile.mkdtemp(prefix="extra-"))
        self.addCleanup(shutil.rmtree, self.work, True)

    # --- (1) Enterprise-sourced replacement pair ---------------------------------------------------------------------

    def test_enterprise_replacement_is_fix_enabled_only_in_the_internal_release(self):
        release = self._release_dir(self.home, self.result.new_release)
        meta = _read(release / "release.json")
        self.assertEqual(meta["confidentiality"], "internal")
        confirmations = self._confirmations(self.tree)
        record = confirmations["ent_core.ent_old_round"]
        self.assertEqual(record["derived_class"], "REPLACEMENT_CONFIRMED")
        row = self._rules(self.tree)[record["rule_id"]]
        self.assertEqual(row["maturity"], "FIX_ENABLED")
        self.assertIs(row["review_required"], False)
        self.assertEqual(row["fixer_ref"], "odooflux.rules.python.certified:rewrite_imported_symbol")
        self.assertEqual(row["params"]["module"], ENT_MODULE)
        self.assertEqual({s["source_id"] for s in record["sources"]}, {"odoo-enterprise-16.0", "odoo-enterprise-17.0"})
        # The Community-only update of the same inputs has no Enterprise pair at all.
        self.assertEqual(self.community_only.outcome, "ACTIVE", self.community_only.reasons)
        community_tree = self._tree(self.community_only_home, self.community_only.new_release)
        self.assertNotIn("ent_core.ent_old_round", self._confirmations(community_tree))
        self.assertEqual(
            [k for k in self._ledger(self.community_only_home, "16-17.json") if k.startswith("ent_core.")], [])

    def test_migrate_fix_applies_the_enterprise_replacement(self):
        module = _custom_module(self.work, "ent_fixture", {"ent_sale": ENT_CALL_BEFORE})
        code, _, err = self._migrate(module, self.home, self.work / "state")
        self.assertEqual(code, 0, err)
        self.assertEqual((module / "models" / "ent_sale.py").read_text(encoding="utf-8"), ENT_CALL_AFTER)

    def test_package_export_of_the_internal_release_is_refused(self):
        release = self._release_dir(self.home, self.result.new_release)
        target = self.work / "internal.ofkp"
        with self.assertRaises(PackageError) as raised:
            export_package(release, target)
        self.assertEqual(raised.exception.code, "EXPORT_REFUSED")
        self.assertFalse(target.exists())

    def test_no_enterprise_source_text_in_the_release_files(self):
        release = self._release_dir(self.home, self.result.new_release)
        # Sanity: the marker is real Enterprise source, held only in the retained store (never in a release).
        store_hits = [p for p in (self.home / "staging" / "update" / "store").rglob("*")
                      if p.is_file() and ENT_MARKER.encode() in p.read_bytes()]
        self.assertTrue(store_hits, "the Enterprise literal must be retained in the store for the check to mean anything")
        for path in sorted(p for p in release.rglob("*") if p.is_file()):
            self.assertNotIn(ENT_MARKER.encode(), path.read_bytes(), path.relative_to(release).as_posix())
        for path in sorted((self.tree / "confirmations").glob("*.json")) + sorted((self.tree / "certifications").glob("*.json")):
            self.assertNotIn("def ent_", path.read_text(encoding="utf-8"), path.name)
        for path in (release / "release.json",):
            self.assertNotIn("ent_old_round", path.read_text(encoding="utf-8"))

    # --- (2) keyword rename and keyword removal ----------------------------------------------------------------------

    def test_keyword_rename_and_removal_stay_detect_only_with_coded_reasons(self):
        ledger = self._ledger(self.home, "16-17.enterprise.json")
        refused = {r["change_id"]: r["code"] for r in self._output("06-candidates.json")["autofix_refused"]}
        rename = ledger["ent_core.ent_kw_old"]
        self.assertEqual(rename["class"], "REPLACEMENT_CANDIDATE")
        self.assertEqual(refused.get(rename["change_id"]), "S1_NOT_IDENTICAL")
        removal = ledger["ent_core.ent_sig"]
        self.assertEqual(removal["class"], "SIGNATURE_CHANGED")
        self.assertNotIn(removal["change_id"], refused)
        confirmed = self._confirmations(self.tree)
        self.assertNotIn("ent_core.ent_kw_old", confirmed)
        self.assertNotIn("ent_core.ent_sig", confirmed)
        self.assertIs(rename["confirmed"], False)
        self.assertIs(removal["confirmed"], False)

    def test_migrate_leaves_keyword_changed_calls_alone(self):
        module = _custom_module(self.work, "kw_fixture", {"kw_calls": KEYWORD_CALLS})
        before = self._tree_bytes(module)
        report = self.work / "kw-report.json"
        code, _, err = self._migrate(module, self.home, self.work / "state-kw", report=report)
        self.assertEqual(code, 0, err)
        self.assertEqual(self._tree_bytes(module), before)
        self.assertEqual(_read(report)["summary"]["edits"]["applied"], 0)

    def _output(self, name):
        return _read(self.home / "staging" / "update" / "steps" / name)["output"]

    # --- (3) overlapping edits on one custom-module file --------------------------------------------------------------

    def test_overlapping_edits_from_certified_rules_apply_once_and_deterministically(self):
        first = _custom_module(self.work / "a", "overlap_a", {"overlap": OVERLAP_BEFORE})
        second = _custom_module(self.work / "b", "overlap_b", {"overlap": OVERLAP_BEFORE})
        code_a, _, err_a = self._migrate(first, self.home, self.work / "state-a")
        code_b, _, err_b = self._migrate(second, self.home, self.work / "state-b")
        self.assertEqual((code_a, code_b), (0, 0), err_a + err_b)
        out_a = (first / "models" / "overlap.py").read_text(encoding="utf-8")
        self.assertEqual(out_a, OVERLAP_AFTER)
        ast.parse(out_a)
        self.assertEqual(out_a, (second / "models" / "overlap.py").read_text(encoding="utf-8"))
        again = self._tree_bytes(first)
        report = self.work / "again.json"
        code, _, err = self._migrate(first, self.home, self.work / "state-again", report=report)
        self.assertEqual(code, 0, err)
        self.assertEqual(self._tree_bytes(first), again)
        self.assertEqual(_read(report)["summary"]["edits"]["applied"], 0)

    # --- (5) AI-proposed pair and insufficient evidence ---------------------------------------------------------------

    def test_insufficient_evidence_pair_stays_detect_only(self):
        ledger = self._ledger(self.home, "16-17.json")
        plain = ledger["odoo.plain_old"]
        self.assertEqual(plain["class"], "RENAMED_CANDIDATE")
        self.assertIs(plain["confirmed"], False)
        self.assertNotIn("odoo.plain_old", self._confirmations(self.tree))
        for row in self._rules(self.tree).values():
            if "plain_old" in json.dumps(row):
                self.assertNotEqual(row["maturity"], "FIX_ENABLED", row["id"])
        module = _custom_module(self.work, "plain_fixture", {"plain_use": PLAIN_CALL})
        before = self._tree_bytes(module)
        self.assertEqual(self._migrate(module, self.home, self.work / "state-plain")[0], 0)
        self.assertEqual(self._tree_bytes(module), before)

    def test_ai_proposed_pair_is_recorded_and_changes_nothing_in_the_release(self):
        ledger = self._ledger(self.home, "16-17.json")
        entry = ledger["odoo.plain_old"]
        tree_before = self._tree_bytes(self.tree)
        candidate = {"candidate_id": "CR-ai-extra", "change_id": entry["change_id"], "status": "PROPOSED",
                     "rule": {"evidence": ["EV-AI-EXTRA"]}}
        evidence = [{"id": "EV-AI-EXTRA", "description": "plain_old may be replaced by plain_new",
                     "locations": [{"match": "plain_old"}]}]
        gateway = _FakeGateway(json.dumps({"rationale": "the names suggest a rename", "template_hint": ""}))
        result = ap.propose([candidate], evidence=evidence, changes={entry["change_id"]: entry},
                            gateway=gateway, authorizer=_AllowAll(), config=dict(AI_CONFIG), template_ids=[])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["proposals"]), 1)
        self.assertEqual(result["proposals"][0]["origin"], "AI_PROPOSED")
        self.assertEqual(self._tree_bytes(self.tree), tree_before, "an AI proposal writes nothing into the release")
        self.assertNotIn("odoo.plain_old", self._confirmations(self.tree))
        self.assertEqual([r for r in self._rules(self.tree).values() if r.get("origin") == "AI_PROPOSED"], [])


AI_CONFIG = {"enabled": True, "provider": "fake", "model": "fake-model", "kill_switch": False,
             "budget_job_tokens": 100000}


class _AllowAll:
    def missing(self, provider, categories):
        return []


class _Reply:
    def __init__(self, text):
        self.text = text
        self.error_kind = None
        self.stop_reason = "complete"
        self.usage = None


class _FakeGateway:
    """Duck-typed gateway: one scripted reply, no provider, no socket."""

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return _Reply(self.text)


class CorruptedRetainedBlobTests(_UpdateFixture):
    """(4) A corrupted retained blob during a full update.

    Corrupting the store before an update is caught at acquisition (the source checksum), so the update fails before any
    rule is proven; that is checked too. The L2 re-proof is reached only when the blob goes bad after the build proved it,
    so the blob is corrupted between the build and the activation decision (the decision is wrapped, nothing else is
    changed). The update must not activate; the previous release stays active and unchanged; no release that became
    active holds a FIX_ENABLED row whose sources do not re-prove."""

    def test_corrupted_blob_before_a_build_fails_closed_at_acquisition(self):
        world = _World(self.registries, self.base / "pre")
        home = self.base / "kb-pre"
        first = world.update(home)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        record = self._confirmations(self._tree(home, first.new_release))["odoo.old_round"]
        digest = next(s["blob_sha256"] for s in record["sources"] if s["side"] == "to")
        BlobStore(home / "staging" / "update" / "store").path_for(digest).write_bytes(b"corrupted")
        before = self._tree_bytes(home / "releases" / first.new_release)
        world.repin()
        second = world.update(home)
        self.assertEqual(second.outcome, "FAILED", second.reasons)
        self.assertIn("CHECKSUM_MISMATCH", " ".join(second.reasons))
        self.assertIsNone(second.new_release)
        self.assertEqual(read_active(home)["release_id"], first.new_release)
        self.assertEqual(self._tree_bytes(home / "releases" / first.new_release), before)

    def test_corrupted_blob_found_at_activation_blocks_and_keeps_the_previous_release(self):
        world = _World(self.registries, self.base / "post")
        home = self.base / "kb-post"
        first = world.update(home)
        self.assertEqual(first.outcome, "ACTIVE", first.reasons)
        before = self._tree_bytes(home / "releases" / first.new_release)
        store = home / "staging" / "update" / "store"
        digest = next(s["blob_sha256"] for s in self._confirmations(self._tree(home, first.new_release))
                      ["odoo.old_round"]["sources"] if s["side"] == "to")
        world.repin()

        real_evaluate = orch.activation.evaluate
        seen = {}

        def corrupt_then_decide(*args, **kwargs):
            BlobStore(store).path_for(digest).write_bytes(b"corrupted")  # after the build proved the blob
            decision = real_evaluate(*args, **kwargs)
            seen["blocking"] = [entry["code"] for entry in decision.blocking]
            return decision

        with mock.patch.object(orch.activation, "evaluate", side_effect=corrupt_then_decide):
            second = world.update(home)

        self.assertEqual(second.outcome, "BLOCKED", second.reasons)
        self.assertIsNotNone(second.new_release)
        self.assertNotEqual(second.new_release, first.new_release)
        self.assertTrue(seen["blocking"], "the activation decision must name the blocking finding")
        self.assertEqual(read_active(home)["release_id"], first.new_release)
        self.assertEqual(self._tree_bytes(home / "releases" / first.new_release), before)
        blocked = self._tree(home, second.new_release)
        self.assertNotEqual(read_active(home)["release_id"], second.new_release)
        # The blocked release is never activated. Its FIX_ENABLED rules re-prove against the store: the rule that cites the
        # corrupted blob does not; the others, whose blobs are intact, do.
        rules = self._rules(blocked)
        for record in self._confirmations(blocked).values():
            if rules[record["rule_id"]]["maturity"] != "FIX_ENABLED":
                continue
            cites = any(s["blob_sha256"] == digest for s in record["sources"])
            problems = safety.source_problems(blocked, record["rule_id"], store)
            self.assertEqual(bool(problems), cites, record["subject"]["subject_key"])


if __name__ == "__main__":
    unittest.main()
