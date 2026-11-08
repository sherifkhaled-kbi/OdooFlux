"""TST-006-018 (REQ-PY-003): detect-only review rules for 16.0 -> 17.0.

``16-17.python.field-states-parameter`` (EV-108), ``16-17.python.name-get-deprecated`` (EV-011),
``16-17.python.read-group-signature`` (EV-012) and ``16-17.python.message-post-with-template`` (EV-207). Each detector
reports; each rule is review-required and has no fixer, so applying the rules changes nothing (SC-005).
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

FIELD_STATES = "16-17.python.field-states-parameter"
NAME_GET = "16-17.python.name-get-deprecated"
READ_GROUP = "16-17.python.read-group-signature"
MESSAGE_POST = "16-17.python.message-post-with-template"
PATH = "m.py"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def detect(rule_id, src):
    return bound(rule_id).detect(Document.from_text(PATH, src))


class FieldStatesTests(unittest.TestCase):
    def test_states_keyword_on_field_is_reported(self):
        findings = detect(FIELD_STATES, "x = fields.Char(string='a', states={'draft': [('readonly', False)]})\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_field_without_states_is_not_reported(self):
        self.assertEqual(detect(FIELD_STATES, "x = fields.Char(string='a')\n"), [])

    def test_states_keyword_on_other_callee_is_not_reported(self):
        self.assertEqual(detect(FIELD_STATES, "x = models.Char(states='draft')\n"), [])


class NameGetTests(unittest.TestCase):
    def test_name_get_override_is_reported(self):
        src = "class A(models.Model):\n    def name_get(self):\n        return []\n"
        self.assertEqual([f.line for f in detect(NAME_GET, src)], [2])

    def test_name_get_call_is_not_an_override(self):
        self.assertEqual(detect(NAME_GET, "class A(models.Model):\n    def f(self):\n        self.name_get()\n"), [])

    def test_display_name_method_is_not_reported(self):
        src = "class A(models.Model):\n    def _compute_display_name(self):\n        pass\n"
        self.assertEqual(detect(NAME_GET, src), [])


class ReadGroupTests(unittest.TestCase):
    def test_read_group_backend_call_is_reported(self):
        findings = detect(READ_GROUP, "res = self._read_group(domain, ['state'], ['amount:sum'])\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_public_read_group_call_is_not_reported(self):
        self.assertEqual(detect(READ_GROUP, "res = self.read_group(domain, ['state'], ['state'])\n"), [])


class MessagePostWithTemplateTests(unittest.TestCase):
    def test_message_post_with_template_call_is_reported(self):
        findings = detect(MESSAGE_POST, "self.message_post_with_template(template.id)\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_message_post_call_is_not_reported(self):
        self.assertEqual(detect(MESSAGE_POST, "self.message_post(body='hi')\n"), [])


class ReviewRulesHaveNoFixerTests(unittest.TestCase):
    def test_each_rule_is_review_required_detect_only(self):
        for rule_id in (FIELD_STATES, NAME_GET, READ_GROUP, MESSAGE_POST):
            rule = bound(rule_id)
            self.assertEqual(rule.maturity, "DETECT_ONLY", rule_id)
            self.assertTrue(rule.review_required, rule_id)
            self.assertIsNone(rule.fixer, rule_id)

    def test_fix_produces_no_edits(self):
        document = Document.from_text(PATH, "x = fields.Char(states='draft')\n")
        self.assertEqual(bound(FIELD_STATES).fix(document), [])

    def test_catalogue_tests_are_recorded(self):
        for rule_id in (FIELD_STATES, NAME_GET, READ_GROUP, MESSAGE_POST):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            self.assertEqual(meta["tests"], {"positive": "TST-006-018", "negative": "TST-006-018"}, rule_id)


if __name__ == "__main__":
    unittest.main()
