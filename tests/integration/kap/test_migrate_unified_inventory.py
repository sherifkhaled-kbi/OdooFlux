"""TST-012-W3d-I (feature 012, plan addendum B3/B5): `migrate` with unified Community + Enterprise inventories.

A release carries `knowledge/inventory/<version>.json` for both versions (hand-written parts, merged by the real
`inventory.merge`, verified on load). Three custom modules are migrated 17 -> 18:
- `mod_community` depends on Community modules only: COMPLETE, fixes applied.
- `mod_enterprise` depends on an Enterprise module (and Community): COMPLETE, both versions carry the Enterprise
  inventory.
- `mod_unknown` depends on a name no inventory declares: INCOMPLETE, KB-COVERAGE-INCOMPLETE, fixes withheld.
Detection still runs for all three. Offline: sockets are replaced and counted. Without an active release (built-in
knowledge) no coverage finding exists and the module is fixed as today.
"""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux import builtins
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.release.manifest import write_release_manifest
from odooflux.knowledge.update import inventory as inv
from tests.integration.kap.test_migrate_with_release import GOLDEN, META, STEPS_COVERED, _build_release

FINDING = "KB-COVERAGE-INCOMPLETE"
DIGEST = "c" * 64
COMMUNITY = {"base": [], "account": ["base"], "sale": ["account", "base"]}
ENTERPRISE = {"sale_subscription": ["sale"]}
MODULES = {
    "mod_community": ["base", "sale"],
    "mod_enterprise": ["base", "sale_subscription"],
    "mod_unknown": ["base", "ghost_module"],
}


def _part(source_id, confidentiality, modules):
    return {"source_id": source_id, "confidentiality": confidentiality, "skipped": 0, "skipped_nested": 0,
            "parse_errors": [],
            "modules": {name: {"depends": sorted(deps), "installable": True, "auto_install": False,
                               "manifest_digest": DIGEST, "path_digest": "d" * 64}
                        for name, deps in modules.items()}}


def _inventory(version):
    return inv.merge([_part(f"odoo-{version}", "public", COMMUNITY),
                      _part(f"enterprise-{version}", "enterprise", ENTERPRISE)])


class MigrateUnifiedInventoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.net = mock.MagicMock(side_effect=AssertionError("network is disabled in tests"))
        for target in ("socket.socket", "socket.create_connection"):
            patch = mock.patch(target, self.net)
            patch.start()
            self.addCleanup(patch.stop)
        self.home = self.install("unified-012", tamper=False)
        self.state = self.tmp / "state"

    def tearDown(self):
        self.assertEqual(self.net.call_count, 0, "a migrate run attempted a network connection")

    def install(self, label, *, tamper):
        """Install a release whose knowledge tree carries the inventories (tampered: content changed, digest kept)."""
        tree = _build_release(self.tmp / f"src-{label}", label)
        directory = tree / "knowledge" / "inventory"
        directory.mkdir(parents=True)
        for version in ("17.0", "18.0"):
            document = _inventory(version)
            if tamper and version == "18.0":
                document["modules"]["sale_subscription"]["depends"] = ["base"]
            (directory / f"{version}.json").write_text(json.dumps(document, sort_keys=True, indent=2) + "\n",
                                                       encoding="utf-8")
        write_release_manifest(tree, {**META, "label": label, "steps_covered": STEPS_COVERED})
        pkg = export_package(tree, self.tmp / f"{label}.ofkp")
        home = self.tmp / f"home-{label}"
        import_package(pkg.path, home, activate=True)
        return home

    def addons(self, name):
        """Fresh copy of the three custom modules (each run starts from the same bytes)."""
        root = self.tmp / f"addons-{name}"
        for module, depends in MODULES.items():
            target = root / module
            shutil.copytree(GOLDEN, target, ignore=shutil.ignore_patterns("expected"))
            (target / "__manifest__.py").write_text(
                repr({"name": module, "version": "17.0.1.0.0", "depends": depends, "installable": True}) + "\n",
                encoding="utf-8")
        return root

    def migrate(self, addons, *argv, home=None, report="report.json"):
        path = self.tmp / f"{report}"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = builtins.main(["migrate", "--addons-path", str(addons), "--from-version", "17",
                                  "--to-version", "18", "--kb-home", str(self.home if home is None else home),
                                  "--state-dir", str(self.state), "--report", str(path),
                                  "--report-format", "json", *argv])
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        return code, out.getvalue() + err.getvalue(), data

    @staticmethod
    def module_entry(report, name):
        return next(m for m in report["modules"] if Path(m["path"]).name == name)

    @staticmethod
    def tree_bytes(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}

    def test_incomplete_module_is_withheld_and_the_others_are_fixed(self):
        addons = self.addons("fix")
        before = {name: self.tree_bytes(addons / name) for name in MODULES}
        code, text, report = self.migrate(addons, "--fix")
        self.assertIn(code, (0, 1, 3), text)
        self.assertFalse(report["knowledge_release"]["builtin"])
        for name in MODULES:  # detection runs for every module
            self.assertTrue(self.module_entry(report, name)["findings"], name)
        unknown = self.module_entry(report, "mod_unknown")
        coverage = [f for f in unknown["findings"] if f.get("rule_id") == FINDING]
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage[0]["severity"], "WARNING")
        self.assertIn("ghost_module", coverage[0]["message"])
        self.assertNotIn("sale_subscription", coverage[0]["message"])  # Enterprise name not in the message
        for name in ("mod_community", "mod_enterprise"):
            self.assertFalse([f for f in self.module_entry(report, name)["findings"] if f.get("rule_id") == FINDING])
        self.assertEqual(self.tree_bytes(addons / "mod_unknown"), before["mod_unknown"], "withheld: no edit written")
        self.assertNotEqual(self.tree_bytes(addons / "mod_community"), before["mod_community"])
        self.assertNotEqual(self.tree_bytes(addons / "mod_enterprise"), before["mod_enterprise"])
        self.assertIn("1 module(s) INCOMPLETE", text)

    def test_coverage_is_reported_in_analysis_mode_too(self):
        code, _, report = self.migrate(self.addons("analyze"))
        self.assertIn(code, (0, 1), _)
        hits = [f for f in self.module_entry(report, "mod_unknown")["findings"] if f.get("rule_id") == FINDING]
        self.assertEqual(len(hits), 1)

    def test_builtin_knowledge_has_no_coverage_and_fixes_as_today(self):
        empty = self.tmp / "empty-home"
        addons = self.addons("builtin")
        before = self.tree_bytes(addons / "mod_unknown")
        code, text, report = self.migrate(addons, "--fix", home=empty)
        self.assertIn(code, (0, 1, 3), text)
        self.assertTrue(report["knowledge_release"]["builtin"])
        self.assertFalse([f for m in report["modules"] for f in m["findings"] if f.get("rule_id") == FINDING])
        self.assertNotEqual(self.tree_bytes(addons / "mod_unknown"), before, "built-in: the module is fixed as today")

    def test_tampered_inventory_stops_the_run_with_a_clear_error(self):
        home = self.install("unified-tampered", tamper=True)
        addons = self.addons("tampered")
        before = self.tree_bytes(addons)
        code, text, report = self.migrate(addons, "--fix", home=home)
        self.assertEqual(code, 4, text)
        self.assertIn("knowledge inventory: INVENTORY_INVALID", text)
        self.assertIsNone(report)  # no report: the run never started
        self.assertEqual(self.tree_bytes(addons), before)


if __name__ == "__main__":
    unittest.main()
