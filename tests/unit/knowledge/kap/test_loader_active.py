"""TST-011-072 (REQ-KAP-036, REQ-KAP-039, REQ-KAP-005): `load_active_knowledge(handle)` and the composition-root binder.

A release installed under kb-home keeps its knowledge tree in `<release>/knowledge/` (see the package importer). The
built-in handle loads exactly what `load_knowledge()` loads today. A non-built-in handle never falls back to the
built-in tree, and FIX_ENABLED rules that fail promotion gates 1 to 5 are capped to DETECT_ONLY with KAP_FIX_CAPPED.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_active_knowledge, load_knowledge
from odooflux.knowledge.release import resolver
from odooflux.knowledge.release.builtin import builtin_handle
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.release.model import KnowledgeHandle, KnowledgeReleaseError, ReleaseState
from odooflux.knowledge.release.resolver import resolve_knowledge
from odooflux.knowledge.release.store import KbLock, build_pointer, ensure_layout, set_release_state, utc_now, \
    write_active

META = {
    "label": "loader-active-test",
    "parent_release": None,
    "framework": {"built_with": "0.0.0-test", "min_framework": "0.0.0", "max_framework": None},
    "schema_versions": {"rule": 1},
    "sources": [],
    "steps_covered": [{"step": "16-17", "completeness": "COMPLETE", "ledger_digest": "ab" * 32}],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.0.0-test", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}

MANUAL_RULE = {"id": "16-17.python.manual", "maturity": "DETECT_ONLY", "origin": "MANUAL", "evidence": []}
FIX_RULE = {"id": "16-17.python.fix", "maturity": "FIX_ENABLED", "origin": "MANUAL", "evidence": []}


class LoaderActiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.home = self.base / "kb-home"
        resolver.clear_cache()

    def tearDown(self):
        resolver.clear_cache()
        self._tmp.cleanup()

    def _install(self, rules) -> str:
        """Build a release whose knowledge tree is `knowledge/`, install it as ACTIVE. Returns the release id."""
        ensure_layout(self.home)
        tree = self.base / "tree"
        (tree / "knowledge" / "compatibility").mkdir(parents=True)
        (tree / "knowledge" / "compatibility" / "16-17.rules.json").write_text(json.dumps(rules) + "\n",
                                                                               encoding="utf-8")
        manifest = write_release_manifest(tree, META)
        rid = manifest["release_id"]
        tree.rename(self.home / "releases" / rid)
        set_release_state(self.home, rid, ReleaseState.ACTIVE)
        with KbLock(self.home):
            write_active(self.home, build_pointer(None, rid, manifest["release_digest"], utc_now()))
        return rid

    def test_builtin_path_unchanged(self):
        kb = load_active_knowledge(builtin_handle())
        reference = load_knowledge(KNOWLEDGE_ROOT)
        self.assertEqual(kb.root, reference.root)
        self.assertEqual(len(kb.rules), len(reference.rules))
        self.assertEqual(kb.rules, reference.rules)
        self.assertEqual(sorted(kb.evidence), sorted(reference.evidence))
        self.assertEqual(kb.load_findings, [])

    def test_no_active_release_resolves_to_builtin_rules(self):
        handle = resolve_knowledge(self.base / "absent-home")
        self.assertTrue(handle.builtin)
        self.assertEqual(load_knowledge().rules, load_active_knowledge(handle).rules)

    def test_active_release_rules_loaded(self):
        self._install([MANUAL_RULE])
        handle = resolve_knowledge(self.home)
        kb = load_active_knowledge(handle)
        self.assertEqual(["16-17.python.manual"], [r["id"] for r in kb.rules])
        self.assertEqual(handle.root / "knowledge", kb.root)

    def test_fix_capped_on_gate_failure(self):
        self._install([MANUAL_RULE, FIX_RULE])
        kb = load_active_knowledge(resolve_knowledge(self.home))
        maturity = {r["id"]: r["maturity"] for r in kb.rules}
        self.assertEqual("DETECT_ONLY", maturity["16-17.python.fix"])
        codes = [(f.code, f.severity, f.pointer) for f in kb.load_findings]
        self.assertIn(("KAP_FIX_CAPPED", "WARNING", "16-17.python.fix"), codes)
        self.assertEqual("DETECT_ONLY", maturity["16-17.python.manual"])

    def test_origin_claim_does_not_skip_the_cap_at_load(self):
        """REQ-KAP-027/039: a FIX_ENABLED row that omits `origin` (or claims BUILTIN) but is not the shipped built-in row
        is capped at load like any other unverified FIX_ENABLED rule: a release is not trusted to describe itself."""
        for n, extra in enumerate(({}, {"origin": "BUILTIN"})):
            row = {"id": f"16-17.python.spoof-{n}", "maturity": "FIX_ENABLED", "evidence": [], **extra}
            self._install([row])
            kb = load_active_knowledge(resolve_knowledge(self.home))
            rule = next(r for r in kb.rules if r["id"] == row["id"])
            self.assertEqual("DETECT_ONLY", rule["maturity"], row)
            self.assertIn(("KAP_FIX_CAPPED", "WARNING", row["id"]),
                          [(f.code, f.severity, f.pointer) for f in kb.load_findings])

    def test_non_builtin_missing_tree_raises_never_falls_back(self):
        handle = KnowledgeHandle(root=self.base / "no-such-release", release_id="kr-000000000000", digest=None,
                                 builtin=False, completeness=None)
        with self.assertRaises(KnowledgeReleaseError):
            load_active_knowledge(handle)

    def test_binder_rows_come_from_active_release(self):
        from odooflux.builtins import build_context

        self._install([MANUAL_RULE])
        with mock.patch.dict(os.environ, {"ODOOFLUX_KB_HOME": str(self.home)}):
            rows = build_context().registries.run_rule_binder.rows()
        self.assertEqual(["16-17.python.manual"], [r["id"] for r in rows])


if __name__ == "__main__":
    unittest.main()
