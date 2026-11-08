"""TST-006-016 (REQ-PY-002): rule 16-17.python.warning-exception (EV-110).

``odoo.exceptions.Warning`` is a subclass of ``UserError`` in 14.0-16.0 and no longer a class in 17.0. The fixer
renames the name to ``UserError`` at its import and at every reference bound to that import. The import rewrite is
what injects ``UserError`` into the module. An ``except Warning`` clause is not rewritten: ``except UserError`` catches
a wider set than ``except Warning``, so a file with one is left unchanged and reported.
"""

import ast
import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "16-17.python.warning-exception"
PATH = "m.py"


def bound(rule_id=RULE_ID):
    meta = next(r for r in load_knowledge().rules if r["id"] == rule_id)
    return bind_rule(meta, BINDABLE_MODULES)


def run_fix(src, rule_id=RULE_ID):
    rule = bound(rule_id)
    document = Document.from_text(PATH, src)
    result = apply_edits(document, rule.fix(document), precedence=[rule_id])
    second = rule.fix(Document.from_text(PATH, result.text))
    return result.text, second


def detect(src):
    rule = bound()
    return rule.detect(Document.from_text(PATH, src))


class WarningExceptionPositiveTests(unittest.TestCase):
    def test_import_and_raise_are_renamed_to_user_error(self):
        src = "from odoo.exceptions import Warning\n\n\ndef f():\n    raise Warning('x')\n"
        text, _ = run_fix(src)
        self.assertEqual(text, "from odoo.exceptions import UserError\n\n\ndef f():\n    raise UserError('x')\n")

    def test_output_compiles(self):
        src = "from odoo.exceptions import Warning\nraise Warning('x')\n"
        text, _ = run_fix(src)
        compile(text, PATH, "exec")
        self.assertIn("UserError", text)

    def test_mixed_import_keeps_other_names(self):
        text, _ = run_fix("from odoo.exceptions import ValidationError, Warning\nraise Warning('x')\n")
        self.assertEqual(text, "from odoo.exceptions import ValidationError, UserError\nraise UserError('x')\n")

    def test_aliased_import_keeps_local_name(self):
        text, _ = run_fix("from odoo.exceptions import Warning as W\nraise W('x')\n")
        self.assertEqual(text, "from odoo.exceptions import UserError as W\nraise W('x')\n")

    def test_module_attribute_form_is_renamed(self):
        text, _ = run_fix("from odoo import exceptions\nraise exceptions.Warning('x')\n")
        self.assertEqual(text, "from odoo import exceptions\nraise exceptions.UserError('x')\n")

    def test_detector_reports_import_and_each_reference(self):
        src = "from odoo.exceptions import Warning\n\n\ndef f():\n    raise Warning('a')\n    raise Warning('b')\n"
        self.assertEqual([f.line for f in detect(src)], [1, 5, 6])


class WarningExceptionNegativeTests(unittest.TestCase):
    def assertUnchanged(self, src):
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_user_error_import_is_untouched(self):
        self.assertUnchanged("from odoo.exceptions import UserError\nraise UserError('x')\n")

    def test_unimported_builtin_name_is_untouched(self):
        self.assertUnchanged("raise Warning('x')\n")

    def test_other_module_warning_is_untouched(self):
        self.assertUnchanged("from mylib.exceptions import Warning\nraise Warning('x')\n")

    def test_string_literal_is_untouched(self):
        self.assertUnchanged("from odoo.exceptions import UserError\nmsg = 'Warning'\n")

    def test_except_clause_blocks_the_whole_file(self):
        src = ("from odoo.exceptions import Warning\n\ntry:\n    pass\nexcept Warning:\n    pass\n"
               "raise Warning('x')\n")
        self.assertUnchanged(src)
        self.assertEqual(len(detect(src)), 3)


class WarningExceptionIdempotenceTests(unittest.TestCase):
    def test_second_application_on_fixed_text_has_no_edits(self):
        _, second = run_fix("from odoo.exceptions import Warning\nraise Warning('x')\n")
        self.assertEqual(second, [])

    def test_fixed_text_has_no_findings(self):
        text, _ = run_fix("from odoo.exceptions import Warning\nraise Warning('x')\n")
        self.assertEqual(detect(text), [])
        ast.parse(text)


class WarningExceptionCatalogueTests(unittest.TestCase):
    def test_catalogue_entry_binds_at_fix_enabled(self):
        rule = bound()
        self.assertEqual(rule.maturity, "FIX_ENABLED")
        self.assertFalse(rule.review_required)
        self.assertIsNotNone(rule.fixer)
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        self.assertEqual(meta["tests"], {"positive": "TST-006-016", "negative": "TST-006-016",
                                         "idempotence": "TST-006-016"})


if __name__ == "__main__":
    unittest.main()
