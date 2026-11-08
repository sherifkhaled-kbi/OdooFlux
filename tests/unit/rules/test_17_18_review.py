"""TST-006-009 (REQ-PY-003, REQ-XML-003): detect-only review rules for 17.0 -> 18.0.

``17-18.python.name-get-removed`` (EV-104), ``17-18.python.name-search-to-search-display-name`` (EV-008, EV-106),
``17-18.xml.cron-numbercall-removed`` (EV-113) and ``17-18.xml.kanban-box-deprecated`` (EV-119). Detectors report
findings; these rules have no fixer, so applying them changes nothing (SC-005). The kanban rule is not review
required (catalogue Group C).
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule
from odooflux.rules.xml import generic as xg

from .. import _setup  # noqa: F401  (src first on sys.path)

NAME_GET = "17-18.python.name-get-removed"
NAME_SEARCH = "17-18.python.name-search-to-search-display-name"
NUMBERCALL = "17-18.xml.cron-numbercall-removed"
KANBAN = "17-18.xml.kanban-box-deprecated"


def ctx(rule_id, severity="WARNING"):
    return RuleContext(rule_id=rule_id, severity=severity, step="17-18", message="review", suggestion="review")


def catalogue(rule_id):
    return next(r for r in load_knowledge().rules if r["id"] == rule_id)


class NameGetTests(unittest.TestCase):
    def detect(self, src):
        return pg.flag_method_override(Document.from_text("m.py", src), ctx(NAME_GET), method="name_get")

    def test_name_get_override_is_reported(self):
        src = "class A(models.Model):\n    def name_get(self):\n        return []\n"
        findings = self.detect(src)
        self.assertEqual([f.line for f in findings], [2])
        self.assertEqual(findings[0].rule_id, NAME_GET)

    def test_display_name_method_is_not_reported(self):
        self.assertEqual(self.detect("class A(models.Model):\n    def _compute_display_name(self):\n        pass\n"), [])

    def test_name_get_call_is_not_an_override(self):
        self.assertEqual(self.detect("class A(models.Model):\n    def f(self):\n        return self.name_get()\n"), [])


class NameSearchTests(unittest.TestCase):
    def detect(self, src):
        return pg.flag_method_override(Document.from_text("m.py", src), ctx(NAME_SEARCH), method="_name_search")

    def test_name_search_override_is_reported(self):
        src = "class A(models.Model):\n    @api.model\n    def _name_search(self, name='', args=None):\n        pass\n"
        self.assertEqual([f.line for f in self.detect(src)], [3])

    def test_search_display_name_override_is_not_reported(self):
        self.assertEqual(self.detect("class A(models.Model):\n    def _search_display_name(self, name):\n        pass\n"), [])


class NumbercallTests(unittest.TestCase):
    def detect(self, text):
        return xg.flag_attribute_value(Document.from_text("cron.xml", text), ctx(NUMBERCALL),
                                       attribute="name", value="numbercall", tag="field")

    def test_numbercall_field_is_reported(self):
        findings = self.detect('<record model="ir.cron" id="c"><field name="numbercall">-1</field></record>')
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].matched, 'name="numbercall"')

    def test_other_cron_fields_are_not_reported(self):
        self.assertEqual(self.detect('<record model="ir.cron" id="c"><field name="interval_number">1</field></record>'),
                         [])

    def test_numbercall_on_another_element_is_not_reported(self):
        self.assertEqual(self.detect('<group><div name="numbercall"/></group>'), [])


class KanbanBoxTests(unittest.TestCase):
    def detect(self, text):
        return xg.flag_attribute_value(Document.from_text("kanban.xml", text), ctx(KANBAN),
                                       attribute="t-name", value="kanban-box")

    def test_kanban_box_template_is_reported(self):
        self.assertEqual(len(self.detect('<templates><t t-name="kanban-box"><div/></t></templates>')), 1)

    def test_card_template_is_not_reported(self):
        self.assertEqual(self.detect('<templates><t t-name="card"><div/></t></templates>'), [])

    def test_malformed_xml_yields_no_findings(self):
        self.assertEqual(self.detect('<templates><t t-name="kanban-box">'), [])


class CatalogueTests(unittest.TestCase):
    def test_each_rule_binds_as_detect_only_without_fixer(self):
        for rule_id in (NAME_GET, NAME_SEARCH, NUMBERCALL, KANBAN):
            with self.subTest(rule=rule_id):
                bound = bind_rule(catalogue(rule_id), BINDABLE_MODULES)
                self.assertEqual(bound.maturity, "DETECT_ONLY")
                self.assertIsNone(bound.fixer)
                self.assertIsNone(catalogue(rule_id)["fixer_ref"])

    def test_review_flags_follow_catalogue_group_c(self):
        self.assertTrue(bind_rule(catalogue(NAME_GET), BINDABLE_MODULES).review_required)
        self.assertTrue(bind_rule(catalogue(NAME_SEARCH), BINDABLE_MODULES).review_required)
        self.assertTrue(bind_rule(catalogue(NUMBERCALL), BINDABLE_MODULES).review_required)
        self.assertFalse(bind_rule(catalogue(KANBAN), BINDABLE_MODULES).review_required)

    def test_applying_detect_only_rules_changes_nothing(self):
        document = Document.from_text("m.py", "class A(models.Model):\n    def name_get(self):\n        pass\n")
        bound = bind_rule(catalogue(NAME_GET), BINDABLE_MODULES)
        self.assertEqual(bound.fix(document), [])
        self.assertEqual(len(bound.detect(document)), 1)


if __name__ == "__main__":
    unittest.main()
