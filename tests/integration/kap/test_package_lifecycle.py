"""TST-011-019 (REQ-KAP-025, REQ-KAP-026, REQ-KAP-047, REQ-KAP-044): package lifecycle across two kb-homes, offline.

Contract: release-lifecycle ("Activation (atomic)", "Rollback") and knowledge-package-format ("Reader algorithm").
Releases are built from `tests/fixtures/kap/fixture_release` (synthetic, DETECT_ONLY rules only). `socket.socket` is
replaced for the whole module, so any network attempt fails the test. The one FIX_ENABLED case asserts refusal only.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.cli.kap_release import FAULT_POINTS as ACTIVATE_FAULTS, ReleaseFault, activate, rollback
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.package.archive import PackageError
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import FAULT_POINTS as IMPORT_FAULTS, ImportFault, import_package
from odooflux.knowledge.release.audit import verify_audit
from odooflux.knowledge.release.manifest import require_intact, write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.store import ACTIVE_NAME, ensure_layout, list_installed, read_active

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "kap" / "fixture_release"
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


def _build_release(root: Path, *, label: str, coverage: bytes = b'{"items": []}\n', maturity: str = None) -> Path:
    """Copy the fixture tree, add the official sources, and write release.json. Returns the release tree."""
    tree = root / "release"
    shutil.copytree(FIXTURE, tree)
    shutil.copytree(KNOWLEDGE_ROOT / "official_sources", tree / "knowledge" / "official_sources")
    (tree / "coverage" / "coverage-manifest.json").write_bytes(coverage)
    if maturity is not None:
        rules_path = tree / "knowledge" / "compatibility" / "12-13.rules.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules[0]["maturity"] = maturity
        rules_path.write_text(json.dumps(rules, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_release_manifest(tree, {**META, "label": label})
    return tree


def _tree_bytes(home: Path) -> dict:
    out = {}
    for path in sorted(home.rglob("*")):
        rel = path.relative_to(home).as_posix()
        out[rel] = None if path.is_dir() else path.read_bytes()
    return out


class TestPackageLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        net = mock.patch("socket.socket", side_effect=AssertionError("network is disabled in tests"))
        net.start()
        self.addCleanup(net.stop)
        self.release_a = _build_release(self.tmp / "a", label="rel-a")
        self.release_b = _build_release(self.tmp / "b", label="rel-b", coverage=b'{"items": [1]}\n')
        self.release_c = _build_release(self.tmp / "c", label="rel-c", coverage=b'{"items": [2]}\n')
        self.pkg_a = export_package(self.release_a, self.tmp / "a.ofkp")
        self.pkg_b = export_package(self.release_b, self.tmp / "b.ofkp")
        self.pkg_c = export_package(self.release_c, self.tmp / "c.ofkp")

    def test_full_lifecycle_offline(self):
        # Site kb-home: import the package and activate it, then export the installed release again.
        site = self.tmp / "site-kb"
        import_package(self.pkg_a.path, site, activate=True)
        site_export = export_package(site / "releases" / self.pkg_a.release_id, self.tmp / "site-export.ofkp")
        self.assertEqual(site_export.release_digest, self.pkg_a.release_digest)

        # Consumer kb-home on another directory: import and activate the exported package.
        consumer = self.tmp / "consumer-kb"
        ensure_layout(consumer)
        result = import_package(site_export.path, consumer, activate=True)
        self.assertEqual(result.release_digest, self.pkg_a.release_digest)
        self.assertEqual(read_active(consumer)["digest"], self.pkg_a.release_digest)
        require_intact(consumer / "releases" / self.pkg_a.release_id)

        # A second release becomes active; the first moves to the previous stack.
        import_package(self.pkg_b.path, consumer, activate=True)
        active = read_active(consumer)
        self.assertEqual(active["release_id"], self.pkg_b.release_id)
        self.assertEqual(active["previous"][0]["release_id"], self.pkg_a.release_id)

        # Rollback restores the first release through the atomic path.
        pointer = rollback(consumer)
        self.assertEqual(pointer["release_id"], self.pkg_a.release_id)
        self.assertEqual(read_active(consumer)["release_id"], self.pkg_a.release_id)
        self.assertEqual(read_active(consumer)["previous"][0]["release_id"], self.pkg_b.release_id)
        require_intact(consumer / "releases" / self.pkg_a.release_id)

        self.assertEqual(sorted(r.release_id for r in list_installed(consumer)),
                         sorted([self.pkg_a.release_id, self.pkg_b.release_id]))
        self.assertTrue(verify_audit(consumer)[0])
        self.assertTrue(verify_audit(site)[0])
        self.assertFalse((consumer / ".lock").exists())
        self.assertEqual(list((consumer / "staging").iterdir()), [])

    def test_multiple_releases_rollback(self):
        home = self.tmp / "kb"
        for pkg in (self.pkg_a, self.pkg_b, self.pkg_c):
            import_package(pkg.path, home, activate=True)
        active = read_active(home)
        self.assertEqual(active["release_id"], self.pkg_c.release_id)
        self.assertEqual([p["release_id"] for p in active["previous"]],
                         [self.pkg_b.release_id, self.pkg_a.release_id])

        rollback(home)
        self.assertEqual(read_active(home)["release_id"], self.pkg_b.release_id)
        self.assertEqual([p["release_id"] for p in read_active(home)["previous"]],
                         [self.pkg_c.release_id, self.pkg_a.release_id])

        # The previous release (C) is damaged on disk: rollback refuses and the current release (B) stays active.
        (home / "releases" / self.pkg_c.release_id / "coverage" / "coverage-manifest.json").write_bytes(b"tampered\n")
        before = (home / ACTIVE_NAME).read_bytes()
        with self.assertRaises(KnowledgeReleaseError):
            rollback(home)
        self.assertEqual((home / ACTIVE_NAME).read_bytes(), before)
        self.assertEqual(read_active(home)["release_id"], self.pkg_b.release_id)
        self.assertTrue(verify_audit(home)[0])

    def test_activation_fault_injection_each_boundary(self):
        home = self.tmp / "kb"
        import_package(self.pkg_a.path, home, activate=True)
        import_package(self.pkg_b.path, home, activate=False)
        before_active = (home / ACTIVE_NAME).read_bytes()
        before_tree = _tree_bytes(home / "releases")
        self.assertEqual(ACTIVATE_FAULTS, ("verify", "lock", "pointer", "audit"))
        for point in ACTIVATE_FAULTS:
            with self.subTest(activate_point=point):
                with self.assertRaises(ReleaseFault):
                    activate(home, self.pkg_b.release_id, fault_at=point)
                self.assertEqual((home / ACTIVE_NAME).read_bytes(), before_active)
                self.assertFalse((home / ".lock").exists())
                self.assertEqual(_tree_bytes(home / "releases"), before_tree)
                self.assertTrue(verify_audit(home)[0])
        for point in IMPORT_FAULTS:
            with self.subTest(import_point=point):
                with self.assertRaises(ImportFault):
                    import_package(self.pkg_c.path, home, activate=True, fault_at=point)
                self.assertEqual((home / ACTIVE_NAME).read_bytes(), before_active)
                self.assertFalse((home / ".lock").exists())
                self.assertEqual(_tree_bytes(home / "releases"), before_tree)
                self.assertTrue(verify_audit(home)[0])
        # Without a fault the same activation succeeds.
        activate(home, self.pkg_b.release_id)
        self.assertEqual(read_active(home)["release_id"], self.pkg_b.release_id)

    def test_fix_enabled_rule_refused_on_import(self):
        fix_tree = _build_release(self.tmp / "fix", label="rel-fix", maturity="FIX_ENABLED")
        fix_pkg = export_package(fix_tree, self.tmp / "fix.ofkp")
        with self.assertRaises(PackageError):
            import_package(fix_pkg.path, self.tmp / "kb-fix", activate=True)


if __name__ == "__main__":
    unittest.main()
