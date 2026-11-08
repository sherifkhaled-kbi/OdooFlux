"""TST-011-071 variant G (REQ-KAP-029, REQ-KAP-036, REQ-KAP-039; INTEGRATION_NOTES note 69): a release BUILT by the
pipeline is a complete knowledge tree that `migrate` uses offline.

The release is built for real through `knowledge/pipeline.py` from the clean synthetic 16.0 to 17.0 repositories
(variant A: the pipeline reaches COMPLETE after triage), installed, and activated with the release CLI. No file of the
release tree is hand-completed. `migrate` then runs on a copy of `tests/golden_fixtures/17.0/kbi_demo` WITHOUT its
expected/ directory, with `socket.socket` and `socket.create_connection` counted (every run must count 0 calls).

Assertions:
1. The built tree carries every file the knowledge readers open (the parent content, carried forward), and the readers
   load it: `load_active_knowledge`, `load_version_data`, `check_integrity` with the release root.
2. `migrate` exits per the existing contract (0 clean, 1 open findings; never 2, 3 or 4 here) and its JSON report
   carries the BUILT release's id and digest, equal to `resolve_knowledge` for that kb-home, with schema 1.1.0.
3. No reader falls back to the built-in tree (the reader-root spies of test_release_consistency).
4. Coverage: 17.0 to 18.0 is not covered by this release (the synthetic release covers 16-17 only): the
   KAP_TRANSITION_NOT_COVERED warning is reported and the module is not PASS. 16.0 to 17.0 is covered: no
   KAP_TRANSITION warning.
5. FIX_ENABLED, CURRENT behaviour (not changed here; owner decision OD-K13): the FIX_ENABLED rules carried from the
   built-in parent (origin absent or BUILTIN) are NOT capped at load. `load_active_knowledge` applies
   `fix_gate_findings(tree)` with `include_builtin=False`, which skips grandfathered built-in rules, so they stay
   FIX_ENABLED and no KAP_FIX_CAPPED finding is produced. The importer is different: `knowledge package import` refuses
   them unverified (P10, covered by test_pipeline_e2e variant F).
6. `release deactivate` removes the pointer; migrate then returns to the built-in release with its computed digest in
   the report.
"""

import contextlib
import io
import json
import shutil
import socket
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.knowledge.loader import KAP_FIX_CAPPED, KNOWLEDGE_ROOT, load_active_knowledge
from odooflux.knowledge.release.builtin import builtin_digest
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.knowledge.release.store import ACTIVE_NAME, list_installed, read_active
from odooflux.validation.dependency.integrity import check_integrity
from odooflux.versions.registry.loader import load_version_data
from tests.integration.kap.test_pipeline_e2e import BROKEN_PATH, JS_PATH, PipelineEndToEnd, _build_variant
from tests.unit.knowledge.kap.test_release_consistency import VIEW_RULES, assert_reader_roots, instrumented

GOLDEN = Path(__file__).resolve().parents[2] / "golden_fixtures" / "17.0" / "kbi_demo"
COVERED = ("16", "17")
UNCOVERED = ("17", "18")
NOT_COVERED = "KAP_TRANSITION_NOT_COVERED"
READERS_REQUIRED = {"rule-binder", "versions", "integrity", "ai-escalation"}
# Files the readers open by path (load_knowledge, load_version_data, check_integrity, docker_env, rng, view_index).
READER_FILES = ("compatibility/versions.json", "compatibility/core_modules.json",
                "compatibility/enterprise_modules.json", "compatibility/runtime_images.json",
                "compatibility/rng_schemas.json", "compatibility/runtime_log_patterns.json", "gaps.json",
                "official_sources/allow_list.json", "official_sources/revisions.json")


def _files(root: Path, sub: str) -> dict:
    base = root / sub
    return {p.relative_to(base).as_posix(): p for p in sorted(base.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def _rule_ids(path: Path) -> set:
    return {r["id"] for r in json.loads(path.read_text(encoding="utf-8"))}


class PipelineReleaseUsable(PipelineEndToEnd):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        helper = cls()  # a TestCase instance only to reuse the plan, triage and CLI helpers of the e2e base class
        cls.helper = helper
        cls.home = cls.base / "g" / "kb-home"
        path, from_sha, to_sha = _build_variant(cls.base / "g" / "repo", drop=(JS_PATH, BROKEN_PATH))
        result = helper._build_with_triage(helper._plan(path, from_sha, to_sha, "usable-g"), cls.home)
        if result.outcome != "OK" or result.completeness != "COMPLETE":
            raise AssertionError(f"variant A must build COMPLETE: {result.outcome} {result.completeness} "
                                 f"{result.message}")
        cls.release_id = result.release_id
        cls.release_dir = cls.home / "releases" / cls.release_id
        cls.tree = cls.release_dir / "knowledge"
        cls.release_digest = json.loads((cls.release_dir / "release.json").read_text(encoding="utf-8"))[
            "release_digest"]
        code, out, err = helper._cli("release", "activate", cls.release_id, "--kb-home", str(cls.home))
        if code != 0:
            raise AssertionError(f"activate failed: {out} {err}")

    def runTest(self):  # default method for the helper instance built in setUpClass (not a test)
        pass

    def setUp(self):
        self.addCleanup(self._reactivate)

    def _reactivate(self):
        if not (self.home / ACTIVE_NAME).exists():
            self.helper._cli("release", "activate", self.release_id, "--kb-home", str(self.home))

    def _migrate(self, name: str, from_v: str, to_v: str, *, extra=(), home=None):
        """One offline migrate run on a fresh copy of kbi_demo without expected/. Returns (code, report, records)."""
        work = self.base / "g-runs" / name
        module = work / "kbi_demo"
        shutil.copytree(GOLDEN, module, ignore=shutil.ignore_patterns("expected"))
        report_path = work / "report.json"
        network = mock.MagicMock(side_effect=AssertionError("network is disabled"))
        records, resolves = [], []
        argv = ["migrate", "--module", str(module), "--kb-home", str(self.home if home is None else home),
                "--state-dir", str(work / "state"), "--from-version", from_v, "--to-version", to_v,
                "--report", str(report_path), "--report-format", "json", *extra]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(socket, "socket", network), mock.patch.object(socket, "create_connection", network), \
                instrumented(records, resolves), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(argv)
        self.assertEqual(network.call_count, 0, f"migrate {name} attempted a socket connection")
        self.assertIn(code, (0, 1), err.getvalue())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        return code, report, records

    # 1. the built tree is complete and the readers load it
    def test_1_built_tree_carries_every_reader_file(self):
        self.assertTrue((self.tree / "compatibility" / "view_index").is_dir(), "view_index is missing")
        self.assertTrue(list((self.tree / "compatibility" / "view_index").glob("*.json")))
        for rel in READER_FILES:
            self.assertTrue((self.tree / rel).is_file(), f"release tree is missing {rel}")
        self.assertTrue((self.tree / "schemas").is_dir(), "release tree is missing schemas/ (note 69)")
        self.assertEqual(sorted(_files(KNOWLEDGE_ROOT, "schemas")), sorted(_files(self.tree, "schemas")))
        self.assertEqual(set(_files(KNOWLEDGE_ROOT, "evidence")) - set(_files(self.tree, "evidence")), set())
        # carried forward: built-in compatibility and official_sources files are present; the pipeline only extends
        # the 16-17 rule file (candidates) and the revisions catalogue.
        for sub in ("compatibility", "official_sources"):
            for name, src in _files(KNOWLEDGE_ROOT, sub).items():
                dest = self.tree / sub / name
                self.assertTrue(dest.is_file(), f"carried-forward file missing: {sub}/{name}")
                if name.endswith(".rules.json"):
                    self.assertLessEqual(_rule_ids(src), _rule_ids(dest), f"{sub}/{name} lost built-in rules")
                elif name != "revisions.json":
                    self.assertEqual(dest.read_bytes(), src.read_bytes(), f"{sub}/{name} differs from the parent")
        revisions = json.loads((self.tree / "official_sources" / "revisions.json").read_text(encoding="utf-8"))
        builtin = json.loads((KNOWLEDGE_ROOT / "official_sources" / "revisions.json").read_text(encoding="utf-8"))
        self.assertTrue(all(entry in revisions for entry in builtin), "built-in revisions were not carried forward")

    def test_1_readers_load_the_release_tree(self):
        handle = resolve_knowledge(self.home)
        self.assertFalse(handle.builtin)
        kb = load_active_knowledge(handle)
        builtin_kb = load_active_knowledge(resolve_knowledge(self.helper.base / "no-such-home"))
        self.assertTrue(builtin_kb.rules)
        self.assertGreaterEqual(len(kb.rules), len(builtin_kb.rules))
        self.assertEqual(len(kb.versions), len(builtin_kb.versions))
        self.assertEqual(load_version_data(knowledge_root=self.tree), load_version_data())
        module = self.base / "g-readers" / "kbi_demo"
        shutil.copytree(GOLDEN, module, ignore=shutil.ignore_patterns("expected"))
        self.assertEqual(check_integrity([str(module)], target_version="18.0", knowledge_root=self.tree),
                         check_integrity([str(module)], target_version="18.0"))

    # 2. migrate exit contract and the report block
    def test_2_report_carries_built_release_id_digest_schema(self):
        code, report, _ = self._migrate("report", *UNCOVERED, extra=VIEW_RULES)
        block = report["knowledge_release"]
        self.assertEqual(block["release_id"], self.release_id)
        self.assertEqual(block["digest"], self.release_digest)
        self.assertFalse(block["builtin"])
        self.assertEqual(block["completeness"], "COMPLETE")
        expected = resolve_knowledge(self.home)
        self.assertEqual((block["release_id"], block["digest"]), (expected.release_id, expected.digest))
        self.assertEqual(report["schema_version"], "1.1.0")
        self.assertIn(code, (0, 1))

    # 3. no fallback to the built-in tree
    def test_3_every_reader_gets_the_built_release_root(self):
        _, _, records = self._migrate("readers", *UNCOVERED, extra=VIEW_RULES)
        readers = {r["reader"] for r in records}
        self.assertTrue(READERS_REQUIRED <= readers, readers)
        assert_reader_roots(records, self.tree)
        for record in records:
            if record["reader"] == "rule-binder":
                self.assertEqual((record["release_id"], record["digest"]), (self.release_id, self.release_digest))

    # 4. coverage: uncovered pair warns and is not PASS; covered pair is silent
    def test_4_uncovered_pair_warns_and_is_not_verified(self):
        _, report, _ = self._migrate("uncovered", *UNCOVERED)
        warnings = report.get("warnings") or []
        hits = [w for w in warnings if w.startswith(NOT_COVERED)]
        self.assertEqual(len(hits), 1, warnings)
        self.assertIn("step 17-18", hits[0])
        self.assertIn(self.release_id, hits[0])
        self.assertIn("cannot be reported verified", hits[0])
        for module in report["modules"]:
            self.assertNotEqual(module["status"], "PASS", "an uncovered step must not be reported verified")

    def test_4_covered_pair_has_no_warning(self):
        _, report, _ = self._migrate("covered", *COVERED)
        self.assertEqual([w for w in report.get("warnings") or [] if w.startswith("KAP_TRANSITION")], [])
        self.assertEqual(report["knowledge_release"]["release_id"], self.release_id)

    # 5. FIX_ENABLED: current behaviour, asserted and documented, not changed
    def test_5_builtin_fix_enabled_rules_are_not_capped_at_load(self):
        kb = load_active_knowledge(resolve_knowledge(self.home))
        fix = [r for r in kb.rules if isinstance(r, dict) and r.get("maturity") == "FIX_ENABLED"]
        self.assertTrue(fix, "the parent's FIX_ENABLED rules are carried into the release")
        self.assertTrue(all(r.get("origin") in (None, "BUILTIN") for r in fix), "only built-in-origin rules here")
        self.assertEqual([f for f in kb.load_findings if getattr(f, "code", None) == KAP_FIX_CAPPED], [])

    # 6. deactivation returns to the built-in release with its computed digest
    def test_6_deactivate_returns_to_builtin_digest(self):
        code, out, err = self.helper._cli("release", "deactivate", "--kb-home", str(self.home))
        self.assertEqual(code, 0, out + err)
        self.assertIsNone(read_active(self.home))
        report_code, report, _ = self._migrate("deactivated", *UNCOVERED)
        block = report["knowledge_release"]
        self.assertTrue(block["builtin"])
        self.assertEqual(block["release_id"], "builtin")
        self.assertEqual(block["digest"], builtin_digest())
        self.assertEqual(block["digest"], resolve_knowledge(self.home).digest)
        self.assertIn(report_code, (0, 1))
        self.assertEqual(list_installed(self.home)[0].state.value, "INSTALLED")


if __name__ == "__main__":
    unittest.main()
