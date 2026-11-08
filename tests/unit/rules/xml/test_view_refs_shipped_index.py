"""T077 (FR-021): the shipped view indexes and the bound rules, including the EV-450 golden check.

Golden: EV-450 records `<field name="inherit_id" ref="payment.payment_acquirer_form"/>` in
addons/website_payment/views/payment_acquirer.xml at 15.0 (present) and the 16.0 file naming
`payment.payment_provider_form`; the old id vanished at 16.0.
"""

import json
import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.view_index import VIEW_INDEX_DIR, load_view_index
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

OLD = '<odoo><record id="v" model="ir.ui.view"><field name="inherit_id" ref="payment.payment_acquirer_form"/></record></odoo>'
NEW = OLD.replace("payment_acquirer_form", "payment_provider_form")
VERSIONS = ("12.0", "13.0", "14.0", "15.0", "16.0", "17.0", "18.0", "19.0")
MAX_VERSION_BYTES = 1_000_000
MAX_TOTAL_BYTES = 5_000_000


def rule(rid):
    return next(r for r in load_knowledge().rules if r["id"] == rid)


def run(rid, target, text):
    bound = bind_rule(rule(rid), BINDABLE_MODULES, run_params={"target": target})
    return bound.detect(Document.from_text("website_payment/views/v.xml", text))


class GoldenPaymentAcquirerFormTests(unittest.TestCase):
    RID = "*.xml.inherit-id-missing-in-target"

    def test_ev450_ref_is_absent_at_16_0(self):
        out = run(self.RID, "16.0", OLD)
        self.assertEqual([f.severity for f in out], ["WARNING"])
        self.assertIn("payment.payment_acquirer_form", out[0].message)

    def test_ev450_ref_is_present_at_15_0(self):
        self.assertEqual(run(self.RID, "15.0", OLD), [])

    def test_renamed_ref_resolves_at_16_0(self):
        self.assertEqual(run(self.RID, "16.0", NEW), [])
        self.assertEqual([f.severity for f in run(self.RID, "15.0", NEW)], ["WARNING"])

    def test_rules_are_detect_only_without_fixer_and_cite_index_evidence(self):
        for rid in (self.RID, "*.xml.xpath-anchor-missing-in-target"):
            meta = rule(rid)
            self.assertEqual((meta["maturity"], meta["fixer_ref"]), ("DETECT_ONLY", None))
            self.assertEqual(sorted(meta["evidence"]), [f"EV-54{i}" for i in range(8)])

    def test_unavailable_index_is_never_clean(self):
        out = run(self.RID, "99.0", OLD)
        self.assertEqual([f.severity for f in out], ["INFO"])
        self.assertIn("index unavailable", out[0].message.lower())


class ShippedIndexTests(unittest.TestCase):
    def test_one_index_per_pinned_version_with_matching_provenance(self):
        kb = load_knowledge()
        pins = {r["branch"]: r["revision"] for r in kb.revisions if r["repository"] == "odoo/odoo"}
        for n, version in enumerate(VERSIONS):
            data = json.loads((VIEW_INDEX_DIR / f"{version}.json").read_text(encoding="utf-8"))
            self.assertEqual(data["revision"], pins[version])
            self.assertEqual(data["evidence"], f"EV-54{n}")
            self.assertEqual(data["problems"], [])
            self.assertIsNotNone(load_view_index(version))
            self.assertTrue((KNOWLEDGE_ROOT / "evidence" / f"EV-54{n}.json").is_file())

    def test_size_budget(self):
        sizes = [(VIEW_INDEX_DIR / f"{v}.json").stat().st_size for v in VERSIONS]
        self.assertTrue(all(s <= MAX_VERSION_BYTES for s in sizes), sizes)
        self.assertLessEqual(sum(sizes), MAX_TOTAL_BYTES)

    def test_core_index_contains_known_views(self):
        self.assertTrue(load_view_index("16.0").has_view("payment.payment_provider_form"))
        self.assertTrue(load_view_index("15.0").has_view("payment.payment_acquirer_form"))
        self.assertFalse(load_view_index("17.0").has_view("payment.payment_acquirer_form"))


if __name__ == "__main__":
    unittest.main()
