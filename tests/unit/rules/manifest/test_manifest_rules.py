"""TST-006-025 (REQ-MAN-002, REQ-MAN-003): shared manifest hygiene and file rules."""

import tempfile
import unittest
from pathlib import Path

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.manifest import files as mf
from odooflux.rules.manifest import hygiene as mh
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401


def ctx(rule_id, severity="WARNING"):
    return RuleContext(rule_id=rule_id, severity=severity, step="*", message="m", suggestion="s")


def doc(text, path="mod/__manifest__.py"):
    return Document.from_text(path, text)


class ParseErrorTests(unittest.TestCase):
    def detect(self, text):
        return mh.flag_parse_error(doc(text), ctx("*.manifest.parse-error", "CRITICAL"))

    def test_non_literal_manifest_is_reported(self):
        self.assertEqual(len(self.detect("{'name': foo()}\n")), 1)

    def test_syntax_error_is_reported_at_its_line(self):
        findings = self.detect("{\n'name': 'x'\n'depends': []}\n")
        self.assertEqual(len(findings), 1)

    def test_valid_manifest_is_not_reported(self):
        self.assertEqual(self.detect("# c\n{'name': 'x', 'depends': ['base']}\n"), [])


class VersionPrefixTests(unittest.TestCase):
    def test_wrong_prefix_is_reported(self):
        findings = mh.flag_version_prefix(doc("{'version': '16.0.1.2.3'}\n"), ctx("*.manifest.version-prefix"),
                                          target="18.0")
        self.assertEqual([f.matched for f in findings], ["'16.0.1.2.3'"])

    def test_matching_prefix_is_not_reported(self):
        self.assertEqual(mh.flag_version_prefix(doc("{'version': '18.0.1.0.0'}\n"),
                                                ctx("*.manifest.version-prefix"), target="18.0"), [])

    def test_missing_version_is_not_reported(self):
        self.assertEqual(mh.flag_version_prefix(doc("{'name': 'x'}\n"), ctx("*.manifest.version-prefix"),
                                                target="18.0"), [])

    def test_fix_preserves_suffix_and_quotes(self):
        d = doc('{"version": "16.0.1.2.3", "name": "x"}\n')
        edits = mh.fix_version_prefix(d, ctx("*.manifest.version-prefix"), target="18.0")
        e = edits[0]
        self.assertEqual(d.text[:e.start] + e.after + d.text[e.end:], '{"version": "18.0.1.2.3", "name": "x"}\n')

    def test_fix_is_idempotent(self):
        d = doc("{'version': '18.0.1.0'}\n")
        self.assertEqual(mh.fix_version_prefix(d, ctx("*.manifest.version-prefix"), target="18.0"), [])

    def test_bare_version_without_suffix_gets_target(self):
        d = doc("{'version': '16.0'}\n")
        edits = mh.fix_version_prefix(d, ctx("*.manifest.version-prefix"), target="18.0")
        self.assertEqual(edits[0].after, "'18.0'")

    def test_invalid_target_raises(self):
        with self.assertRaises(ValueError):
            mh.flag_version_prefix(doc("{}\n"), ctx("*.manifest.version-prefix"), target="x")


class NotInstallableTests(unittest.TestCase):
    def detect(self, text):
        return mh.flag_not_installable(doc(text), ctx("*.manifest.not-installable"))

    def test_installable_false_is_reported(self):
        self.assertEqual(len(self.detect("{'installable': False}\n")), 1)

    def test_installable_true_is_not_reported(self):
        self.assertEqual(self.detect("{'installable': True}\n"), [])

    def test_absent_key_is_not_reported(self):
        self.assertEqual(self.detect("{'name': 'x'}\n"), [])


class MissingDataFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "mod"
        (self.root / "views").mkdir(parents=True)
        (self.root / "security").mkdir()
        (self.root / "views" / "a.xml").write_text("<odoo/>")
        (self.root / "security" / "ir.model.access.csv").write_text("id\n")

    def detect(self, text):
        d = doc(text, str(self.root / "__manifest__.py"))
        return mf.flag_missing_data_files(d, ctx("*.manifest.missing-data-file"))

    def test_missing_file_is_reported(self):
        findings = self.detect("{'data': ['views/a.xml', 'views/gone.xml']}\n")
        self.assertEqual([f.matched for f in findings], ["'views/gone.xml'"])

    def test_missing_demo_and_asset_paths_are_reported(self):
        text = "{'demo': ['demo/d.xml'], 'assets': {'web.assets_backend': ['mod/static/x.js']}}\n"
        self.assertEqual(len(self.detect(text)), 2)

    def test_present_files_are_not_reported(self):
        self.assertEqual(self.detect("{'data': ['views/a.xml', 'security/ir.model.access.csv']}\n"), [])

    def test_glob_and_prefixed_asset_directives_are_not_reported(self):
        text = "{'assets': {'web.assets_backend': ['mod/static/src/**/*', ('include', 'web.assets_x')]}}\n"
        self.assertEqual(self.detect(text), [])

    def test_unparseable_manifest_yields_nothing(self):
        self.assertEqual(self.detect("{'data': [foo()]}\n"), [])


class LoadOrderTests(unittest.TestCase):
    def detect(self, text):
        return mf.flag_load_order(doc(text), ctx("*.manifest.load-order"))

    def test_security_after_views_is_reported(self):
        findings = self.detect("{'data': ['views/a.xml', 'security/ir.model.access.csv']}\n")
        self.assertEqual([f.matched for f in findings], ["'security/ir.model.access.csv'"])

    def test_security_first_is_not_reported(self):
        self.assertEqual(self.detect("{'data': ['security/s.xml', 'security/ir.model.access.csv', 'views/a.xml']}\n"), [])

    def test_no_views_is_not_reported(self):
        self.assertEqual(self.detect("{'data': ['data/x.xml', 'security/s.xml']}\n"), [])


class CatalogueTests(unittest.TestCase):
    IDS = ("*.manifest.parse-error", "*.manifest.version-prefix", "*.manifest.not-installable",
           "*.manifest.missing-data-file", "*.manifest.load-order")

    def test_shared_rules_are_registered_and_bind(self):
        rules = {r["id"]: r for r in load_knowledge().rules}
        for rid in self.IDS:
            self.assertIn(rid, rules)
            self.assertEqual(rules[rid]["step"], "*")
            bind_rule(rules[rid], BINDABLE_MODULES)

    def test_shared_rules_never_fix_without_evidence(self):
        rules = {r["id"]: r for r in load_knowledge().rules}
        for rid in self.IDS:
            self.assertNotEqual(rules[rid]["maturity"], "FIX_ENABLED")


if __name__ == "__main__":
    unittest.main()
