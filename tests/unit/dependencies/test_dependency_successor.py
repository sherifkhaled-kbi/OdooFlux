"""TST-006-063 (FR-020): ``*.deps.removed-with-successor`` and the "no successor known" case (synthetic data only)."""

import tempfile
import unittest
from pathlib import Path

from odooflux.dependencies import core_modules as cm

from .. import _setup  # noqa: F401

SOURCE = frozenset({"base", "old_a", "old_b", "old_c"})
TARGET = frozenset({"base", "new_a"})
REPLACED = {"old_a": {"successors": ["new_a"], "evidence": ["EV-900"]}}


def write(root: Path, name: str, depends):
    module = root / name
    module.mkdir()
    (module / "__manifest__.py").write_text(repr({"name": name, "depends": list(depends)}), encoding="utf-8")
    return module


class DependencySuccessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_check(self, modules, replaced_by=REPLACED, source=SOURCE, target=TARGET):
        paths = [write(self.root, name, deps) for name, deps in modules.items()]
        return cm.check_unknown_dependencies(paths, source_core=source, target_core=target, replaced_by=replaced_by)

    def test_removed_with_successor_cites_successor_and_evidence(self):
        findings = self.run_check({"m": ["old_a"]})
        self.assertEqual([(f.rule_id, f.matched) for f in findings], [("*.deps.removed-with-successor", "old_a")])
        self.assertIn("new_a", findings[0].message)
        self.assertIn("EV-900", findings[0].message)

    def test_removed_without_successor_still_reports_and_says_so(self):
        findings = self.run_check({"m": ["old_b"]})
        self.assertEqual([(f.rule_id, f.severity) for f in findings], [("*.deps.unknown-dependency", "CRITICAL")])
        self.assertIn("no successor known", findings[0].message)

    def test_unknown_non_core_name_is_not_called_a_removed_module(self):
        findings = self.run_check({"m": ["web_studio"]})
        self.assertEqual([(f.rule_id, f.severity) for f in findings], [("*.deps.unknown-dependency", "WARNING")])
        self.assertNotIn("no successor known", findings[0].message)

    def test_no_replaced_by_data_keeps_existing_behaviour(self):
        findings = self.run_check({"m": ["old_a"]}, replaced_by=None)
        self.assertEqual([(f.rule_id, f.severity) for f in findings], [("*.deps.unknown-dependency", "CRITICAL")])
        self.assertNotIn("no successor known", findings[0].message)

    def test_successor_entry_without_evidence_is_ignored(self):
        findings = self.run_check({"m": ["old_a"]}, replaced_by={"old_a": {"successors": ["new_a"], "evidence": []}})
        self.assertEqual([f.rule_id for f in findings], ["*.deps.unknown-dependency"])
        self.assertIn("no successor known", findings[0].message)

    def test_scanned_or_present_dependency_is_not_reported(self):
        self.assertEqual(self.run_check({"m": ["new_a", "old_a"], "old_a": ["base"]}), [])

    def test_successor_finding_never_edits_anything(self):
        findings = self.run_check({"m": ["old_a"]})
        self.assertTrue(all(getattr(f, "replacement", None) is None for f in findings))

    def test_load_replaced_by_unknown_version_is_empty(self):
        self.assertEqual(cm.load_replaced_by("99.0"), {})


if __name__ == "__main__":
    unittest.main()
