"""TST-006-0xx (FR-021, T064): inherit-id and xpath-anchor DETECT_ONLY rules over a synthetic view index.

Synthetic data only: the index below is built by hand and is not a claim about any Odoo version. An unavailable
index, an unknown (non-core) module and a scanned module must never be reported as errors (consistent with
FR-011): they are 'unverifiable' INFO findings or are skipped, and never proof of compatibility.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.view_index import ViewIndex, load_view_index
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule
from odooflux.rules.xml import view_refs as vr

from ... import _setup  # noqa: F401

INDEX = ViewIndex.from_dict({
    "format": 1, "version": "16.0", "repository": "odoo/odoo", "revision": "0" * 40, "evidence": "EV-540",
    "modules": ["base", "payment", "web"],
    "views": {"payment": {"payment_provider_form": "", "payment_provider_extra": "payment.payment_provider_form"},
              "base": {"view_partner_form": ""}, "web": {}},
    "anchors": {"payment.payment_provider_form": ["state", "name", "wrap"], "base.view_partner_form": ["phone"]},
})


def _meta(rule_id, func):
    return {"id": rule_id, "step": "*", "maturity": "DETECT_ONLY", "review_required": False, "severity": "WARNING",
            "detector_ref": f"odooflux.rules.xml.view_refs:{func}", "fixer_ref": None, "params": {},
            "tests": {"positive": "T", "negative": "T"}}


META_INHERIT = _meta("*.xml.inherit-id-missing-in-target", "flag_inherit_id_missing")
META_XPATH = _meta("*.xml.xpath-anchor-missing-in-target", "flag_xpath_anchor_missing")


def ctx(rule_id="*.xml.x", severity="WARNING"):
    return RuleContext(rule_id=rule_id, severity=severity, step="15-16", message="m", suggestion="s")


def doc(text, path="mod/views/v.xml"):
    return Document.from_text(path, text)


def record(inherit, arch="<xpath expr=\"//field[@name='state']\" position=\"after\"/>"):
    return ('<odoo><record id="v1" model="ir.ui.view"><field name="model">x</field>'
            f'<field name="inherit_id" ref="{inherit}"/><field name="arch" type="xml">{arch}</field>'
            '</record></odoo>')


class InheritIdTests(unittest.TestCase):
    def detect(self, text, **kw):
        kw.setdefault("index", INDEX)
        kw.setdefault("target", "16.0")
        return vr.flag_inherit_id_missing(doc(text), ctx(), **kw)

    def test_present_core_view_is_not_reported(self):
        self.assertEqual(self.detect(record("payment.payment_provider_form")), [])

    def test_absent_core_view_is_reported_as_warning(self):
        out = self.detect(record("payment.payment_acquirer_form"))
        self.assertEqual([f.severity for f in out], ["WARNING"])
        self.assertIn("'payment.payment_acquirer_form'", out[0].message)
        self.assertNotIn("unverifiable", out[0].message.lower())

    def test_line_points_at_the_ref(self):
        text = "<odoo>\n" + record("payment.gone")[len("<odoo>"):]
        self.assertEqual(self.detect(text)[0].line, 2)

    def test_non_core_module_is_unverifiable_info(self):
        out = self.detect(record("sale_enterprise.some_view"))
        self.assertEqual([f.severity for f in out], ["INFO"])
        self.assertIn("unverifiable", out[0].message.lower())

    def test_scanned_module_is_skipped(self):
        self.assertEqual(self.detect(record("my_mod.v"), scanned_modules=frozenset({"my_mod"})), [])

    def test_unprefixed_local_ref_is_skipped(self):
        self.assertEqual(self.detect(record("local_view")), [])

    def test_template_inherit_id_attribute_is_checked(self):
        text = '<odoo><template id="t" inherit_id="payment.gone"><div/></template></odoo>'
        self.assertEqual([f.severity for f in self.detect(text)], ["WARNING"])
        ok = '<odoo><template id="t" inherit_id="base.view_partner_form"><div/></template></odoo>'
        self.assertEqual(self.detect(ok), [])

    def test_index_unavailable_is_unverifiable_never_clean(self):
        out = vr.flag_inherit_id_missing(doc(record("payment.payment_provider_form")), ctx(),
                                         target="99.0", index=None)
        self.assertEqual([f.severity for f in out], ["INFO"])
        self.assertIn("unverifiable", out[0].message.lower())
        self.assertIn("index unavailable", out[0].message.lower())

    def test_without_run_context_the_rule_is_skipped_with_a_gap(self):
        bound = bind_rule(META_INHERIT, BINDABLE_MODULES)
        self.assertEqual(bound.detect(doc(record("payment.gone"))), [])
        self.assertIn("skipped", bound.gap)

    def test_malformed_xml_yields_nothing(self):
        self.assertEqual(self.detect("<odoo><record"), [])

    def test_non_view_inherit_id_fields_are_ignored(self):
        text = '<odoo><record id="a" model="res.partner"><field name="parent_id" ref="base.nothing"/></record></odoo>'
        self.assertEqual(self.detect(text), [])


class XpathAnchorTests(unittest.TestCase):
    def detect(self, text, **kw):
        kw.setdefault("index", INDEX)
        kw.setdefault("target", "16.0")
        return vr.flag_xpath_anchor_missing(doc(text), ctx(), **kw)

    def arch(self, expr):
        return record("payment.payment_provider_form", f'<xpath expr="{expr}" position="after"/>')

    def test_present_name_anchor_is_not_reported(self):
        self.assertEqual(self.detect(self.arch("//field[@name='state']")), [])

    def test_absent_name_anchor_is_reported(self):
        out = self.detect(self.arch("//field[@name='acquirer_id']"))
        self.assertEqual([f.severity for f in out], ["WARNING"])
        self.assertIn("'acquirer_id'", out[0].message)

    def test_anchor_defined_in_an_inheriting_core_view_counts_as_present(self):
        # anchors are stored per inheritance tree root, so an extension view's anchors resolve via the root
        self.assertEqual(self.detect(record("payment.payment_provider_extra", '<xpath expr="//div[@id=\'wrap\']"/>')), [])

    def test_id_anchor_is_checked(self):
        self.assertEqual(["'nope'" in f.message for f in self.detect(self.arch("//div[@id=&quot;nope&quot;]"))], [True])

    def test_action_xmlid_button_names_are_not_anchors(self):
        self.assertEqual(self.detect(self.arch("//button[@name='%(stock.act)d']")), [])

    def test_or_alternatives_are_satisfied_by_any_present_anchor(self):
        self.assertEqual(self.detect(self.arch("//field[@name='gone' or @name='state']")), [])
        out = self.detect(self.arch("//field[@name='gone' or @name='gone2']"))
        self.assertEqual(len(out), 1)
        self.assertIn("'gone' or 'gone2'", out[0].message)

    def test_unnamed_xpath_is_ignored(self):
        self.assertEqual(self.detect(self.arch("//form/sheet")), [])

    def test_shorthand_field_anchor_is_checked(self):
        text = record("payment.payment_provider_form", '<field name="gone" position="after"><field name="new"/></field>')
        self.assertEqual(["'gone'" in f.message for f in self.detect(text)], [True])
        ok = record("payment.payment_provider_form", '<field name="state" position="after"/>')
        self.assertEqual(self.detect(ok), [])

    def test_new_content_inside_position_block_is_not_an_anchor(self):
        text = record("payment.payment_provider_form",
                      '<xpath expr="//field[@name=\'state\']" position="after"><field name="brand_new"/></xpath>')
        self.assertEqual(self.detect(text), [])

    def test_missing_parent_view_is_left_to_inherit_rule(self):
        self.assertEqual(self.detect(record("payment.gone", '<xpath expr="//field[@name=\'q\']"/>')), [])

    def test_non_core_parent_is_unverifiable_info(self):
        out = self.detect(record("sale_enterprise.v", '<xpath expr="//field[@name=\'q\']"/>'))
        self.assertEqual([f.severity for f in out], ["INFO"])
        self.assertIn("unverifiable", out[0].message.lower())

    def test_scanned_parent_is_skipped(self):
        text = record("my_mod.v", '<xpath expr="//field[@name=\'q\']"/>')
        self.assertEqual(self.detect(text, scanned_modules=frozenset({"my_mod"})), [])

    def test_index_unavailable_is_unverifiable_never_clean(self):
        out = vr.flag_xpath_anchor_missing(doc(self.arch("//field[@name='state']")), ctx(), target="99.0", index=None)
        self.assertEqual([f.severity for f in out], ["INFO"])
        self.assertIn("index unavailable", out[0].message.lower())

    def test_without_run_context_the_rule_is_skipped_with_a_gap(self):
        bound = bind_rule(META_XPATH, BINDABLE_MODULES)
        self.assertEqual(bound.detect(doc(self.arch("//field[@name='x']"))), [])
        self.assertIn("skipped", bound.gap)

    def test_template_xpath_is_checked_against_inherit_id_attribute(self):
        text = ('<odoo><template id="t" inherit_id="base.view_partner_form">'
                '<xpath expr="//field[@name=\'mobile\']" position="after"/></template></odoo>')
        self.assertEqual(["'mobile'" in f.message for f in self.detect(text)], [True])


class IndexLoadingTests(unittest.TestCase):
    def test_unknown_version_has_no_index(self):
        self.assertIsNone(load_view_index("99.0"))

    def test_lookups(self):
        self.assertTrue(INDEX.has_module("payment"))
        self.assertFalse(INDEX.has_module("sale"))
        self.assertTrue(INDEX.has_view("payment.payment_provider_form"))
        self.assertFalse(INDEX.has_view("payment.payment_acquirer_form"))
        self.assertIn("state", INDEX.anchors_for("payment.payment_provider_extra"))
        self.assertIsNone(INDEX.anchors_for("payment.nope"))

    def test_malformed_index_is_rejected(self):
        with self.assertRaises(ValueError):
            ViewIndex.from_dict({"format": 1})


if __name__ == "__main__":
    unittest.main()
