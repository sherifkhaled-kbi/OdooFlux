"""TST-006-020 (REQ-PY-002): rule 16-17.tests.savepointcase-removed (EV-111, EV-305, EV-306, EV-307).

``SavepointCase`` exists through 16.0 (a deprecated subclass of ``TransactionCase``, EV-306) and is absent in 17.0 (EV-305).
The rename to ``TransactionCase`` is the T013 decision. The fixer renames the import and every reference bound to it.
An alias keeps its local name. An ``except`` clause that names the class is never rewritten, so the file is left
unchanged and reported.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401  (src first on sys.path)

RULE_ID = "16-17.tests.savepointcase-removed"
PATH = "test_m.py"


def bound():
    meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
    return bind_rule(meta, BINDABLE_MODULES)


def run_fix(src):
    rule = bound()
    document = Document.from_text(PATH, src)
    result = apply_edits(document, rule.fix(document), precedence=[RULE_ID])
    second = rule.fix(Document.from_text(PATH, result.text))
    return result.text, second


def detect(src):
    return bound().detect(Document.from_text(PATH, src))


class SavepointPositiveTests(unittest.TestCase):
    def test_import_and_base_class_are_renamed(self):
        src = "from odoo.tests.common import SavepointCase\n\n\nclass T(SavepointCase):\n    pass\n"
        text, _ = run_fix(src)
        self.assertEqual(text, "from odoo.tests.common import TransactionCase\n\n\nclass T(TransactionCase):\n    pass\n")

    def test_module_attribute_form_is_renamed(self):
        src = "from odoo.tests import common\n\n\nclass T(common.SavepointCase):\n    pass\n"
        text, _ = run_fix(src)
        self.assertEqual(text, "from odoo.tests import common\n\n\nclass T(common.TransactionCase):\n    pass\n")

    def test_aliased_import_keeps_local_name(self):
        src = "from odoo.tests.common import SavepointCase as S\n\n\nclass T(S):\n    pass\n"
        text, _ = run_fix(src)
        self.assertEqual(text, "from odoo.tests.common import TransactionCase as S\n\n\nclass T(S):\n    pass\n")

    def test_output_compiles(self):
        text, _ = run_fix("from odoo.tests.common import SavepointCase\nclass T(SavepointCase):\n    pass\n")
        compile(text, PATH, "exec")

    def test_detector_reports_import_and_base_class(self):
        findings = detect("from odoo.tests.common import SavepointCase\nclass T(SavepointCase):\n    pass\n")
        self.assertEqual([f.line for f in findings], [1, 2])


class SavepointNegativeTests(unittest.TestCase):
    def assertUnchanged(self, src):
        text, second = run_fix(src)
        self.assertEqual(text, src)
        self.assertEqual(second, [])

    def test_transaction_case_is_untouched(self):
        self.assertUnchanged("from odoo.tests.common import TransactionCase\nclass T(TransactionCase):\n    pass\n")

    def test_locally_defined_class_of_the_same_name_is_untouched(self):
        self.assertUnchanged("class SavepointCase(object):\n    pass\n\n\nclass T(SavepointCase):\n    pass\n")

    def test_other_module_of_the_same_name_is_untouched(self):
        self.assertUnchanged("from mylib.tests import SavepointCase\nclass T(SavepointCase):\n    pass\n")

    def test_string_literal_is_untouched(self):
        self.assertUnchanged("name = 'SavepointCase'\n")

    def test_except_clause_blocks_the_whole_file(self):
        src = ("from odoo.tests.common import SavepointCase\n\ntry:\n    pass\nexcept SavepointCase:\n    pass\n")
        self.assertUnchanged(src)


class SavepointIdempotenceTests(unittest.TestCase):
    def test_second_application_on_fixed_text_has_no_edits(self):
        _, second = run_fix("from odoo.tests.common import SavepointCase\nclass T(SavepointCase):\n    pass\n")
        self.assertEqual(second, [])


class SavepointCatalogueTests(unittest.TestCase):
    def test_catalogue_entry_binds_at_fix_enabled(self):
        rule = bound()
        self.assertEqual(rule.maturity, "FIX_ENABLED")
        self.assertIsNotNone(rule.fixer)
        self.assertFalse(rule.review_required)
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE_ID)
        self.assertEqual(meta["tests"], {"positive": "TST-006-020", "negative": "TST-006-020",
                                         "idempotence": "TST-006-020"})


if __name__ == "__main__":
    unittest.main()
