"""Experimental attrs fixer: field names that mean something else in a modifier expression (QA D1).

In an Odoo 17 modifier, the names listed in RESERVED are evaluation-context variables, and a Python keyword or
True/False/None cannot be a field name. A leaf whose left operand is one of them is refused as ``reserved-name``.
"""

import unittest

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.engine.documents import Document
from odooflux.rules.experimental import xml_modifiers as xm

RESERVED = ("uid", "context", "context_today", "current_date", "today", "now", "time", "datetime",
            "relativedelta", "parent", "active_id", "active_ids", "active_model", "allowed_company_ids")
KEYWORDS = ("class", "in", "not", "True", "False", "None", "if")


def plan(inner):
    return xm.plan_attrs(Document.from_text("v.xml", f"<form>{inner}</form>"))


def field_with(domain):
    return f"""<field name="a" attrs="{{'invisible': {domain}}}"/>"""


class ReservedNameRefusalTests(unittest.TestCase):
    def test_every_reserved_name_as_left_operand_is_refused(self):
        for name in RESERVED:
            with self.subTest(name=name):
                result = plan(field_with(f"[('{name}', '=', 1)]"))
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], ["reserved-name"])

    def test_reserved_name_inside_a_compound_domain_refuses_the_whole_element(self):
        result = plan(field_with("['|', ('state', '=', 'a'), ('uid', 'in', [1, 2])]"))
        self.assertEqual(result.edits, ())
        self.assertEqual([r.reason for r in result.refused], ["reserved-name"])

    def test_python_keywords_and_literal_constants_are_refused(self):
        for name in KEYWORDS:
            with self.subTest(name=name):
                result = plan(field_with(f"[('{name}', '=', 1)]"))
                self.assertEqual(result.edits, ())
                self.assertEqual([r.reason for r in result.refused], ["reserved-name"])

    def test_refused_reserved_element_is_left_byte_identical(self):
        text = "<form>" + field_with("[('uid', '=', 1)]") + "</form>"
        self.assertEqual(xm.plan_attrs(Document.from_text("v.xml", text)).edits, ())


class ReservedNameNonRefusalTests(unittest.TestCase):
    def test_reserved_name_on_the_right_side_is_a_literal_and_converts(self):
        result = plan(field_with("[('state', '=', 'uid')]"))
        self.assertEqual(result.refused, ())
        self.assertEqual([c.after for c in result.converted],
                         ["""invisible="state == 'uid'\""""])

    def test_fields_that_only_contain_a_reserved_substring_still_convert(self):
        for name in ("user_uid", "today_count", "uid_partner", "context_id"):
            with self.subTest(name=name):
                result = plan(field_with(f"[('{name}', '=', 1)]"))
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)

    def test_supported_cases_keep_converting(self):
        for domain in ("[('state', '=', 'done')]",
                       "[('state', 'in', ['draft', 'sent'])]",
                       "[('state', 'not in', ['x'])]",
                       "['|', ('state', '=', 'a'), ('amount', '=', 1)]",
                       "[('state', '=', 'a'), ('amount', '!=', 1)]"):
            with self.subTest(domain=domain):
                result = plan(field_with(domain))
                self.assertEqual(result.refused, ())
                self.assertEqual(len(result.converted), 1)


if __name__ == "__main__":
    unittest.main()
