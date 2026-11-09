"""Feature 012 hardening (review item 4): import-resolved rewrites refuse the WHOLE file when the target can be observed
or changed through another route (monkeypatching, reflection, string names, re-export via ``__all__``).

Each case is a reproducer from the adversarial review (t5). A refused file gets zero edits, so the planned output equals
the input text byte for byte. Detection still reports something for a refused file (the hazard spans).
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.parsers.python import document as pydoc
from odooflux.transformers import imported as imp

MODULE = "odoo.x.y"


def _parsed(src: str):
    return pydoc.parse_document(Document.from_bytes("c.py", src.encode()))


def rewrite(src: str, module=MODULE, old="old", new="new") -> str:
    parsed = _parsed(src)
    sites, refusal = imp.plan_rewrite_imported_symbol(parsed, module, old, new)
    out = parsed.text
    for span, after, _ in sorted(sites, key=lambda site: -site[0].start):
        out = out[:span.start] + after + out[span.end:]
    return out if not refusal else src


def remove(src: str, module=MODULE, name="old") -> str:
    parsed = _parsed(src)
    sites, refusal = imp.plan_remove_imported_decorator(parsed, module, name)
    out = parsed.text
    for span, after, _ in sorted(sites, key=lambda site: -site[0].start):
        out = out[:span.start] + after + out[span.end:]
    return out if not refusal else src


class RefusedWholeFileTests(unittest.TestCase):
    def assertRefused(self, src, module=MODULE):
        self.assertEqual(rewrite(src, module=module), src)
        self.assertNotEqual(imp.plan_rewrite_imported_symbol(_parsed(src), module, "old", "new")[1], "")

    def test_attribute_store_on_the_module_refuses_the_file(self):
        # t5 monkeypatch: `M.old = my_patch` must not leave `M.old(1)` calling the new name
        self.assertRefused("import odoo.x.y as M\nM.old = my_patch\nr = M.old(1)\n")

    def test_attribute_store_through_from_import_of_the_package_refuses(self):
        self.assertRefused("from odoo.x import y\ny.old = patch\nr = y.old(1)\n")

    def test_augmented_assignment_on_the_attribute_refuses(self):
        self.assertRefused("import odoo.x.y as M\nM.old += 1\n")

    def test_string_constant_equal_to_the_old_name_refuses(self):
        # getattr / setattr / mock.patch.object name the symbol by string
        self.assertRefused("import odoo.x.y as M\nf = getattr(M, 'old')\nM.old(1)\n")
        self.assertRefused("from unittest import mock\nimport odoo.x.y as M\n"
                           "with mock.patch.object(M, 'old'):\n    M.old(1)\n")

    def test_string_constant_equal_to_the_dotted_path_refuses(self):
        self.assertRefused("from odoo.x.y import old\nd = {'key': 'odoo.x.y.old'}\nold(1)\n")

    def test_del_of_the_attribute_refuses(self):
        self.assertRefused("import odoo.x.y as M\ndel M.old\n")

    def test_reflection_with_the_module_object_refuses(self):
        # hasattr(M, ...) / setattr(M, ...) with a non-string name still targets the module object
        self.assertRefused("import odoo.x.y as M\nif hasattr(M, name):\n    M.old(1)\n")
        self.assertRefused("import odoo.x.y as M\nsetattr(M, name, patch)\nM.old(1)\n")

    def test_name_reexported_through_all_refuses(self):
        # t5 reexport_all: the import line would change but `__all__` keeps the old name
        self.assertRefused("from odoo.x.y import old\n__all__ = ['old']\n")

    def test_plain_import_and_call_still_rewrites(self):
        # no behaviour change for the certified shape itself (the pinned fixture in test_imported_primitives)
        src = "from odoo.x.y import old\nvalue = old(1)\n"
        self.assertEqual(rewrite(src), "from odoo.x.y import new\nvalue = new(1)\n")

    def test_plain_attribute_call_still_rewrites(self):
        src = "import odoo.x.y as M\nvalue = M.old(1)\n"
        self.assertEqual(rewrite(src), "import odoo.x.y as M\nvalue = M.new(1)\n")

    def test_decorator_removal_refuses_when_the_module_is_patched(self):
        src = "import odoo.x.y as M\nM.old = patch\nclass K:\n    @M.old\n    def f(self):\n        pass\n"
        self.assertEqual(remove(src), src)

    def test_refused_file_detection_still_reports_the_hazard(self):
        src = "import odoo.x.y as M\nM.old = my_patch\n"
        spans = imp.imported_symbol_spans(_parsed(src), MODULE, "old")
        self.assertTrue(spans, "a refused file must still be reported for a human")


if __name__ == "__main__":
    unittest.main()
