"""TST-006-023 (REQ-PY-002, REQ-PY-003): rules for 12.0 -> 13.0.

- ``12-13.python.api-multi-removed`` (FIX, EV-101): ``@api.multi`` decorator removed (multi is the default in 13.0).
- ``12-13.python.api-one-removed`` (DETECT review, EV-101): ``@api.one`` reported; the replacement needs review.
- ``12-13.python.sudo-user-argument`` (DETECT review, EV-103, EV-349): ``sudo(user)`` reported. 12.0 ``sudo(user)``
  switches uid and 13.0 ``sudo(flag)`` toggles superuser, so the rewrite is not equivalent (EV-349). A boolean
  literal ``sudo(True)`` / ``sudo(False)`` is the 13.0 form and produces no finding.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

MULTI = "12-13.python.api-multi-removed"
ONE = "12-13.python.api-one-removed"
SUDO = "12-13.python.sudo-user-argument"
PATH = "m.py"


def bound(rule_id):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def run_fix(src):
    rule = bound(MULTI)
    document = Document.from_text(PATH, src)
    result = apply_edits(document, rule.fix(document), precedence=[MULTI])
    second = rule.fix(Document.from_text(PATH, result.text))
    return result.text, second


def detect(rule_id, src):
    return bound(rule_id).detect(Document.from_text(PATH, src))


CLASS = "from odoo import api, models\n\n\nclass A(models.Model):\n{body}"


class ApiMultiTests(unittest.TestCase):
    def test_api_multi_decorator_is_removed(self):
        src = CLASS.format(body="    @api.multi\n    def f(self):\n        return True\n")
        text, _ = run_fix(src)
        self.assertEqual(text, CLASS.format(body="    def f(self):\n        return True\n"))

    def test_api_multi_is_reported(self):
        src = CLASS.format(body="    @api.multi\n    def f(self):\n        return True\n")
        self.assertEqual([f.line for f in detect(MULTI, src)], [5])

    def test_api_model_decorator_is_untouched(self):
        src = CLASS.format(body="    @api.model\n    def f(self):\n        return True\n")
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_multi_from_another_module_is_untouched(self):
        src = "from mylib import api\n\n\n@api.multi\ndef f(self):\n    pass\n"
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_fixed_text_is_idempotent(self):
        src = CLASS.format(body="    @api.multi\n    def f(self):\n        return True\n")
        _, second = run_fix(src)
        self.assertEqual(second, [])


class ApiOneTests(unittest.TestCase):
    def test_api_one_is_reported(self):
        src = CLASS.format(body="    @api.one\n    def f(self):\n        return True\n")
        self.assertEqual([f.line for f in detect(ONE, src)], [5])

    def test_api_model_is_not_reported(self):
        self.assertEqual(detect(ONE, CLASS.format(body="    @api.model\n    def f(self):\n        pass\n")), [])

    def test_rule_is_detect_only_review_required_without_a_fixer(self):
        rule = bound(ONE)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertTrue(rule.review_required)
        self.assertIsNone(rule.fixer)


class SudoUserArgumentTests(unittest.TestCase):
    def test_sudo_with_user_record_is_reported(self):
        self.assertEqual([f.line for f in detect(SUDO, "x = self.env['res.users'].sudo(user_id)\n")], [1])

    def test_sudo_with_user_keyword_is_reported(self):
        self.assertEqual(len(detect(SUDO, "x = self.sudo(user=3)\n")), 1)

    def test_sudo_with_env_user_is_reported(self):
        self.assertEqual(len(detect(SUDO, "x = self.sudo(self.env.user)\n")), 1)

    def test_boolean_literal_sudo_is_not_reported(self):
        self.assertEqual(detect(SUDO, "a = self.sudo(True)\nb = self.sudo(False)\n"), [])

    def test_sudo_flag_keyword_is_not_reported(self):
        self.assertEqual(detect(SUDO, "a = self.sudo(flag=True)\n"), [])

    def test_sudo_without_argument_is_not_reported(self):
        self.assertEqual(detect(SUDO, "a = self.sudo()\n"), [])

    def test_rule_is_detect_only_review_required_without_a_fixer(self):
        rule = bound(SUDO)
        self.assertEqual(rule.maturity, "DETECT_ONLY")
        self.assertTrue(rule.review_required)
        self.assertIsNone(rule.fixer)


class CatalogueTests(unittest.TestCase):
    def test_tests_are_recorded_for_each_rule(self):
        for rule_id in (MULTI, ONE, SUDO):
            meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
            self.assertEqual(meta["tests"]["positive"], "TST-006-023", rule_id)
            self.assertEqual(meta["tests"]["negative"], "TST-006-023", rule_id)
        meta = next(r for r in load_knowledge().rules if r["id"] == MULTI)
        self.assertEqual(meta["tests"]["idempotence"], "TST-006-023")


if __name__ == "__main__":
    unittest.main()
