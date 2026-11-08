"""TST-003-018 (REQ-VAL-001): Python, XML, manifest validators PASS on valid and FAIL with location."""

import unittest

from odooflux.builtins import build_context

from ._setup import SRC  # noqa: F401


class SyntaxValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validators = {v.key: v for v in build_context().registries.validators.all()}

    def test_python(self):
        v = self.validators["syntax.python"]
        self.assertEqual(v.validate("models/a.py", "x = 1\n").outcome, "PASS")
        bad = v.validate("models/a.py", "def f(:\n")
        self.assertEqual(bad.outcome, "FAIL")
        self.assertIn("line 1", bad.reason)

    def test_xml(self):
        v = self.validators["syntax.xml"]
        self.assertEqual(v.validate("views/a.xml", "<odoo/>").outcome, "PASS")
        self.assertEqual(v.validate("views/a.xml", "<odoo><x></odoo>").outcome, "FAIL")

    def test_manifest(self):
        v = self.validators["syntax.manifest"]
        self.assertEqual(v.validate("__manifest__.py", "{'name': 'x'}").outcome, "PASS")
        self.assertEqual(v.validate("__manifest__.py", "['not', 'a', 'dict']").outcome, "FAIL")
        self.assertEqual(v.validate("__manifest__.py", "{'x': 1 +}").outcome, "FAIL")

    def test_all_are_registered_in_the_validators_registry(self):
        self.assertEqual(set(self.validators), {"syntax.python", "syntax.xml", "syntax.manifest", "static.rescan"})


if __name__ == "__main__":
    unittest.main()
