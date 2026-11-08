"""TST-006-013 (REQ-PY-003): bespoke detector for 18-19.python.sql-constraints-unsupported (EV-006, EV-116).

In 19.0 ``_sql_constraints`` is not applied (a warning only); constraints are ``models.Constraint`` table objects.
The detector reports each constraint tuple of a class-body ``_sql_constraints`` with the suggested declaration as
text. It never edits. Severity is CRITICAL.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import sql_constraints as sc
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "18-19.python.sql-constraints-unsupported"
CTX = RuleContext(rule_id=RULE_ID, severity="CRITICAL", step="18-19",
                  message="_sql_constraints is not applied in 19.0", suggestion="declare models.Constraint")


def detect(src):
    return sc.flag_sql_constraints(Document.from_text("m.py", src), CTX)


class SqlConstraintPositiveTests(unittest.TestCase):
    SRC = ("class Order(models.Model):\n"
           "    _sql_constraints = [\n"
           "        ('name_uniq', 'UNIQUE(name)', 'Name must be unique'),\n"
           "        ('qty_positive', 'CHECK(qty > 0)', 'Quantity must be positive'),\n"
           "    ]\n")

    def test_each_constraint_tuple_is_reported_on_its_line(self):
        findings = detect(self.SRC)
        self.assertEqual([f.line for f in findings], [3, 4])
        self.assertTrue(all(f.severity == "CRITICAL" and f.rule_id == RULE_ID for f in findings))

    def test_message_names_the_constraint(self):
        findings = detect(self.SRC)
        self.assertIn("name_uniq", findings[0].message)
        self.assertIn("qty_positive", findings[1].message)

    def test_suggestion_is_the_models_constraint_form_as_text(self):
        findings = detect(self.SRC)
        self.assertEqual(findings[0].suggestion,
                         "name_uniq = models.Constraint('UNIQUE(name)', 'Name must be unique')  "
                         "(text only; review before use)")

    def test_annotated_assignment_is_reported(self):
        src = "class A(models.Model):\n    _sql_constraints: list = [('a_uniq', 'UNIQUE(a)', 'A unique')]\n"
        self.assertEqual([f.line for f in detect(src)], [2])

    def test_non_literal_value_is_reported_once_on_the_assignment(self):
        findings = detect("class A(models.Model):\n    _sql_constraints = build_constraints()\n")
        self.assertEqual([f.line for f in findings], [2])
        self.assertIn("cannot be read", findings[0].message)

    def test_empty_list_still_reports_the_unsupported_attribute(self):
        findings = detect("class A(models.Model):\n    _sql_constraints = []\n")
        self.assertEqual([f.line for f in findings], [2])


class SqlConstraintNegativeTests(unittest.TestCase):
    def test_model_without_the_attribute_is_clean(self):
        self.assertEqual(detect("class A(models.Model):\n    _name = 'a'\n"), [])

    def test_table_object_constraint_is_clean(self):
        self.assertEqual(detect("class A(models.Model):\n    _name_uniq = models.Constraint('UNIQUE(name)', 'x')\n"), [])

    def test_read_of_the_attribute_is_not_a_declaration(self):
        self.assertEqual(detect("def f(self):\n    return self._sql_constraints\n"), [])

    def test_string_literal_is_clean(self):
        self.assertEqual(detect("doc = \"_sql_constraints = []\"\n"), [])

    def test_malformed_python_yields_no_findings(self):
        self.assertEqual(detect("class A(models.Model):\n    _sql_constraints = [\n"), [])


class SqlConstraintCatalogueTests(unittest.TestCase):
    def test_entry_binds_as_critical_detect_only_without_fixer(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.context.severity, "CRITICAL")
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.review_required)
        self.assertIsNone(bound.fixer)
        self.assertEqual(meta["evidence"], ["EV-006", "EV-116"])
        document = Document.from_text("m.py", "class A(models.Model):\n    _sql_constraints = []\n")
        self.assertEqual(bound.fix(document), [])
        self.assertEqual(len(bound.detect(document)), 1)


if __name__ == "__main__":
    unittest.main()
