"""Feature 012, Addendum F4: the automatic FIX pipeline end to end, on synthetic local git repositories.

A synthetic 16.0 -> 17.0 Community repository carries an `odoo/` package with one pair per soundness class (F1):
S1 a documented, body-identical replacement (`old_round` -> `new_round`), S2 a delegating alias with a deprecation
warning (`legacy_sum` -> `new_sum`), S3 an identity decorator that is removed (`multi`). Decoys must stay DETECT_ONLY with
a coded reason: a module-constant reference (`const_old`), a body that differs (`diff_old`), a non-identity decorator
(`tracked`), and a similarity-only rename without a docs hint (`plain_old`).

`knowledge update` builds and activates the release through the real pipeline, offline: the remote is faked, the fetch
goes to local bare repositories and sockets are patched. Then `migrate --fix` runs on a small custom module through the
real CLI and engine path. Tamper cases copy the activated release and check the loader (load), the package predicate
(import) and the blob re-proof (build and pre-activation).

Synthetic only. Every kb-home and module is a temporary directory; the user's knowledge base is never touched.
"""

import contextlib
import io
import json
import shutil
import socket
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.builtins import build_registries
from odooflux.knowledge.authoring import promote as pr
from odooflux.knowledge.loader import load_active_knowledge
from odooflux.knowledge.release import safety
from odooflux.knowledge.release.model import KnowledgeHandle
from odooflux.knowledge.release.store import read_active
from odooflux.knowledge.update import catalog as catalog_mod
from odooflux.knowledge.update import orchestrator as orch
from tests.fixtures.kap import make_synth_repo as synth
from tests.integration.kap.test_update_orchestrator import COM_REPO, FakeRemotes, _bare_copy, _clock, _write_catalog

FIXED_CLOCK = lambda: "2026-11-09T10:00:00Z"  # noqa: E731  (a rebuild is compared byte for byte, so the clock is fixed)

HELPERS_16 = '''"""Synthetic helpers (16.0)."""

RATE = 2


def old_round(value):
    """Round to two places."""
    return round(value, 2)


def plain_old(value):
    return round(value, 2)


def const_old(value):
    return round(value * RATE, 2)


def diff_old(value):
    """Round to two places."""
    return round(value, 2)


def legacy_sum(a, b):
    return a + b
'''

HELPERS_17 = '''"""Synthetic helpers (17.0)."""
import warnings

RATE = 2


def new_round(value):
    """Round to two places. Replaces ``old_round``."""
    return round(value, 2)


def plain_new(value):
    return round(value, 2)


def const_new(value):
    """Replaces ``const_old``."""
    return round(value * RATE, 2)


def diff_new(value):
    """Replaces ``diff_old``."""
    return round(value, 3)


def new_sum(a, b):
    return a + b


def legacy_sum(a, b):
    """Deprecated alias of new_sum."""
    warnings.warn("legacy_sum is deprecated", DeprecationWarning, stacklevel=2)
    return new_sum(a, b)
'''

API_16 = '''"""Synthetic api helpers (16.0)."""


def multi(method):
    """Identity decorator kept for compatibility."""
    return method


def tracked(method):
    method.tracked = True
    return method


def model(method):
    return method
'''

API_17 = '''"""Synthetic api helpers (17.0)."""


def model(method):
    return method
'''

ODOO_16 = {"odoo/tools/helpers.py": HELPERS_16, "odoo/api.py": API_16}
ODOO_17 = {"odoo/tools/helpers.py": HELPERS_17, "odoo/api.py": API_17}
FIX_SUBJECTS = {"odoo.old_round": "REPLACEMENT_CONFIRMED", "odoo.legacy_sum": "DELEGATING_ALIAS",
                "odoo.multi": "IDENTITY_DECORATOR_REMOVED"}
DECOY_REASONS = {"odoo.const_old": "S1_GLOBAL_REF", "odoo.diff_old": "S1_NOT_IDENTICAL",
                 "odoo.tracked": "S3_NOT_IDENTITY"}
DECOY_SUBJECTS = ("odoo.plain_old", "odoo.const_old", "odoo.diff_old", "odoo.tracked")
FIX_BINDING = {"REPLACEMENT_CONFIRMED": "rewrite_imported_symbol", "DELEGATING_ALIAS": "rewrite_imported_symbol",
               "IDENTITY_DECORATOR_REMOVED": "remove_imported_decorator"}

# The custom module the migrate run fixes (16 -> 17). Expected text is written out below, not derived from the engine.
MODULE_MANIFEST = "{'name': 'fix_fixture', 'version': '17.0.1.0.0', 'depends': [], 'installable': True}\n"
SALE_BEFORE = '''from odoo import api
from odoo.api import multi
from odoo.tools.helpers import legacy_sum, old_round


class SaleFixture(object):
    @multi
    def action(self, x):
        """Mentions old_round in a docstring."""
        note = "old_round is replaced"  # comment: old_round
        return legacy_sum(old_round(x), 1)
'''
SALE_AFTER = '''from odoo import api
from odoo.api import multi
from odoo.tools.helpers import new_sum, new_round


class SaleFixture(object):
    def action(self, x):
        """Mentions old_round in a docstring."""
        note = "old_round is replaced"  # comment: old_round
        return new_sum(new_round(x), 1)
'''
SHADOW = '''from odoo.tools.helpers import old_round


def old_round(x):
    return x
'''


def _two_version_repo(dest: Path) -> types.SimpleNamespace:
    """A 16.0 -> 17.0 repository: the synthetic Community trees plus the `odoo/` pairs above."""
    dest.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix="autofix-repo-"))
    try:
        home, template = scratch / "home", scratch / "template"
        home.mkdir()
        template.mkdir()
        init_env = synth._git_env(home, template, "")
        subprocess.run(["git", "init", "-q", str(dest)], env=init_env, check=True, capture_output=True)
        git_dir = dest / ".git"
        parent, shas = None, {}
        for version, trees in (("16.0", {**synth._TREE_16, **ODOO_16}), ("17.0", {**synth._TREE_17, **ODOO_17})):
            env = synth._git_env(home, template, synth._DATES[version])
            tree = synth._write_tree(git_dir, env, trees)
            args = ["commit-tree", tree, "-m", synth._MESSAGES[version]] + (["-p", parent] if parent else [])
            sha = synth._run(args, env, git_dir)
            synth._run(["update-ref", f"refs/heads/{version}", sha], env, git_dir)
            shas[version] = sha
            parent = sha
        synth._run(["symbolic-ref", "HEAD", "refs/heads/17.0"], init_env, git_dir)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return types.SimpleNamespace(path=str(dest), from_sha=shas["16.0"], to_sha=shas["17.0"])


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _module(root: Path) -> Path:
    """A fresh custom module (the fixture of the fix run) under `root`."""
    mod = root / "fix_fixture"
    (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text(MODULE_MANIFEST, encoding="utf-8")
    (mod / "models" / "__init__.py").write_text("from . import sale\nfrom . import shadow\n", encoding="utf-8")
    (mod / "models" / "sale.py").write_text(SALE_BEFORE, encoding="utf-8")
    (mod / "models" / "shadow.py").write_text(SHADOW, encoding="utf-8")
    return mod


class ReleaseFixture(unittest.TestCase):
    """Two `knowledge update` runs on the two-version repository (same inputs, same fixed clock), shared by the test classes.
    No test methods here: subclasses carry the tests, so the builds run once per class."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls._net = [mock.patch.object(socket, "socket", side_effect=AssertionError("network is disabled")),
                    mock.patch.object(socket, "create_connection", side_effect=AssertionError("network is disabled"))]
        for patch in cls._net:
            patch.start()
        cls.registries = build_registries()
        cls.repo = _two_version_repo(cls.base / "community")
        cls.catalog = catalog_mod.load_catalog(_write_catalog(cls.base / "catalog.json"))
        cls.remotes = FakeRemotes()
        cls.remotes.heads[COM_REPO] = {"16.0": cls.repo.from_sha, "17.0": cls.repo.to_sha}
        cls.bare = _bare_copy(Path(cls.repo.path), cls.base / "community.git")
        cls.home = cls.base / "kb"
        cls.result = cls._update(cls.home, clock=FIXED_CLOCK)
        cls.home_again = cls.base / "kb-again"
        cls.result_again = cls._update(cls.home_again, clock=FIXED_CLOCK)

    @classmethod
    def tearDownClass(cls):
        for patch in cls._net:
            patch.stop()
        cls._tmp.cleanup()

    @classmethod
    def _update(cls, home, *, clock=_clock):
        return orch.run_update(home, toolkit=cls.registries.extract_toolkit, catalog=cls.catalog,
                               ls_remote=cls.remotes.ls_remote, transport_for=lambda sid: cls.bare, clock=clock,
                               token=None)

    # --- helpers ----------------------------------------------------------------------------------------------------

    def release_dir(self, home=None, result=None):
        result = result or self.result
        return (home or self.home) / "releases" / result.new_release

    def tree(self):
        return self.release_dir() / "knowledge"

    def rules(self, tree=None):
        rows = {}
        for path in sorted(((tree or self.tree()) / "compatibility").glob("*.rules.json")):
            for row in _read(path):
                rows[row["id"]] = row
        return rows

    def confirmations(self, tree=None):
        folder = (tree or self.tree()) / "confirmations"
        return {_read(p)["subject"]["subject_key"]: _read(p) for p in sorted(folder.glob("*.json"))}

    def migrate(self, module: Path, *, home=None, state=None, report=None):
        argv = ["migrate", "--module", str(module), "--kb-home", str(home or self.home), "--state-dir",
                str(state), "--from-version", "16", "--to-version", "17", "--fix"]
        if report is not None:
            argv += ["--report", str(report), "--report-format", "json"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(argv)
        return code, out.getvalue(), err.getvalue()

    def step_output(self, name, home=None):
        return _read(((home or self.home) / "staging" / "update" / "steps" / name))["output"]

class AutofixEndToEndTests(ReleaseFixture):
    """The build, the rules, the ledger audit, the decoys and `migrate --fix`."""

    # --- the build ---------------------------------------------------------------------------------------------------

    def test_update_activates_a_release(self):
        self.assertEqual(self.result.outcome, "ACTIVE", self.result.reasons)
        self.assertEqual(read_active(self.home)["release_id"], self.result.new_release)

    def test_fix_pairs_are_fix_enabled_with_automatic_certification(self):
        rules = self.rules()
        confirmations = self.confirmations()
        self.assertEqual(set(confirmations), set(FIX_SUBJECTS))
        for subject, derived in FIX_SUBJECTS.items():
            record = confirmations[subject]
            self.assertEqual(record["derived_class"], derived)
            row = rules[record["rule_id"]]
            self.assertEqual(row["maturity"], "FIX_ENABLED", subject)
            self.assertIs(row["review_required"], False)
            self.assertEqual(row["fixer_ref"], f"odooflux.rules.python.certified:{FIX_BINDING[derived]}")
            self.assertEqual(row["params"], record["derived_params"])
            cert = _read(self.tree() / "certifications" / f"{record['rule_id']}.json")
            self.assertEqual(cert["change_class"], derived)
            self.assertEqual(row["approval"], f"auto-cert:{cert['policy_version']}:{cert['record_digest']}")
            self.assertTrue(row["approval"].startswith("auto-cert:1:"))

    def test_the_ledger_stays_unconfirmed_and_records_the_machine_action(self):
        ledger = _read(self.home / "staging" / "update" / "ledgers" / "16-17.json")
        by_subject = {e["subject_key"]: e for e in ledger["entries"]}
        for subject in FIX_SUBJECTS:
            entry = by_subject[subject]
            self.assertIs(entry["confirmed"], False, subject)
            self.assertEqual(entry["disposition"], "RULE_CREATED", subject)
            actors = [(h["actor"], h["action"]) for h in entry["history"]]
            self.assertIn(("MACHINE:odooflux.machine-confirmation/1", "machine_confirm"), actors)
            self.assertNotIn("MANUAL", [h["actor"] for h in entry["history"]])

    def test_decoys_stay_detect_only_with_coded_reasons(self):
        ledger = _read(self.home / "staging" / "update" / "ledgers" / "16-17.json")
        cid = {e["subject_key"]: e["change_id"] for e in ledger["entries"]}
        refused = {r["change_id"]: r["code"] for r in self.step_output("06-candidates.json")["autofix_refused"]}
        for subject, code in DECOY_REASONS.items():
            self.assertEqual(refused.get(cid[subject]), code, subject)
        confirmed = set(self.confirmations())
        for subject in DECOY_SUBJECTS:
            self.assertNotIn(subject, confirmed, subject)
        self.assertIs(next(e for e in ledger["entries"] if e["subject_key"] == "odoo.plain_old")["confirmed"], False)
        for row in self.rules().values():
            if row.get("origin") == "GENERATED" and row["id"] not in {c["rule_id"] for c in self.confirmations().values()}:
                self.assertNotEqual(row["maturity"], "FIX_ENABLED", row["id"])

    def test_the_build_has_no_demotion_and_the_gates_pass(self):
        self.assertEqual(self.step_output("09-rule-tests.json")["autofix_demoted"], [])
        self.assertEqual(self.step_output("09-rule-tests.json")["safety_findings"], [])

    def test_rebuild_with_the_same_inputs_is_byte_identical(self):
        self.assertEqual(self.result_again.outcome, "ACTIVE", self.result_again.reasons)
        self.assertEqual(self.result_again.new_release, self.result.new_release)
        self.assertEqual(_tree_bytes(self.tree()), _tree_bytes(self.release_dir(self.home_again, self.result_again) / "knowledge"))

    def test_a_pending_rule_is_never_promoted_by_a_machine_reference(self):
        target, ref = next((r["id"], r["approval"]) for r in self.rules().values() if r.get("approval"))
        work = Path(tempfile.mkdtemp(prefix="promote-"))
        try:
            tree = work / "knowledge"
            shutil.copytree(self.tree(), tree)
            with self.assertRaises(pr.PromoteError) as raised:
                pr.promote(tree, target, approval=ref)
            self.assertIn("automated certification", str(raised.exception))
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # --- migrate --fix (the real CLI and engine path) ----------------------------------------------------------------

    def test_migrate_fix_applies_the_exact_edits_and_leaves_the_rest_alone(self):
        work = Path(tempfile.mkdtemp(prefix="migrate-fix-"))
        try:
            mod = _module(work)
            shadow_before = (mod / "models" / "shadow.py").read_bytes()
            code, _, err = self.migrate(mod, state=work / "state", report=work / "report.json")
            self.assertEqual(code, 0, err)
            self.assertEqual((mod / "models" / "sale.py").read_text(encoding="utf-8"), SALE_AFTER)
            self.assertEqual((mod / "models" / "shadow.py").read_bytes(), shadow_before)
            self.assertEqual((mod / "__manifest__.py").read_text(encoding="utf-8"), MODULE_MANIFEST)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def test_a_second_fix_run_is_a_no_op(self):
        work = Path(tempfile.mkdtemp(prefix="migrate-twice-"))
        try:
            mod = _module(work)
            self.assertEqual(self.migrate(mod, state=work / "state-1")[0], 0)
            once = _tree_bytes(mod)
            code, _, err = self.migrate(mod, state=work / "state-2", report=work / "again.json")
            self.assertEqual(code, 0, err)
            self.assertEqual(_tree_bytes(mod), once)
            report = _read(work / "again.json")
            self.assertEqual(report["summary"]["edits"]["applied"], 0)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def _redigest(record: dict) -> dict:
    """A tampered record with its own digests recomputed (an attacker can do that; the re-proof must still refuse)."""
    from odooflux.knowledge.release.canonical import digest_obj
    record = dict(record)
    record["witness_digest"] = digest_obj(record["witness"])
    body = {k: v for k, v in record.items() if k != "record_digest"}
    record["record_digest"] = digest_obj(body)
    return record


def _tamper_witness(record):
    """Flip one structural fact of the TO side (a def's free names); the digests are recomputed to match."""
    defs = record["witness"]["to"]["defs"]
    name = record["new"] if record.get("new") in defs else record["old"]
    defs[name]["free_names"] = ["forged_global"]
    return _redigest(record)


def _tamper_evidence_digest(record):
    record["evidence"][0]["digest"] = "0" * 64
    return _redigest(record)


def _tamper_confirmed_flag(record):
    record["ledger_entry"]["confirmed"] = True
    return record


def _tamper_record_digest(record):
    record["record_digest"] = "0" * 64
    return record


class AutofixTamperTests(ReleaseFixture):
    """Each tampered artefact of a FIX_ENABLED rule ends DETECT_ONLY at the loader (load), is refused by the package
    predicate (import) and by activation, on a copy of the activated release. The user's knowledge base is untouched."""

    def setUp(self):
        self._work = Path(tempfile.mkdtemp(prefix="tamper-"))
        self.addCleanup(shutil.rmtree, self._work, True)
        self.copy = self._work / "release"
        shutil.copytree(self.release_dir(), self.copy)
        self.tree_copy = self.copy / "knowledge"
        self.target = self.confirmations()["odoo.old_round"]["rule_id"]
        self.other = self.confirmations()["odoo.legacy_sum"]["rule_id"]

    def _rules_file(self):
        for path in sorted((self.tree_copy / "compatibility").glob("*.rules.json")):
            if any(r["id"] == self.target for r in _read(path)):
                return path
        raise AssertionError("rule file not found")

    def _edit_row(self, rule_id, **changes):
        path = self._rules_file()
        rows = _read(path)
        for row in rows:
            if row["id"] == rule_id:
                row.update(changes)
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _confirmation_path(self, rule_id):
        return self.tree_copy / "confirmations" / f"{rule_id}.json"

    def _edit_confirmation(self, rule_id, transform):
        path = self._confirmation_path(rule_id)
        path.write_text(json.dumps(transform(_read(path)), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _assert_capped_everywhere(self, rule_id):
        # import (P10 predicate): the release package refuses the row
        findings, _, _ = safety.package_fix_findings(self.tree_copy)
        self.assertIn(rule_id, {f["rule_id"] for f in findings}, "import must refuse the tampered row")
        # load: the loader caps the row to DETECT_ONLY with KAP_FIX_CAPPED
        handle = KnowledgeHandle(root=self.copy, release_id="tamper", digest=None, builtin=False, completeness=None)
        kb = load_active_knowledge(handle)
        row = next(r for r in kb.rules if r.get("id") == rule_id)
        self.assertEqual(row["maturity"], "DETECT_ONLY", "load must cap the tampered row")
        self.assertIn("KAP_FIX_CAPPED", [f.code for f in kb.load_findings])
        # activation: the same predicate refuses it before the release can become active
        from odooflux.knowledge.update import activation
        problems = activation._fix_rule_problems(self.copy, {rule_id})
        self.assertTrue(problems and problems[0][0] == rule_id, problems)

    def test_untouched_copy_is_trusted_everywhere(self):
        findings, _, _ = safety.package_fix_findings(self.tree_copy)
        self.assertEqual(findings, [])
        handle = KnowledgeHandle(root=self.copy, release_id="tamper", digest=None, builtin=False, completeness=None)
        kb = load_active_knowledge(handle)
        self.assertEqual(next(r for r in kb.rules if r.get("id") == self.target)["maturity"], "FIX_ENABLED")

    def test_modified_rule_row_params(self):
        self._edit_row(self.target, params={"module": "odoo.tools.helpers", "old": "old_round", "new": "other_round"})
        self._assert_capped_everywhere(self.target)

    def test_forged_auto_cert_approval(self):
        self._edit_row(self.target, approval="auto-cert:1:" + "f" * 64)
        self._assert_capped_everywhere(self.target)

    def test_modified_certification_record(self):
        path = self.tree_copy / "certifications" / f"{self.target}.json"
        record = _read(path)
        record["change_class"] = "DELEGATING_ALIAS"
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        self._assert_capped_everywhere(self.target)

    def test_modified_confirmation_witness(self):
        self._edit_confirmation(self.target, _tamper_witness)
        self._assert_capped_everywhere(self.target)

    def test_forged_record_digest(self):
        self._edit_confirmation(self.target, _tamper_record_digest)
        self._assert_capped_everywhere(self.target)

    def test_swapped_evidence_digest(self):
        self._edit_confirmation(self.target, _tamper_evidence_digest)
        self._assert_capped_everywhere(self.target)

    def test_confirmation_of_another_rule_copied_in(self):
        shutil.copyfile(self._confirmation_path(self.other), self._confirmation_path(self.target))
        self._assert_capped_everywhere(self.target)

    def test_confirmed_flag_forged_in_the_record(self):
        self._edit_confirmation(self.target, _tamper_confirmed_flag)
        self._assert_capped_everywhere(self.target)

    def test_deleted_confirmation(self):
        self._confirmation_path(self.target).unlink()
        self._assert_capped_everywhere(self.target)

    def test_corrupted_blob_fails_the_re_proof(self):
        """L2: the retained blobs of the pair re-prove to the same witness; a corrupted blob is refused."""
        from odooflux.knowledge.acquisition.blobstore import BlobStore
        store_copy = self._work / "store"
        shutil.copytree(self.home / "staging" / "update" / "store", store_copy)
        record = self.confirmations()["odoo.old_round"]
        self.assertEqual(safety.source_problems(self.tree(), record["rule_id"], store_copy), [])
        digest = next(s["blob_sha256"] for s in record["sources"] if s["side"] == "to")
        BlobStore(store_copy).path_for(digest).write_bytes(b"corrupted")
        problems = safety.source_problems(self.tree(), record["rule_id"], store_copy)
        self.assertTrue(problems)
        self.assertEqual(problems[0][0], "blob-missing")


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


if __name__ == "__main__":
    unittest.main()
