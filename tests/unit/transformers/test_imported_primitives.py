"""Feature 012 addendum F1/F3.7: the import-resolved rewrite and decorator removal (transformers/imported.py).

Every case goes through the real engine path (Document, parse, edits, apply_edits). Positive cases, the shadowing,
double-binding, other-module, dynamic-getattr, string/comment and decorator-stack negatives, the conflict behaviour
and idempotence are all checked on fixture text. Stdlib unittest only.
"""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import Edit, apply_edits
from odooflux.parsers.python import document as pydoc
from odooflux.transformers import imported as imp

RULE = "1-1.python_orm.sample-rule"
MODULE = "odoo.tools.helpers"


def _doc(text, path="custom/module.py"):
    return Document.from_text(path, text)


def _run_rewrite(text, old="old_round", new="new_round", module=MODULE):
    document = _doc(text)
    parsed = pydoc.parse_document(document)
    edits = imp.rewrite_imported_symbol_edits(parsed, module, old, new, rule_id=RULE)
    return apply_edits(document, edits, precedence=[RULE]), edits


def _run_remove(text, name="multi", module="odoo.api"):
    document = _doc(text)
    parsed = pydoc.parse_document(document)
    edits = imp.remove_imported_decorator_edits(parsed, module, name, rule_id=RULE)
    return apply_edits(document, edits, precedence=[RULE]), edits


class RewritePositiveTests(unittest.TestCase):
    def test_from_import_import_line_call_and_references_are_rewritten(self):
        text = "from odoo.tools.helpers import old_round\nvalue = old_round(1)\n"
        result, edits = _run_rewrite(text)
        self.assertEqual(result.text, "from odoo.tools.helpers import new_round\nvalue = new_round(1)\n")
        self.assertEqual(result.rejected, ())
        self.assertTrue(result.preserved_ok)
        self.assertEqual({e.rule_id for e in edits}, {RULE})

    def test_strings_and_comments_are_never_touched(self):
        text = ("from odoo.tools.helpers import old_round\n"
                "NOTE = 'old_round(1)'\n"
                "value = old_round(1)  # old_round is legacy\n"
                '"""old_round docstring"""\n')
        result, _ = _run_rewrite(text)
        self.assertIn("NOTE = 'old_round(1)'\n", result.text)
        self.assertIn("# old_round is legacy", result.text)
        self.assertIn('"""old_round docstring"""', result.text)
        self.assertIn("value = new_round(1)  #", result.text)

    def test_module_attribute_form_rewrites_the_attribute_only(self):
        text = "from odoo.tools import helpers\nx = helpers.old_round(2)\n"
        result, _ = _run_rewrite(text)
        self.assertEqual(result.text, "from odoo.tools import helpers\nx = helpers.new_round(2)\n")

    def test_plain_import_with_an_alias_rewrites_the_alias_chain(self):
        text = "import odoo.tools.helpers as h\nx = h.old_round(1)\n"
        result, _ = _run_rewrite(text)
        self.assertEqual(result.text, "import odoo.tools.helpers as h\nx = h.new_round(1)\n")

    def test_plain_dotted_import_rewrites_the_full_chain(self):
        text = "import odoo.tools.helpers\nx = odoo.tools.helpers.old_round(1)\n"
        result, _ = _run_rewrite(text)
        self.assertEqual(result.text, "import odoo.tools.helpers\nx = odoo.tools.helpers.new_round(1)\n")

    def test_aliased_from_import_keeps_the_local_alias(self):
        text = "from odoo.tools.helpers import old_round as legacy\nvalue = legacy(1)\n"
        result, _ = _run_rewrite(text)
        self.assertEqual(result.text, "from odoo.tools.helpers import new_round as legacy\nvalue = legacy(1)\n")

    def test_attribute_store_is_not_rewritten(self):
        text = "from odoo.tools import helpers\nhelpers.old_round = 1\n"
        result, edits = _run_rewrite(text)
        self.assertEqual(edits, [])
        self.assertEqual(result.text, text)

    def test_edits_carry_the_engine_fields_and_the_span_text(self):
        text = "from odoo.tools.helpers import old_round\nvalue = old_round(1)\n"
        _, edits = _run_rewrite(text)
        self.assertTrue(edits and all(isinstance(e, Edit) for e in edits))
        for e in edits:
            with self.subTest(edit=e.id):
                self.assertEqual(text[e.start:e.end], e.before)
                self.assertEqual(e.path, "custom/module.py")
                self.assertEqual(e.validation, ("python-syntax",))


class RewriteNegativeTests(unittest.TestCase):
    def assertUntouched(self, text, **kwargs):
        result, edits = _run_rewrite(text, **kwargs)
        self.assertEqual(edits, [])
        self.assertEqual(result.text, text)
        self.assertEqual(result.applied, ())

    def test_parameter_shadowing_zeroes_the_whole_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\n"
                             "def g(old_round):\n    return old_round(1)\n")

    def test_assignment_shadowing_zeroes_the_whole_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\nold_round = 3\nvalue = old_round\n")

    def test_def_and_class_names_shadow(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\ndef old_round():\n    pass\n")
        self.assertUntouched("from odoo.tools.helpers import old_round\nclass old_round:\n    pass\n")

    def test_loop_with_except_comprehension_walrus_global_and_lambda_targets_shadow(self):
        bindings = {
            "for": "from odoo.tools.helpers import old_round\nfor old_round in range(2):\n    pass\n",
            "with": "from odoo.tools.helpers import old_round\nwith open('x') as old_round:\n    pass\n",
            "except": ("from odoo.tools.helpers import old_round\ntry:\n    pass\nexcept Exception as old_round:\n"
                       "    pass\n"),
            "comprehension": "from odoo.tools.helpers import old_round\nvalues = [old_round for old_round in range(2)]\n",
            "walrus": "from odoo.tools.helpers import old_round\nif (old_round := 1):\n    pass\n",
            "global": ("from odoo.tools.helpers import old_round\ndef f():\n    global old_round\n"
                       "    old_round = 2\n"),
            "lambda": "from odoo.tools.helpers import old_round\nf = lambda old_round: old_round\n",
            "class_attribute": "from odoo.tools.helpers import old_round\nclass A:\n    old_round = 1\n",
        }
        for label, text in bindings.items():
            with self.subTest(binding=label):
                self.assertUntouched(text)

    def test_double_binding_by_two_imports_zeroes_the_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\n"
                             "from other.mod import old_round\nvalue = old_round(1)\n")
        self.assertUntouched("from odoo.tools.helpers import old_round\n"
                             "from odoo.tools.helpers import old_round\nvalue = old_round(1)\n")

    def test_the_same_symbol_from_another_module_is_not_touched(self):
        self.assertUntouched("from other.mod import old_round\nvalue = old_round(1)\n")
        self.assertUntouched("from other import helpers\nvalue = helpers.old_round(1)\n")

    def test_dynamic_getattr_is_not_resolved(self):
        self.assertUntouched("from odoo.tools import helpers\nvalue = getattr(helpers, 'old_round')(1)\n")

    def test_star_import_zeroes_the_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\nfrom elsewhere import *\n"
                             "value = old_round(1)\n")

    def test_string_and_comment_only_mentions_are_left_alone(self):
        self.assertUntouched("import odoo.tools.helpers as h\nNOTE = 'h.old_round(1)'  # h.old_round\n")

    def test_import_nested_in_a_function_does_not_resolve(self):
        self.assertUntouched("def f():\n    from odoo.tools.helpers import old_round\n    return old_round(1)\n")

    def test_new_name_already_bound_zeroes_the_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\ndef new_round():\n    pass\n"
                             "value = old_round(1)\n")

    def test_new_name_referenced_without_a_binding_zeroes_the_file(self):
        self.assertUntouched("from odoo.tools.helpers import old_round\nvalue = old_round(1)\nother = new_round\n")

    def test_unparsable_file_gets_no_edits(self):
        document = _doc("from odoo.tools.helpers import old_round\ndef broken(:\n")
        parsed = pydoc.parse_document(document)
        self.assertEqual(imp.rewrite_imported_symbol_edits(parsed, MODULE, "old_round", "new_round", rule_id=RULE), [])


class RewriteConflictAndIdempotenceTests(unittest.TestCase):
    def test_a_conflicting_rule_on_the_same_span_is_rejected_and_ours_applies(self):
        text = "from odoo.tools.helpers import old_round\nvalue = old_round(1)\n"
        document = _doc(text)
        parsed = pydoc.parse_document(document)
        ours = imp.rewrite_imported_symbol_edits(parsed, MODULE, "old_round", "new_round", rule_id=RULE)
        span = ours[-1]
        other = Edit(id="other.rule:x", rule_id="other.rule", path=document.path, start=span.start, end=span.end,
                     before=span.before, after="other_name", severity="WARNING", step="python-fix",
                     validation=("python-syntax",))
        result = apply_edits(document, ours + [other], precedence=[RULE, "other.rule"])
        self.assertEqual(result.text, "from odoo.tools.helpers import new_round\nvalue = new_round(1)\n")
        self.assertEqual({e.rule_id for e in result.rejected}, {"other.rule"})
        self.assertEqual({e.rule_id for e in result.applied}, {RULE})

    def test_rewrite_is_idempotent(self):
        text = "from odoo.tools.helpers import old_round\nvalue = old_round(1)\nx = helpers_other.old_round\n"
        first, _ = _run_rewrite(text)
        second, second_edits = _run_rewrite(first.text)
        self.assertEqual(second_edits, [])
        self.assertEqual(second.text, first.text)

    def test_attribute_form_is_idempotent(self):
        text = "import odoo.tools.helpers as h\nx = h.old_round(1)\n"
        first, _ = _run_rewrite(text)
        _, second_edits = _run_rewrite(first.text)
        self.assertEqual(second_edits, [])


class DecoratorRemovalTests(unittest.TestCase):
    def test_bare_decorator_is_removed_and_the_stack_stays(self):
        text = ("from odoo.api import multi\n\n\nclass Model:\n    @multi\n    @property\n    def f(self):\n"
                "        return 1\n")
        result, edits = _run_remove(text)
        self.assertEqual(result.text, "from odoo.api import multi\n\n\nclass Model:\n    @property\n"
                                      "    def f(self):\n        return 1\n")
        self.assertEqual(len(edits), 1)

    def test_module_attribute_and_alias_decorators_are_removed(self):
        text = "import odoo.api as api\n\n\nclass Model:\n    @api.multi\n    def f(self):\n        return 1\n"
        result, _ = _run_remove(text)
        self.assertNotIn("@api.multi", result.text)
        self.assertIn("def f(self):", result.text)

    def test_call_decorator_is_never_removed(self):
        text = "from odoo.api import multi\n\n\nclass Model:\n    @multi(1)\n    def f(self):\n        return 1\n"
        result, edits = _run_remove(text)
        self.assertEqual(edits, [])
        self.assertEqual(result.text, text)

    def test_unresolved_and_other_module_decorators_are_left_alone(self):
        for text in ("class Model:\n    @multi\n    def f(self):\n        pass\n",
                     "from other.api import multi\n\n\nclass Model:\n    @multi\n    def f(self):\n        pass\n",
                     "import other.api as api\n\n\nclass Model:\n    @api.multi\n    def f(self):\n        pass\n"):
            with self.subTest(text=text):
                result, edits = _run_remove(text)
                self.assertEqual(edits, [])
                self.assertEqual(result.text, text)

    def test_shadowed_decorator_name_zeroes_the_file(self):
        text = ("from odoo.api import multi\n\n\ndef multi(fn):\n    return fn\n\n\nclass Model:\n    @multi\n"
                "    def f(self):\n        pass\n")
        result, edits = _run_remove(text)
        self.assertEqual(edits, [])
        self.assertEqual(result.text, text)

    def test_string_and_comment_mentions_are_not_removed(self):
        text = ("from odoo.api import multi\n\n\nclass Model:\n    @multi\n    def f(self):\n"
                "        return '@multi'  # @multi\n")
        result, _ = _run_remove(text)
        self.assertIn("return '@multi'  # @multi", result.text)
        self.assertNotIn("    @multi\n", result.text)

    def test_removal_is_idempotent(self):
        text = "from odoo.api import multi\n\n\nclass Model:\n    @multi\n    def f(self):\n        pass\n"
        first, _ = _run_remove(text)
        second, second_edits = _run_remove(first.text)
        self.assertEqual(second_edits, [])
        self.assertEqual(second.text, first.text)


class DetectorSpanTests(unittest.TestCase):
    def test_detector_reports_resolved_sites_and_the_import_line_when_refused(self):
        resolved = pydoc.parse("from odoo.tools.helpers import old_round\nvalue = old_round(1)\n", "a.py")
        self.assertEqual(len(imp.imported_symbol_spans(resolved, MODULE, "old_round")), 2)
        shadowed = pydoc.parse("from odoo.tools.helpers import old_round\ndef g(old_round):\n    pass\n", "a.py")
        spans = imp.imported_symbol_spans(shadowed, MODULE, "old_round")
        self.assertEqual([shadowed.text[s.start:s.end] for s in spans], ["old_round"])

    def test_decorator_detector_reports_bare_decorators_only(self):
        parsed = pydoc.parse("from odoo.api import multi\n\n\nclass M:\n    @multi\n    def f(self):\n        pass\n",
                             "a.py")
        self.assertEqual(len(imp.imported_decorator_spans(parsed, "odoo.api", "multi")), 1)
        called = pydoc.parse("from odoo.api import multi\n\n\nclass M:\n    @multi(1)\n    def f(self):\n        pass\n",
                             "a.py")
        self.assertEqual(imp.imported_decorator_spans(called, "odoo.api", "multi"), [])


class IndexTests(unittest.TestCase):
    def test_only_top_level_absolute_imports_resolve(self):
        index = imp.index_imports(pydoc.parse(
            "import a.b\nfrom c import d as e\nfrom . import f\ndef g():\n    import h\n", "x.py").tree)
        self.assertEqual(index.bindings["a"].target, "a")
        self.assertEqual(index.bindings["e"].target, "c.d")
        self.assertNotIn("f", index.bindings)
        self.assertNotIn("h", index.bindings)
        self.assertEqual(index.counts["h"], 1)


if __name__ == "__main__":
    unittest.main()
