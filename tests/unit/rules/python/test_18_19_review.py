"""TST-006-012 (REQ-PY-003, REQ-XML-003): detect-only rules for 18.0 -> 19.0. None of them edits a file.

- ``18-19.python.api-returns-removed`` (EV-102, review): ``@api.returns`` is removed in 19.0.
- ``18-19.python.read-group-deprecated`` (EV-004, review): ``read_group`` is deprecated for ``_read_group``.
- ``18-19.python.osv-deprecated`` (EV-002, not review): ``odoo.osv`` is deprecated in 19.0.
- ``18-19.xml.kanban-box-removed`` (EV-119, review): the ``kanban-box`` template name is no longer read.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule
from odooflux.rules.xml import generic as xg

from ... import _setup  # noqa: F401  (src first on sys.path)

API_RETURNS = "18-19.python.api-returns-removed"
READ_GROUP = "18-19.python.read-group-deprecated"
OSV = "18-19.python.osv-deprecated"
KANBAN = "18-19.xml.kanban-box-removed"


def ctx(rule_id):
    return RuleContext(rule_id=rule_id, severity="WARNING", step="18-19", message="review", suggestion="review")


def catalogue(rule_id):
    return next(r for r in load_knowledge().rules if r["id"] == rule_id)


class ApiReturnsTests(unittest.TestCase):
    def detect(self, src):
        return pg.flag_decorator(Document.from_text("m.py", src), ctx(API_RETURNS), decorator="api.returns")

    def test_returns_decorator_is_reported(self):
        src = "class A(models.Model):\n    @api.returns('res.partner')\n    def f(self):\n        return []\n"
        self.assertEqual([f.line for f in self.detect(src)], [2])

    def test_other_api_decorators_are_not_reported(self):
        self.assertEqual(self.detect("class A(models.Model):\n    @api.model\n    def f(self):\n        pass\n"), [])
        self.assertEqual(self.detect("class A(models.Model):\n    @api.depends('x')\n    def f(self):\n        pass\n"), [])


class ReadGroupTests(unittest.TestCase):
    def detect(self, src):
        return pg.flag_method_call(Document.from_text("m.py", src), ctx(READ_GROUP), method="read_group")

    def test_self_and_env_calls_are_reported(self):
        src = "a = self.read_group([], ['x'], ['y'])\nb = self.env['sale.order'].read_group([], [], [])\n"
        self.assertEqual([f.line for f in self.detect(src)], [1, 2])

    def test_replacement_methods_are_not_reported(self):
        self.assertEqual(self.detect("a = self._read_group([], [], [])\nb = self.formatted_read_group([], [], [])\n"), [])

    def test_attribute_read_without_call_is_not_reported(self):
        self.assertEqual(self.detect("f = self.read_group\n"), [])


class OsvTests(unittest.TestCase):
    def detect(self, src):
        return pg.flag_import(Document.from_text("m.py", src), ctx(OSV), module="odoo.osv")

    def test_from_submodule_import_is_reported(self):
        self.assertEqual([f.line for f in self.detect("from odoo.osv import expression\n")], [1])

    def test_from_package_import_of_osv_is_reported(self):
        self.assertEqual(len(self.detect("from odoo import osv\n")), 1)

    def test_plain_import_is_reported(self):
        self.assertEqual(len(self.detect("import odoo.osv\n")), 1)

    def test_other_odoo_imports_are_not_reported(self):
        self.assertEqual(self.detect("from odoo import models, fields\n"), [])
        self.assertEqual(self.detect("from odoo.tools import osv\n"), [])
        self.assertEqual(self.detect("import osvlib\n"), [])


class KanbanBoxRemovedTests(unittest.TestCase):
    def detect(self, text):
        return xg.flag_attribute_value(Document.from_text("k.xml", text), ctx(KANBAN),
                                       attribute="t-name", value="kanban-box")

    def test_kanban_box_template_is_reported(self):
        self.assertEqual(len(self.detect('<templates><t t-name="kanban-box"/></templates>')), 1)

    def test_card_template_is_not_reported(self):
        self.assertEqual(self.detect('<templates><t t-name="card"/></templates>'), [])


class CatalogueTests(unittest.TestCase):
    def test_entries_are_detect_only_without_fixers(self):
        for rule_id in (API_RETURNS, READ_GROUP, OSV, KANBAN):
            with self.subTest(rule=rule_id):
                bound = bind_rule(catalogue(rule_id), BINDABLE_MODULES)
                self.assertEqual(bound.maturity, "DETECT_ONLY")
                self.assertIsNone(bound.fixer)
                self.assertEqual(bound.fix(Document.from_text("m.py", "x = self.read_group([], [], [])\n")), [])

    def test_review_flags_follow_catalogue(self):
        self.assertTrue(bind_rule(catalogue(API_RETURNS), BINDABLE_MODULES).review_required)
        self.assertTrue(bind_rule(catalogue(READ_GROUP), BINDABLE_MODULES).review_required)
        self.assertFalse(bind_rule(catalogue(OSV), BINDABLE_MODULES).review_required)
        self.assertTrue(bind_rule(catalogue(KANBAN), BINDABLE_MODULES).review_required)


if __name__ == "__main__":
    unittest.main()
