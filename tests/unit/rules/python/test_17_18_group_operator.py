"""TST-006-008 (REQ-PY-002): rule 17-18.python.group-operator-renamed (EV-010, EV-118).

The field attribute ``group_operator`` (17.0) is ``aggregator`` in 18.0. The fixer renames the keyword argument of
field constructors only; other callees, string literals and the new spelling are left alone, and a second
application produces no edits.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "17-18.python.group-operator-renamed"
CTX = RuleContext(rule_id=RULE_ID, severity="WARNING", step="17-18", message="renamed", suggestion="rename")
PARAMS = {"callee": "fields.", "keyword": "group_operator", "new_keyword": "aggregator"}
PATH = "m.py"


def fix(src):
    document = Document.from_text(PATH, src)
    result = apply_edits(document, pg.rename_keyword(document, CTX, **PARAMS), precedence=[RULE_ID])
    second = pg.rename_keyword(Document.from_text(PATH, result.text), CTX, **PARAMS)
    return result, second


class GroupOperatorPositiveTests(unittest.TestCase):
    def test_field_keyword_is_renamed(self):
        result, second = fix("x = fields.Float(group_operator='avg')\n")
        self.assertEqual(result.text, "x = fields.Float(aggregator='avg')\n")
        self.assertEqual(second, [])

    def test_module_level_import_alias_is_renamed(self):
        result, _ = fix("from odoo import fields as f\nx = f.Integer(string='n', group_operator='max')\n")
        self.assertEqual(result.text, "from odoo import fields as f\nx = f.Integer(string='n', aggregator='max')\n")

    def test_multiline_call_is_renamed_and_keeps_layout(self):
        src = "class A(models.Model):\n    total = fields.Monetary(\n        group_operator='sum',\n        currency_field='c')\n"
        result, _ = fix(src)
        self.assertEqual(result.text, src.replace("group_operator='sum'", "aggregator='sum'"))

    def test_detector_reports_each_occurrence(self):
        document = Document.from_text(PATH, "a = fields.Float(group_operator='sum')\nb = fields.Char(group_operator='max')\n")
        findings = pg.keyword_in_call(document, CTX, **{k: v for k, v in PARAMS.items() if k != "new_keyword"})
        self.assertEqual([f.line for f in findings], [1, 2])


class GroupOperatorNegativeTests(unittest.TestCase):
    def assertUnchanged(self, src):
        result, second = fix(src)
        self.assertEqual(result.text, src)
        self.assertEqual(second, [])

    def test_other_callee_is_untouched(self):
        self.assertUnchanged("x = models.Float(group_operator='sum')\n")

    def test_already_renamed_keyword_is_untouched(self):
        self.assertUnchanged("x = fields.Float(aggregator='sum')\n")

    def test_string_literal_is_untouched(self):
        self.assertUnchanged("doc = \"fields.Float(group_operator='sum')\"\n")

    def test_group_operator_attribute_access_is_untouched(self):
        self.assertUnchanged("value = record.group_operator\n")


class GroupOperatorIdempotenceTests(unittest.TestCase):
    def test_second_application_on_fixed_text_has_no_edits(self):
        _, second = fix("x = fields.Float(group_operator='sum')\n")
        self.assertEqual(second, [])


class GroupOperatorCatalogueTests(unittest.TestCase):
    def test_catalogue_entry_binds_at_fix_enabled(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.maturity, "FIX_ENABLED")
        self.assertFalse(bound.review_required)
        self.assertIsNotNone(bound.fixer)
        self.assertEqual(meta["tests"], {"positive": "TST-006-008", "negative": "TST-006-008",
                                         "idempotence": "TST-006-008"})


if __name__ == "__main__":
    unittest.main()
