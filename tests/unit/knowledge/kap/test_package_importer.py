"""TST-011-013 (REQ-KAP-025, REQ-KAP-027, REQ-KAP-026): package importer, atomic and fail-closed.

Contract: knowledge-package-format "Reader algorithm" and "P10", release-lifecycle "Activation (atomic)". Packages are
built with the real builder; the kb-home tree is compared byte for byte before and after every refused or faulted
import, so "untouched" means untouched.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import FAULT_POINTS, ImportFault, import_package
from odooflux.knowledge.release.audit import verify_audit
from odooflux.knowledge.release.manifest import require_intact, write_release_manifest
from odooflux.knowledge.release.store import ensure_layout, list_installed, read_active

META = {
    "label": "community-17.0-18.0-2026.11",
    "parent_release": None,
    "framework": {"built_with": "0.2.0", "min_framework": "0.2.0", "max_framework": None},
    "schema_versions": {"evidence": "1", "rule_metadata": "1"},
    "sources": [],
    "steps_covered": [],
    "coverage_manifest_digest": "cd" * 32,
    "completeness": "COMPLETE",
    "build": {"tool_version": "0.2.0", "build_time": "2026-11-01T00:00:00Z", "host_free": True},
}
RULE_BASE = {
    "id": "12-13.python.probe", "step": "12-13", "category": "python_orm", "maturity": "DETECT_ONLY",
    "risk": "LOW", "evidence": ["EV-101"], "detector_ref": "odooflux.rules.python.generic:flag_decorator",
    "fixer_ref": "odooflux.rules.python.generic:remove_decorator",
    "tests": {"positive": "T1", "negative": "T2", "idempotence": "T3"}, "review_required": False,
    "severity": "CRITICAL", "message": "m", "suggestion": "s", "file_kinds": ["python"], "ai_eligible": False,
    "conflicts_with": [], "depends_on": [], "legacy_ref": None, "params": {},
}


def _release(root: Path, *, maturity="DETECT_ONLY", coverage=b'{"items": []}\n') -> Path:
    """A complete knowledge release tree: official sources, one unverified evidence record, one rule."""
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", root / "knowledge" / "official_sources")
    evidence = json.loads((KNOWLEDGE_ROOT / "evidence" / "EV-101.json").read_text(encoding="utf-8"))
    evidence["status"] = "UNVERIFIED"
    files = {
        "knowledge/evidence/EV-101.json": json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        "knowledge/compatibility/versions.json": json.dumps({"versions": [], "transitions": []}) + "\n",
        "knowledge/compatibility/12-13.rules.json": json.dumps([{**RULE_BASE, "maturity": maturity}],
                                                              indent=2, sort_keys=True) + "\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "coverage").mkdir(exist_ok=True)
    (root / "coverage" / "coverage-manifest.json").write_bytes(coverage)
    (root / "provenance").mkdir(exist_ok=True)
    (root / "provenance" / "sources.json").write_text('{"sources": []}\n', encoding="utf-8")
    write_release_manifest(root, META)
    return root


def _snapshot(home: Path) -> dict:
    out = {}
    for path in sorted(home.rglob("*")):
        rel = path.relative_to(home).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


class TestPackageImporter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "kb"
        ensure_layout(self.home)
        self.good = export_package(_release(self.tmp / "good"), self.tmp / "good.ofkp")
        self.bad = export_package(_release(self.tmp / "bad", maturity="FIX_ENABLED"), self.tmp / "bad.ofkp")

    def tearDown(self):
        self._tmp.cleanup()

    def test_import_roundtrip_digest(self):
        result = import_package(self.good.path, self.home, activate=True)
        active = read_active(self.home)
        self.assertEqual(active["digest"], self.good.release_digest)
        self.assertEqual(result.release_digest, self.good.release_digest)
        installed = self.home / "releases" / self.good.release_id
        require_intact(installed)
        self.assertEqual(list(self.home.glob("staging/*")), [])
        self.assertFalse((self.home / ".lock").exists())
        self.assertTrue(verify_audit(self.home)[0])

    def test_reject_unverified_fix_enabled(self):
        bad = export_package(_release(self.tmp / "fix", maturity="FIX_ENABLED"), self.tmp / "fix.ofkp")
        before = _snapshot(self.home)
        with self.assertRaises(PackageError) as ctx:
            import_package(bad.path, self.home, activate=True)
        self.assertEqual(ctx.exception.code, "P10")
        self.assertEqual(_snapshot(self.home), before)
        self.assertEqual(list_installed(self.home), [])

    def test_downgrade_option_caps(self):
        result = import_package(self.bad.path, self.home, activate=True, downgrade_unverified=True)
        self.assertEqual(result.downgraded_rules, ("12-13.python.probe",))
        self.assertNotEqual(result.release_digest, self.bad.release_digest)
        installed = self.home / "releases" / result.release_id
        require_intact(installed)
        rules = json.loads((installed / "knowledge" / "compatibility" / "12-13.rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules[0]["maturity"], "DETECT_ONLY")
        self.assertEqual(read_active(self.home)["release_id"], result.release_id)
        self.assertTrue(verify_audit(self.home)[0])
        audit = (self.home / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("12-13.python.probe", audit)

    def test_failure_leaves_kbhome_untouched(self):
        before = _snapshot(self.home)
        with self.assertRaises(PackageError):
            import_package(self.bad.path, self.home, activate=True)
        self.assertEqual(_snapshot(self.home), before)
        corrupt = self.tmp / "corrupt.ofkp"
        corrupt.write_bytes(b"not a zip")
        with self.assertRaises(PackageError):
            import_package(corrupt, self.home, activate=True)
        self.assertEqual(_snapshot(self.home), before)

    def test_fault_injection_each_step(self):
        self.assertEqual(
            FAULT_POINTS, ("extract", "verify", "gates", "state", "move", "activate", "audit"))
        for point in FAULT_POINTS:
            with self.subTest(point=point):
                home = self.tmp / f"kb-{point}"
                ensure_layout(home)
                before = _snapshot(home)
                with self.assertRaises(ImportFault):
                    import_package(self.good.path, home, activate=True, fault_at=point)
                self.assertEqual(_snapshot(home), before)
                self.assertEqual(list_installed(home), [])

    def test_reimport_active_release_is_idempotent(self):
        import_package(self.good.path, self.home, activate=True)
        again = import_package(self.good.path, self.home, activate=True)
        self.assertFalse(again.installed)
        active = read_active(self.home)
        self.assertEqual(active["release_id"], self.good.release_id)
        self.assertEqual(active["previous"], [])

    def test_two_releases_installed(self):
        second = export_package(_release(self.tmp / "second", coverage=b'{"items": [1]}\n'), self.tmp / "second.ofkp")
        import_package(self.good.path, self.home, activate=True)
        import_package(second.path, self.home, activate=True)
        installed = [r.release_id for r in list_installed(self.home)]
        self.assertEqual(installed, sorted([self.good.release_id, second.release_id]))
        active = read_active(self.home)
        self.assertEqual(active["release_id"], second.release_id)
        self.assertEqual(active["previous"][0]["release_id"], self.good.release_id)


if __name__ == "__main__":
    unittest.main()
