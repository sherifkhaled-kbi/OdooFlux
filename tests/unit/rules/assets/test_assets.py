"""TST-006-032 (REQ-JS-003): ``14-15.manifest.qweb-key`` and XML asset-template detection (detect-only; the
transition is not mechanical, EV-330)."""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.assets import generic as ag
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

QWEB_KEY = "14-15.manifest.qweb-key"
TEMPLATE = "14-15.assets.xml-asset-template"


def ctx(rid):
    return RuleContext(rule_id=rid, severity="WARNING", step="14-15", message="m", suggestion="s")


def doc(text, path):
    return Document.from_text(path, text)


class QwebKeyTests(unittest.TestCase):
    def detect(self, text):
        return ag.flag_manifest_key(doc(text, "m/__manifest__.py"), ctx(QWEB_KEY), key="qweb")

    def test_qweb_key_is_reported(self):
        findings = self.detect("{\n 'name': 'm',\n 'qweb': ['static/src/xml/a.xml'],\n}\n")
        self.assertEqual([f.line for f in findings], [3])
        self.assertEqual(findings[0].matched, "'qweb'")

    def test_assets_key_is_not_reported(self):
        self.assertEqual(self.detect("{'assets': {'web.assets_qweb': ['m/static/src/xml/a.xml']}}\n"), [])

    def test_qweb_inside_a_value_is_not_reported(self):
        self.assertEqual(self.detect("{'name': 'qweb', 'description': 'uses qweb'}\n"), [])

    def test_unparseable_manifest_yields_nothing(self):
        self.assertEqual(self.detect("{'qweb': [x()}\n"), [])


class AssetTemplateTests(unittest.TestCase):
    def detect(self, text):
        return ag.flag_asset_templates(doc(text, "views/assets.xml"), ctx(TEMPLATE))

    def test_template_inheriting_a_bundle_is_reported(self):
        text = ('<odoo>\n  <template id="a" inherit_id="web.assets_backend" name="x">\n'
                '    <xpath expr="." position="inside"><script src="/m/a.js"/></xpath>\n  </template>\n</odoo>\n')
        findings = self.detect(text)
        self.assertEqual([f.line for f in findings], [2])
        self.assertEqual(findings[0].matched, "web.assets_backend")

    def test_frontend_and_lazy_bundles_are_reported(self):
        text = ('<odoo><template id="a" inherit_id="website.assets_frontend"/>'
                '<template id="b" inherit_id="web.assets_common_lazy"/></odoo>')
        self.assertEqual(len(self.detect(text)), 2)

    def test_view_template_inheritance_is_not_reported(self):
        self.assertEqual(self.detect('<odoo><template id="a" inherit_id="web.layout"/></odoo>'), [])

    def test_template_without_inherit_is_not_reported(self):
        self.assertEqual(self.detect('<odoo><template id="assets_x" name="x"/></odoo>'), [])

    def test_malformed_xml_yields_nothing(self):
        self.assertEqual(self.detect('<odoo><template inherit_id="web.assets_backend">'), [])


class CatalogueTests(unittest.TestCase):
    def rules(self):
        return {r["id"]: r for r in load_knowledge().rules}

    def test_entries_are_detect_only_without_fixer_at_recorded_maturity(self):
        rules = self.rules()
        for rid in (QWEB_KEY, TEMPLATE):
            bound = bind_rule(rules[rid], BINDABLE_MODULES)
            self.assertEqual(bound.maturity, "DETECT_ONLY", rid)
            self.assertIsNone(bound.fixer, rid)
        self.assertEqual(rules[QWEB_KEY]["evidence"][:2], ["EV-123", "EV-124"])


if __name__ == "__main__":
    unittest.main()
