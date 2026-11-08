"""TST-006-026 (REQ-DEP-001): ``*.deps.unknown-dependency``."""

import tempfile
import unittest
from pathlib import Path

from odooflux.dependencies import core_modules as cm

from .. import _setup  # noqa: F401

SOURCE = frozenset({"base", "web", "website_sale_dummy", "mail"})
TARGET = frozenset({"base", "web", "mail"})


def write(root: Path, name: str, depends, text_extra=""):
    module = root / name
    module.mkdir()
    (module / "__manifest__.py").write_text(repr({"name": name, "depends": list(depends)}), encoding="utf-8")
    return module


class UnknownDependencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_check(self, modules, source=SOURCE, target=TARGET):
        paths = [write(self.root, name, deps) for name, deps in modules.items()]
        return cm.check_unknown_dependencies(paths, source_core=source, target_core=target)

    def test_core_dependency_is_clean(self):
        self.assertEqual(self.run_check({"a": ["base", "mail"]}), [])

    def test_scanned_module_dependency_is_clean(self):
        self.assertEqual(self.run_check({"a": ["b"], "b": ["base"]}), [])

    def test_enterprise_like_unknown_name_is_warning(self):
        findings = self.run_check({"a": ["base", "web_studio"]})
        self.assertEqual(len(findings), 1)
        self.assertEqual((findings[0].rule_id, findings[0].severity, findings[0].matched),
                         ("*.deps.unknown-dependency", "WARNING", "web_studio"))
        self.assertEqual(findings[0].line, 1)

    def test_removed_core_module_is_critical(self):
        findings = self.run_check({"a": ["website_sale_dummy"]})
        self.assertEqual([(f.severity, f.matched) for f in findings], [("CRITICAL", "website_sale_dummy")])

    def test_removed_core_module_that_is_scanned_is_clean(self):
        self.assertEqual(self.run_check({"a": ["website_sale_dummy"], "website_sale_dummy": ["base"]}), [])

    def test_without_source_list_unknown_is_warning(self):
        findings = self.run_check({"a": ["website_sale_dummy"]}, source=None)
        self.assertEqual([f.severity for f in findings], ["WARNING"])

    def test_without_target_list_nothing_is_decided(self):
        self.assertEqual(self.run_check({"a": ["zzz"]}, target=None), [])

    def test_unreadable_manifest_is_skipped(self):
        module = self.root / "bad"
        module.mkdir()
        (module / "__manifest__.py").write_text("{'depends': [foo()]}", encoding="utf-8")
        self.assertEqual(cm.check_unknown_dependencies([module], source_core=SOURCE, target_core=TARGET), [])

    def test_shipped_lists_load_for_registry_versions(self):
        self.assertIn("base", cm.core_list("18.0"))
        self.assertIsNone(cm.core_list("99.0"))

    def test_finding_line_points_at_the_dependency(self):
        module = self.root / "m"
        module.mkdir()
        (module / "__manifest__.py").write_text("{\n 'name': 'm',\n 'depends': [\n  'base',\n  'ghost',\n ],\n}\n")
        findings = cm.check_unknown_dependencies([module], source_core=None, target_core=TARGET)
        self.assertEqual(findings[0].line, 5)


if __name__ == "__main__":
    unittest.main()
