"""Feature 012 addendum F3.7: the bound fixers and detectors of ``rules/python/certified.py``.

The loader path is exercised for real: ``bind_rule`` (from the bindable table), ``KnowledgeRule`` and
``fixing_transform`` (which runs ``apply_edits``). The certification executor's output must equal what the engine
produces for the same rule, so the certified code is the executed code. Synthetic custom-module fixtures only.
"""

import hashlib
import unittest

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import Edit
from odooflux.core.orchestrator.knowledge_rules import KnowledgeRule, fixing_transform
from odooflux.knowledge.candidates.templates import (FIXER_PREFIXES, TemplateError, check_detector_table,
                                                     detector_shape_problem, verify_detector_ref)
from odooflux.parsers.extract_toolkit import ExtractToolkit, detector_table
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.python import certified
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule
from odooflux.transformers import fix_templates as ft
from odooflux.transformers.certify_exec import FixCertifier

CERTIFIED = "odooflux.rules.python.certified"
RULE = "1-1.python_orm.sample-rule"
MODULE = "odoo.tools.helpers"
REWRITE = {"module": MODULE, "old": "old_round", "new": "new_round"}
REMOVE = {"module": "odoo.api", "name": "multi"}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _meta(params, fixer, detector, rule_id=RULE):
    return {"id": rule_id, "maturity": "FIX_ENABLED", "review_required": False, "severity": "WARNING", "step": "1-1",
            "detector_ref": detector, "fixer_ref": fixer, "params": dict(params),
            "tests": {"positive": "p", "negative": "n", "idempotence": "i"}}


def _rewrite_rule(rule_id=RULE):
    return KnowledgeRule(bind_rule(_meta(REWRITE, f"{CERTIFIED}:rewrite_imported_symbol",
                                         f"{CERTIFIED}:flag_imported_symbol", rule_id), BINDABLE_MODULES),
                         _meta(REWRITE, None, None, rule_id))


def _remove_rule(rule_id=RULE):
    meta = _meta(REMOVE, f"{CERTIFIED}:remove_imported_decorator", f"{CERTIFIED}:flag_imported_decorator", rule_id)
    return KnowledgeRule(bind_rule(meta, BINDABLE_MODULES), meta)


def _transform(rules, path, text):
    return fixing_transform(rules, ["1-1"])(path, text)


CUSTOM_IMPORT_CALL = ("from odoo.tools.helpers import old_round\n"
                      "value = old_round(1)\n"
                      "NOTE = 'old_round(1)'  # old_round\n")
CUSTOM_IMPORT_CALL_FIXED = ("from odoo.tools.helpers import new_round\n"
                            "value = new_round(1)\n"
                            "NOTE = 'old_round(1)'  # old_round\n")
CUSTOM_SHADOW = "from odoo.tools.helpers import old_round\ndef g(old_round):\n    return old_round(1)\n"
CUSTOM_DECORATED = ("from odoo.api import multi\n\n\nclass Model:\n    @multi\n    @property\n    def f(self):\n"
                    "        return 1\n")
CUSTOM_DECORATED_FIXED = ("from odoo.api import multi\n\n\nclass Model:\n    @property\n    def f(self):\n"
                          "        return 1\n")


class BindingTests(unittest.TestCase):
    def test_both_fixers_bind_as_fix_enabled_rules_with_their_detectors(self):
        for rule in (_rewrite_rule(), _remove_rule()):
            with self.subTest(rule=rule.key):
                self.assertTrue(rule.fixes)
                self.assertEqual(rule.maturity, "FIX_ENABLED")

    def test_fixers_and_detectors_are_registered_and_shaped_correctly(self):
        self.assertIs(BINDABLE_MODULES[CERTIFIED], certified)
        table = detector_table(BINDABLE_MODULES)
        self.assertIn(f"{CERTIFIED}:flag_imported_symbol", table)
        self.assertIn(f"{CERTIFIED}:flag_imported_decorator", table)
        for name in ("rewrite_imported_symbol", "remove_imported_decorator"):
            self.assertNotIn(f"{CERTIFIED}:{name}", table)
            self.assertTrue(name.startswith(FIXER_PREFIXES))
        for name in ("flag_imported_symbol", "flag_imported_decorator"):
            self.assertIsNone(detector_shape_problem(f"{CERTIFIED}:{name}", getattr(certified, name)))
        ExtractToolkit(detectors=table)  # composition-time validation of the detector table must pass

    def test_a_fixer_is_never_a_detector(self):
        table = detector_table(BINDABLE_MODULES)
        with self.assertRaises(TemplateError):
            verify_detector_ref(f"{CERTIFIED}:rewrite_imported_symbol", table)
        with self.assertRaises(TemplateError):
            check_detector_table({f"{CERTIFIED}:remove_imported_decorator": BINDABLE_MODULES[CERTIFIED]})

    def test_bad_names_are_refused_by_the_fixers(self):
        ctx = RuleContext(rule_id=RULE, severity="WARNING", step="1-1")
        document = Document.from_text("a.py", CUSTOM_IMPORT_CALL)
        for kwargs in ({"module": "bad module", "old": "a", "new": "b"}, {"module": MODULE, "old": "a.b", "new": "c"},
                       {"module": MODULE, "old": "same", "new": "same"}, {"module": MODULE, "old": "class", "new": "b"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    certified.rewrite_imported_symbol(document, ctx, **kwargs)


class EnginePathTests(unittest.TestCase):
    def test_custom_module_rewrite_end_to_end_through_the_loader_path(self):
        rule = _rewrite_rule()
        self.assertEqual(_transform([rule], "custom/a.py", CUSTOM_IMPORT_CALL), CUSTOM_IMPORT_CALL_FIXED)
        # a shadowed file: zero edits, byte-identical
        self.assertEqual(_transform([rule], "custom/b.py", CUSTOM_SHADOW), CUSTOM_SHADOW)
        # the attribute form and an unrelated module's same-named symbol
        text = "from other.mod import old_round\nvalue = old_round(1)\n"
        self.assertEqual(_transform([rule], "custom/c.py", text), text)

    def test_second_run_is_a_no_op(self):
        rule = _rewrite_rule()
        once = _transform([rule], "custom/a.py", CUSTOM_IMPORT_CALL)
        self.assertEqual(_transform([rule], "custom/a.py", once), once)

    def test_decorator_removal_end_to_end_and_idempotent(self):
        rule = _remove_rule()
        once = _transform([rule], "custom/model.py", CUSTOM_DECORATED)
        self.assertEqual(once, CUSTOM_DECORATED_FIXED)
        self.assertEqual(_transform([rule], "custom/model.py", once), once)

    def test_detector_reports_through_the_knowledge_rule(self):
        rule = _rewrite_rule()
        document = Document.from_text("custom/a.py", CUSTOM_IMPORT_CALL)
        findings = rule.detect(document)
        self.assertEqual(len(findings), 2)  # the import alias and the call; the string and comment are not code
        self.assertTrue(all(f.rule_id == RULE for f in findings))

    def test_a_conflicting_custom_rule_on_the_same_span_applies_one_edit(self):
        class Conflicting:
            key = "custom.conflict"
            step = "1-1"
            fixes = True

            def applies_to(self, path):
                return True

            def fix(self, document):
                start = document.text.index("old_round(1)")
                return [Edit(id="custom.conflict:x", rule_id=self.key, path=document.path, start=start,
                             end=start + len("old_round"), before="old_round", after="other_name",
                             severity="WARNING", step="1-1", validation=("python-syntax",))]

        text = "from odoo.tools.helpers import old_round\nvalue = old_round(1)\n"
        out = _transform([_rewrite_rule(), Conflicting()], "custom/a.py", text)
        self.assertEqual(out, "from odoo.tools.helpers import new_round\nvalue = new_round(1)\n")


class CertificationEqualsExecutionTests(unittest.TestCase):
    """The executor's positive, negative and second-pass outputs equal the engine's output for the same rule."""

    def test_exercise_outputs_match_the_loader_run_for_both_templates(self):
        certifier = FixCertifier(modules=BINDABLE_MODULES)
        for template_id, params, rule in (("python.rewrite_imported_symbol", REWRITE, _rewrite_rule()),
                                          ("python.remove_imported_decorator", REMOVE, _remove_rule())):
            with self.subTest(template=template_id):
                spec = ft.template(template_id)
                row = {"id": RULE, "step": "1-1", "params": params, "fixer_ref": spec.fixer_ref,
                       "detector_ref": spec.detector_refs[0], "origin": "BUILTIN"}
                result = certifier.exercise(row, template_id, params)
                self.assertEqual(result["problems"], [])
                before, expected, negative = ft.fixtures(template_id, params)
                self.assertEqual(result["outputs"]["positive_output_digest"], _digest(_transform([rule], "positive.py", before)))
                self.assertEqual(_transform([rule], "positive.py", before), expected)
                self.assertEqual(result["outputs"]["negative_output_digest"], _digest(_transform([rule], "negative.py", negative)))
                self.assertEqual(result["outputs"]["second_pass_digest"], _digest(expected))

    def test_generated_origin_is_refused_without_a_verified_confirmation(self):
        certifier = FixCertifier(modules=BINDABLE_MODULES)
        spec = ft.template("python.rewrite_imported_symbol")
        row = {"id": RULE, "step": "1-1", "params": REWRITE, "fixer_ref": spec.fixer_ref,
               "detector_ref": spec.detector_refs[0], "origin": "GENERATED"}
        self.assertIsNone(certifier.eligible(row, "REPLACEMENT_CONFIRMED")[0])
        self.assertEqual(certifier.eligible(row, "REPLACEMENT_CONFIRMED", confirmation_verified=True),
                         ("python.rewrite_imported_symbol", "eligible"))

    def test_transformer_identity_names_the_bound_fixer(self):
        identity = FixCertifier(modules=BINDABLE_MODULES).transformer_identity("python.remove_imported_decorator")
        self.assertEqual(identity["qualified_name"], f"{CERTIFIED}.remove_imported_decorator")
        self.assertRegex(identity["source_digest"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
