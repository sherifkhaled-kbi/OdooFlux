"""TST-006-062/073/074 (FR-018, ADR-018 D-A4): the renamed-model family.

Every instance (``<step>.<kind>.model-renamed-<slug>``) is DETECT_ONLY and review_required with no fixer (D-A5 is
not approved). Python, XML and CSV fixtures live in ``tests/golden_fixtures/rules/<rule id>/`` with an
``expected.json`` mapping each fixture file to the exact line numbers a detector must report. Positive files hold
every reference form; negative files hold substrings, comments, docstrings and look-alike names that must stay
silent.
"""

import json
import unittest
from pathlib import Path

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from .. import _setup  # noqa: F401

FIXTURES = Path(__file__).resolve().parents[2] / "golden_fixtures" / "rules"
FAMILY = "model-renamed-"
# slug -> (step, old model, new model, defining module, evidence for the python rule); fixtures exist for payment-provider
INSTANCES = {
    "payment-provider": ("15-16", "payment.acquirer", "payment.provider", "payment", "EV-450"),
    "payment-onboarding-wizard": ("15-16", "payment.acquirer.onboarding.wizard", "payment.provider.onboarding.wizard", "payment", "EV-500"),
    "sale-payment-onboarding-wizard": ("15-16", "sale.payment.acquirer.onboarding.wizard", "sale.payment.provider.onboarding.wizard", "sale", "EV-501"),
    "stock-route": ("15-16", "stock.location.route", "stock.route", "stock", "EV-502"),
    "stock-lot": ("15-16", "stock.production.lot", "stock.lot", "stock", "EV-503"),
    "mail-channel-member": ("15-16", "mail.channel.partner", "mail.channel.member", "mail", "EV-504"),
    "discuss-channel": ("16-17", "mail.channel", "discuss.channel", "mail", "EV-505"),
    "discuss-channel-member": ("16-17", "mail.channel.member", "discuss.channel.member", "mail", "EV-506"),
    "discuss-channel-rtc-session": ("16-17", "mail.channel.rtc.session", "discuss.channel.rtc.session", "mail", "EV-507"),
    "mail-canned-response": ("17-18", "mail.shortcode", "mail.canned.response", "mail", "EV-508"),
    "mail-push-device": ("17-18", "mail.partner.device", "mail.push.device", "mail", "EV-509"),
    "stock-package": ("18-19", "stock.quant.package", "stock.package", "stock", "EV-510"),
}
KINDS = ("python", "xml", "csv")
# rule id -> evidence ids the rule must cite (each one researched in research-notes/models.md)
EVIDENCE = {}
for _slug, (_step, _o, _n, _m, _ev) in INSTANCES.items():
    EVIDENCE[f"{_step}.python.{FAMILY}{_slug}"] = {_ev}
    EVIDENCE[f"{_step}.xml.{FAMILY}{_slug}"] = {_ev, "EV-515"}
    EVIDENCE[f"{_step}.csv.{FAMILY}{_slug}"] = {_ev, "EV-515"}
EVIDENCE["15-16.xml.model-renamed-payment-provider"] |= {"EV-511", "EV-513"}
EVIDENCE["15-16.csv.model-renamed-payment-provider"] |= {"EV-511"}
KNOWLEDGE = load_knowledge()


def meta(rule_id):
    return next(r for r in KNOWLEDGE.rules if r["id"] == rule_id)


def bound(rule_id):
    return bind_rule(meta(rule_id), BINDABLE_MODULES)


def lines(rule_id, text, path="f"):
    return [f.line for f in bound(rule_id).detect(Document.from_text(path, text))]


def fixture_dirs():
    return sorted(d for d in FIXTURES.glob(f"*.{FAMILY}*") if d.is_dir())


class FixtureTests(unittest.TestCase):
    def test_every_registered_instance_has_fixtures_and_vice_versa(self):
        registered = {r["id"] for r in KNOWLEDGE.rules if FAMILY in r["id"]}
        self.assertEqual(registered, set(EVIDENCE))
        self.assertEqual({d.name for d in fixture_dirs()},
                         {f"15-16.{k}.{FAMILY}payment-provider" for k in KINDS})

    def test_fixtures_report_exactly_the_expected_lines(self):
        for directory in fixture_dirs():
            expected = json.loads((directory / "expected.json").read_text())
            for name, want in expected.items():
                with self.subTest(rule=directory.name, file=name):
                    text = (directory / name).read_text(encoding="utf-8")
                    self.assertEqual(lines(directory.name, text, name), want)

    def test_each_instance_has_positive_and_negative_files(self):
        for directory in fixture_dirs():
            expected = json.loads((directory / "expected.json").read_text())
            self.assertTrue(any(v for v in expected.values()), directory.name)
            self.assertTrue(any(not v for v in expected.values()), directory.name)


class MetadataTests(unittest.TestCase):
    def test_instances_are_detect_only_review_required_without_fixer(self):
        for rule_id, evidence in EVIDENCE.items():
            with self.subTest(rule=rule_id):
                row = meta(rule_id)
                self.assertEqual(row["maturity"], "DETECT_ONLY")
                self.assertIs(row["review_required"], True)
                self.assertIsNone(row["fixer_ref"])
                self.assertTrue(evidence <= set(row["evidence"]))
                rule = bound(rule_id)
                self.assertIsNone(rule.fixer)
                self.assertEqual(rule.fix(Document.from_text("f", "class A:\n    _inherit = 'payment.acquirer'\n")), [])

    def test_evidence_records_exist(self):
        ids = set(KNOWLEDGE.evidence)
        for rule_id in EVIDENCE:
            self.assertTrue(set(meta(rule_id)["evidence"]) <= ids, rule_id)

    def test_rename_is_bound_to_its_step_only(self):
        """Multi-step run 15 to 19: only the 15-16 step reports; later steps add no duplicate finding."""
        for slug, (step, old, _new, _mod, _ev) in INSTANCES.items():
            rows = [r for r in KNOWLEDGE.rules if r.get("params", {}).get("old") == old]
            self.assertEqual({r["step"] for r in rows}, {step}, slug)
            self.assertEqual({r["id"] for r in rows}, {f"{step}.{k}.{FAMILY}{slug}" for k in KINDS}, slug)


def python_ref(old):
    return f"class A:\n    _inherit = '{old}'\n    f = fields.Many2one(comodel_name='{old}')\n    g = self.env['{old}']\n"


class InstanceTests(unittest.TestCase):
    """T074: every further rename has positive and negative cases for Python, XML and CSV."""

    def test_python(self):
        for slug, (step, old, new, _mod, _ev) in INSTANCES.items():
            rule = f"{step}.python.{FAMILY}{slug}"
            with self.subTest(rule=rule):
                self.assertEqual(lines(rule, python_ref(old)), [2, 3, 4])
                self.assertEqual(lines(rule, python_ref(new)), [])
                self.assertEqual(lines(rule, python_ref(f"x.{old}") + f"# _inherit = '{old}'\n"), [])
                self.assertEqual(lines(rule, python_ref(f"{old}.extra")), [])

    def test_xml(self):
        for slug, (step, old, new, mod, _ev) in INSTANCES.items():
            rule = f"{step}.xml.{FAMILY}{slug}"
            ids = f"{mod}.model_{old.replace('.', '_')}"
            positive = (f'<odoo>\n<record id="a" model="{old}"/>\n<field name="res_model">{old}</field>\n'
                        f'<field name="model_id" ref="{ids}"/>\n</odoo>')
            negative = (f'<odoo>\n<!-- model="{old}" -->\n<record id="a" model="{new}"/>\n<record model="{old}.extra"/>\n'
                        f'<field name="model_id" ref="{ids}_extra"/>\n<field name="x" ref="other.model_{old.replace(".", "_")}"/>\n</odoo>')
            with self.subTest(rule=rule):
                self.assertEqual(lines(rule, positive), [2, 3, 4])
                self.assertEqual(lines(rule, negative), [])

    def test_csv(self):
        head = "id,name,model_id:id,perm_read\n"
        for slug, (step, old, new, mod, _ev) in INSTANCES.items():
            rule = f"{step}.csv.{FAMILY}{slug}"
            ids = f"{mod}.model_{old.replace('.', '_')}"
            with self.subTest(rule=rule):
                self.assertEqual(lines(rule, head + f"a,a,{ids},1\nb,b,{mod}.model_{new.replace('.', '_')},1\n"), [2])
                self.assertEqual(lines(rule, head + f"a,a,{ids}_extra,1\nb,b,model_{old.replace('.', '_')},1\n"), [])


class PythonEdgeTests(unittest.TestCase):
    RULE = "15-16.python.model-renamed-payment-provider"

    def test_forms(self):
        for src in ("class A:\n    _inherit = 'payment.acquirer'\n", "class A:\n    _inherit = ('a', 'payment.acquirer')\n",
                    "class A:\n    _name: str = 'payment.acquirer'\n", "x = self.env['payment.acquirer']\n",
                    "class A:\n    _inherits = {'payment.acquirer': 'f'}\n",
                    "f = fields.Many2one('payment.acquirer')\n", "f = fields.Many2one(comodel_name='payment.acquirer')\n"):
            self.assertEqual(lines(self.RULE, src), [2 if src.startswith("class") else 1], src)

    def test_substring_comment_and_docstring_are_silent(self):
        for src in ("# _inherit = 'payment.acquirer'\n", "x = 'my.payment.acquirer'\n",
                    "class A:\n    _inherit = 'payment.acquirer.x'\n", "class A:\n    _inherit = 'payment.acquirer_x'\n",
                    '"""env[\'payment.acquirer\']"""\n', "log('payment.acquirer')\n", "x = 'payment.acquirer'\n",
                    "_inherit = 'payment.acquirer'\n"):
            self.assertEqual(lines(self.RULE, src), [], src)

    def test_syntax_error_yields_nothing(self):
        self.assertEqual(lines(self.RULE, "class A:\n    _inherit = 'payment.acquirer'\ndef (:\n"), [])

    def test_finding_matches_the_literal(self):
        found = bound(self.RULE).detect(Document.from_text("m.py", "class A:\n    _inherit = 'payment.acquirer'\n"))
        self.assertEqual([f.matched for f in found], ["'payment.acquirer'"])
        self.assertEqual(found[0].rule_id, self.RULE)


class XmlEdgeTests(unittest.TestCase):
    RULE = "15-16.xml.model-renamed-payment-provider"

    def test_malformed_xml_yields_nothing(self):
        self.assertEqual(lines(self.RULE, '<odoo><record model="payment.acquirer"></odoo>'), [])

    def test_attribute_and_text_forms(self):
        self.assertEqual(lines(self.RULE, '<odoo><record id="a" model="payment.acquirer"/></odoo>'), [1])
        self.assertEqual(lines(self.RULE, '<odoo><field name="res_model"> payment.acquirer </field></odoo>'), [1])

    def test_comment_and_substring_are_silent(self):
        self.assertEqual(lines(self.RULE, '<odoo><!-- model="payment.acquirer" --></odoo>'), [])
        self.assertEqual(lines(self.RULE, '<odoo><record model="payment.acquirers"/></odoo>'), [])


class CsvEdgeTests(unittest.TestCase):
    RULE = "15-16.csv.model-renamed-payment-provider"
    HEAD = "id,name,model_id:id,perm_read\n"

    def test_qualified_model_xml_id_is_reported(self):
        self.assertEqual(lines(self.RULE, self.HEAD + "a,a,payment.model_payment_acquirer,1\n"), [2])

    def test_unrelated_column_and_other_module_are_silent(self):
        self.assertEqual(lines(self.RULE, "id,name,x\na,payment.model_payment_acquirer,1\n"), [])
        self.assertEqual(lines(self.RULE, self.HEAD + "a,a,mymod.model_payment_acquirer,1\n"), [])

    def test_quoted_cell_and_crlf(self):
        self.assertEqual(lines(self.RULE, self.HEAD.replace("\n", "\r\n") + 'a,"a, b","payment.model_payment_acquirer",1\r\n'), [2])

    def test_empty_file(self):
        self.assertEqual(lines(self.RULE, ""), [])


if __name__ == "__main__":
    unittest.main()
