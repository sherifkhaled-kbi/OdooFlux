"""TST-006-010 (REQ-PY-002): rule 17-18.python.user-has-groups-removed, DETECT_ONLY (EV-105, EV-308..311).

17.0 ``user_has_groups(groups)`` is removed in 18.0. The 18.0 replacement ``has_groups(group_spec)`` takes a
spec string with optional ``!`` negation, so the call rewrite is not mechanical (EV-310). The rule is therefore
detect-only and review-required: detection reports every call whatever the receiver, and nothing is edited.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import generic as pg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "17-18.python.user-has-groups-removed"
CTX = RuleContext(rule_id=RULE_ID, severity="WARNING", step="17-18", message="review", suggestion="review")
PARAMS = {"method": "user_has_groups"}


def detect(src):
    return pg.flag_method_call(Document.from_text("m.py", src), CTX, **PARAMS)


class UserHasGroupsPositiveTests(unittest.TestCase):
    def test_self_call_is_reported(self):
        findings = detect("class A(models.Model):\n    def f(self):\n        return self.user_has_groups('base.group_user')\n")
        self.assertEqual([f.line for f in findings], [3])
        self.assertEqual(findings[0].matched, "self.user_has_groups")

    def test_env_user_call_is_reported(self):
        self.assertEqual(len(detect("ok = self.env.user.user_has_groups('base.group_system')\n")), 1)

    def test_bare_receiver_call_is_reported(self):
        self.assertEqual(len(detect("ok = user.user_has_groups('base.group_user,base.group_system')\n")), 1)

    def test_each_call_is_reported_in_order(self):
        src = "a = u.user_has_groups('x')\nb = u.user_has_groups('y')\n"
        self.assertEqual([f.line for f in detect(src)], [1, 2])


class UserHasGroupsNegativeTests(unittest.TestCase):
    def test_has_group_is_not_reported(self):
        self.assertEqual(detect("ok = self.env.user.has_group('base.group_user')\n"), [])

    def test_has_groups_is_not_reported(self):
        self.assertEqual(detect("ok = self.env.user.has_groups('base.group_user,!base.group_portal')\n"), [])

    def test_attribute_read_without_call_is_not_reported(self):
        self.assertEqual(detect("f = self.env.user.user_has_groups\n"), [])

    def test_string_literal_is_not_reported(self):
        self.assertEqual(detect("doc = \"self.user_has_groups('x')\"\n"), [])

    def test_method_definition_is_not_a_call(self):
        self.assertEqual(detect("class A(models.Model):\n    def user_has_groups(self, groups):\n        return True\n"), [])

    def test_plain_function_name_call_is_not_reported(self):
        self.assertEqual(detect("ok = user_has_groups('x')\n"), [])


class UserHasGroupsCatalogueTests(unittest.TestCase):
    def test_entry_is_detect_only_review_without_fixer(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.review_required)
        self.assertIsNone(bound.fixer)
        self.assertEqual(meta["evidence"], ["EV-105", "EV-308", "EV-309", "EV-310", "EV-311"])
        self.assertEqual(bound.fix(Document.from_text("m.py", "ok = u.user_has_groups('x')\n")), [])


if __name__ == "__main__":
    unittest.main()
