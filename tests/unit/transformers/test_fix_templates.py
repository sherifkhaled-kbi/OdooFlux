"""Feature 012 fix templates (plan section 4, addendum A4): the table is the only source of eligibility.

Each template is checked against the real transformer primitive through the engine path (Document, parse, edits,
apply_edits): the positive fixture produces its expected text exactly, the negative fixture stays byte-identical,
and a second application changes nothing. Eligibility needs a DERIVED change class with its own proof; ledger classes
(candidates included) never certify a fix. Ineligible rows come back with a reason. Stdlib unittest only.
"""

import json
import unittest
from pathlib import Path

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng
from odooflux.parsers.python import document as pydoc
from odooflux.transformers import fix_templates as ft

RULE_ID = "1-1.python_orm.sample-rule"
SCHEMAS = Path(__file__).resolve().parents[3] / "src" / "odooflux" / "knowledge" / "schemas"

# template id -> (params, the derived class that certifies it, or None when no derived class exists). The superseded
# literal templates (addendum F3.7) serve no class any more, so their entry carries None.
SAMPLES = {
    "python.rewrite_imported_symbol": ({"module": "odoo.tools.helpers", "old": "old_round", "new": "new_round"},
                                       "REPLACEMENT_CONFIRMED"),
    "python.remove_imported_decorator": ({"module": "odoo.api", "name": "multi"}, "IDENTITY_DECORATOR_REMOVED"),
    "python.replace_call_name": ({"callee": "api.old_call", "replacement": "api.new_call"}, None),
    "python.replace_attribute": ({"old": "env.old_attr", "new": "env.new_attr"}, None),
    "python.rename_keyword": ({"callee": "fields.Char", "keyword": "oldkw", "new_keyword": "newkw"}, None),
    "python.remove_keyword": ({"callee": "fields.Char", "keyword": "deprecated"}, None),
    "python.remove_decorator": ({"decorator": "api.multi"}, None),
}
SUPERSEDED = ("python.replace_call_name", "python.replace_attribute", "python.remove_decorator")
IMPORTED_REWRITE = "python.rewrite_imported_symbol"
IMPORTED_REMOVE = "python.remove_imported_decorator"
IMPORTED_REMOVE_PARAMS = SAMPLES[IMPORTED_REMOVE][0]
IMPORTED_REWRITE_PARAMS = SAMPLES[IMPORTED_REWRITE][0]
REMOVE_KEYWORD_REASON = ("python.remove_keyword is disabled: no change class proves a removed keyword argument is a "
                         "no-op")
CANDIDATE_CLASSES = ("REPLACEMENT_CANDIDATE", "RENAMED_CANDIDATE")
UNPROVEN_LEDGER_CLASSES = tuple(c for c in ft.LEDGER_CLASSES if c not in CANDIDATE_CLASSES)


def _row(params, origin=None, rule_id=RULE_ID):
    """A rule row as metadata carries it: a template that binds a fixer also binds its detector and fixer refs."""
    bound = next((t for t in ft.FIX_TEMPLATES.values()
                  if t.fixer_ref and isinstance(params, dict) and t.names == frozenset(params)), None)
    row = {"id": rule_id, "step": "1-1", "category": "python_orm", "maturity": "DETECT_ONLY", "risk": "LOW",
           "evidence": ["EV-001"], "detector_ref": bound.detector_refs[0] if bound else None,
           "fixer_ref": bound.fixer_ref if bound else None, "tests": {}, "params": params}
    if origin is not None:
        row["origin"] = origin
    return row


def _apply(template_id, text, params):
    """Run the primitive on ``text`` the way the fix engine does and return the engine result."""
    document = docs.Document.from_bytes("fixture.py", text.encode("utf-8"))
    parsed = pydoc.parse_document(document)
    edits = ft.primitive_edits(template_id, parsed, RULE_ID, params)
    return eng.apply_edits(document, edits, precedence=[RULE_ID]), document


class TableTests(unittest.TestCase):
    def test_version_and_template_set(self):
        self.assertEqual(ft.FIX_TEMPLATES_VERSION, 1)
        self.assertEqual(set(ft.FIX_TEMPLATES), set(SAMPLES))

    def test_each_template_names_an_existing_primitive(self):
        for spec in ft.FIX_TEMPLATES.values():
            with self.subTest(template=spec.template_id):
                self.assertTrue(callable(getattr(spec.primitive_module, spec.primitive)))

    def test_bound_fixers_and_detectors_are_the_certified_module_functions(self):
        for template_id in (IMPORTED_REWRITE, IMPORTED_REMOVE):
            spec = ft.FIX_TEMPLATES[template_id]
            with self.subTest(template=template_id):
                self.assertTrue(spec.fixer_ref.startswith("odooflux.rules.python.certified:"))
                self.assertEqual(len(spec.detector_refs), 1)
                self.assertTrue(spec.detector_refs[0].startswith("odooflux.rules.python.certified:flag_"))
                self.assertTrue(spec.fixer_ref.partition(":")[2].startswith(("rewrite_", "remove_")))
        for template_id in SUPERSEDED:
            with self.subTest(superseded=template_id):
                self.assertIsNone(ft.FIX_TEMPLATES[template_id].fixer_ref)

    def test_derived_classes_are_the_three_proofs_and_are_not_ledger_classes(self):
        self.assertEqual(ft.DERIVED_CLASSES,
                         ("REPLACEMENT_CONFIRMED", "DELEGATING_ALIAS", "IDENTITY_DECORATOR_REMOVED"))
        self.assertEqual(set(ft.DERIVED_CLASSES) & set(ft.LEDGER_CLASSES), set())

    def test_schema_enum_is_the_ledger_and_every_served_class_is_known(self):
        ledger = json.loads((SCHEMAS / "change_ledger.schema.json").read_text(encoding="utf-8"))
        enum = ledger["properties"]["entries"]["items"]["properties"]["class"]["enum"]
        self.assertEqual(tuple(enum), ft.LEDGER_CLASSES)
        for spec in ft.FIX_TEMPLATES.values():
            for cls in spec.change_classes:
                self.assertIn(cls, ft.LEDGER_CLASSES + ft.DERIVED_CLASSES)

    def test_only_derived_classes_are_served(self):
        for spec in ft.FIX_TEMPLATES.values():
            with self.subTest(template=spec.template_id):
                self.assertEqual(set(spec.change_classes) & set(ft.LEDGER_CLASSES), set())
                self.assertTrue(set(spec.change_classes) <= set(ft.DERIVED_CLASSES))

    def test_served_classes_match_the_table(self):
        served = {spec.template_id: spec.change_classes for spec in ft.FIX_TEMPLATES.values()}
        self.assertEqual(served, {
            "python.rewrite_imported_symbol": ("REPLACEMENT_CONFIRMED", "DELEGATING_ALIAS"),
            "python.remove_imported_decorator": ("IDENTITY_DECORATOR_REMOVED",),
            "python.replace_call_name": (),  # superseded by rewrite_imported_symbol (addendum F3.7)
            "python.replace_attribute": (),  # superseded by rewrite_imported_symbol
            "python.rename_keyword": (),
            "python.remove_keyword": (),
            "python.remove_decorator": (),  # superseded by remove_imported_decorator
        })

    def test_parameter_sets_are_unique(self):
        names = [spec.names for spec in ft.FIX_TEMPLATES.values()]
        self.assertEqual(len(names), len(set(names)))

    def test_table_is_read_only(self):
        with self.assertRaises(TypeError):
            ft.FIX_TEMPLATES["python.x"] = None  # type: ignore[index]

    def test_unknown_template_is_refused(self):
        with self.assertRaises(ft.FixTemplateError) as ctx:
            ft.template("python.not_a_template")
        self.assertEqual(ctx.exception.code, "template_unknown")


class TemplateRoundTripTests(unittest.TestCase):
    def test_positive_negative_and_idempotence_per_template(self):
        # every template, disabled ones included, still runs its real primitive on its fixtures
        for template_id, (params, cls) in SAMPLES.items():
            with self.subTest(template=template_id):
                if ft.FIX_TEMPLATES[template_id].change_classes:
                    self.assertEqual(ft.eligible(_row(params), cls), (template_id, "eligible"))
                before, expected, negative = ft.fixtures(template_id, params)

                result, document = _apply(template_id, before, params)
                self.assertEqual(result.rejected, ())
                self.assertTrue(result.preserved_ok)
                self.assertEqual(result.text, expected)
                self.assertEqual(document.with_text(result.text).encode(), expected.encode("utf-8"))

                untouched, neg_document = _apply(template_id, negative, params)
                self.assertEqual(untouched.applied, ())
                self.assertEqual(untouched.text, negative)
                self.assertEqual(neg_document.with_text(untouched.text).encode(), negative.encode("utf-8"))

                second_doc = document.with_text(result.text)
                second = ft.primitive_edits(template_id, pydoc.parse_document(second_doc), RULE_ID, params)
                self.assertEqual(second, [])

    def test_fixtures_are_deterministic(self):
        for template_id, (params, _) in SAMPLES.items():
            with self.subTest(template=template_id):
                self.assertEqual(ft.fixtures(template_id, params), ft.fixtures(template_id, params))

    def test_arguments_are_derived_from_params(self):
        self.assertEqual(ft.primitive_arguments("python.rename_keyword", SAMPLES["python.rename_keyword"][0]),
                         {"call_name": "fields.Char", "keyword": "oldkw", "new_name": "newkw"})
        self.assertEqual(ft.primitive_arguments("python.replace_call_name", SAMPLES["python.replace_call_name"][0]),
                         {"old": "api.old_call", "new": "api.new_call"})

    def test_fixtures_refuse_unvalidated_params(self):
        with self.assertRaises(ft.FixTemplateError) as ctx:
            ft.fixtures("python.remove_decorator", {"decorator": "api.multi\nimport os"})
        self.assertEqual(ctx.exception.code, "param_invalid")


class EligibilityTests(unittest.TestCase):
    def assertRefused(self, row, change_class, *, contains=""):
        template_id, reason = ft.eligible(row, change_class)
        self.assertIsNone(template_id, reason)
        self.assertTrue(reason)
        if contains:
            self.assertIn(contains, reason)

    def test_builtin_manual_and_absent_origin_are_eligible(self):
        params, cls = SAMPLES[IMPORTED_REMOVE]
        for origin in (None, "BUILTIN", "MANUAL"):
            with self.subTest(origin=origin):
                self.assertEqual(ft.eligible(_row(params, origin), cls)[0], IMPORTED_REMOVE)

    def test_ai_generated_and_unknown_origins_are_never_eligible(self):
        params, cls = SAMPLES[IMPORTED_REMOVE]
        for origin in ("AI", "AI_PROPOSED", "GENERATED", "LEGACY", "", 7, ["MANUAL"]):
            with self.subTest(origin=origin):
                self.assertRefused(_row(params, origin), cls, contains="origin")

    def test_generated_origin_is_eligible_only_with_a_verified_confirmation(self):
        for template_id, (params, cls) in SAMPLES.items():
            if not ft.FIX_TEMPLATES[template_id].change_classes:
                continue
            with self.subTest(template=template_id):
                row = _row(params, "GENERATED")
                self.assertEqual(ft.eligible(row, cls, confirmation_verified=True), (template_id, "eligible"))
                for flag in (False, None, "yes", 1):
                    self.assertIsNone(ft.eligible(row, cls, confirmation_verified=flag)[0])
                self.assertIn("origin", ft.eligible(row, cls)[1])
                # the flag never widens the other origins
                self.assertIsNone(ft.eligible(_row(params, "AI"), cls, confirmation_verified=True)[0])

    def test_row_must_carry_the_bound_fixer_and_detector(self):
        params, cls = SAMPLES[IMPORTED_REWRITE]
        row = _row(params)
        for key, value in (("fixer_ref", "odooflux.rules.python.generic:rename_keyword"), ("fixer_ref", None),
                           ("detector_ref", "odooflux.rules.python.certified:flag_imported_decorator"),
                           ("detector_ref", None)):
            with self.subTest(key=key, value=value):
                changed = dict(row, **{key: value})
                template_id, reason = ft.eligible(changed, cls)
                self.assertIsNone(template_id)
                self.assertIn(key, reason)
        bare = dict(row)
        bare.pop("fixer_ref")
        self.assertIsNone(ft.eligible(bare, cls)[0])

    def test_superseded_literal_templates_are_refused_with_their_reason(self):
        for template_id in SUPERSEDED:
            params, _ = SAMPLES[template_id]
            for cls in ("REPLACEMENT_CONFIRMED", "DELEGATING_ALIAS", "IDENTITY_DECORATOR_REMOVED"):
                with self.subTest(template=template_id, change_class=cls):
                    template_id_out, reason = ft.eligible(_row(params), cls)
                    self.assertIsNone(template_id_out)
                    self.assertIn("superseded", reason)

    def test_non_mapping_row_is_refused(self):
        self.assertRefused(["not", "a", "row"], "IDENTITY_DECORATOR_REMOVED")

    def test_missing_or_empty_params_are_refused(self):
        row = _row({})
        row.pop("params")
        self.assertRefused(row, "IDENTITY_DECORATOR_REMOVED", contains="no fixer params")
        self.assertRefused(_row({}), "IDENTITY_DECORATOR_REMOVED", contains="no fixer params")
        self.assertRefused(_row("callee=a.b"), "IDENTITY_DECORATOR_REMOVED", contains="no fixer params")

    def test_missing_and_extra_params_match_no_template(self):
        self.assertRefused(_row({"callee": "fields.Char"}), "IDENTITY_DECORATOR_REMOVED",
                           contains="match no fix template")
        self.assertRefused(_row({"callee": "fields.Char", "keyword": "k", "extra": "x"}),
                           "IDENTITY_DECORATOR_REMOVED", contains="extra")
        self.assertRefused(_row({"module": "odoo.api", "name": "multi", "extra": "x"}), "IDENTITY_DECORATOR_REMOVED")
        self.assertRefused(_row({"module": "odoo.api"}), "IDENTITY_DECORATOR_REMOVED", contains="match no fix")

    def test_injection_attempts_in_names_are_refused(self):
        bad_values = {
            "newline": "api.multi\nimport os",
            "carriage_return": "api.multi\rx",
            "semicolon": "api.multi;import os",
            "single_quote": "api.multi'",
            "double_quote": 'api.multi"',
            "space": "api.multi x",
            "parenthesis": "api.multi()",
            "backslash": "api\\multi",
            "leading_dot": ".api",
            "trailing_dot": "api.",
            "double_dot": "api..multi",
            "digit_start": "1api.multi",
            "unicode_homoglyph": "api.multі",
        }
        for label, value in bad_values.items():
            with self.subTest(value=label):
                self.assertRefused(_row({"module": "odoo.api", "name": value}), "IDENTITY_DECORATOR_REMOVED")
                self.assertRefused(_row({"module": value, "name": "multi"}), "IDENTITY_DECORATOR_REMOVED")

    def test_keyword_identifiers_are_refused(self):
        self.assertRefused(_row({"module": "odoo.api", "name": "class"}), "IDENTITY_DECORATOR_REMOVED",
                           contains="param_reserved")
        self.assertRefused(_row({"module": "odoo.class", "name": "multi"}), "IDENTITY_DECORATOR_REMOVED",
                           contains="param_reserved")
        # remove_keyword is disabled, so eligibility never reaches its parameter checks: validate directly
        with self.assertRaises(ft.FixTemplateError) as ctx:
            ft.validate_params("python.remove_keyword", {"callee": "fields.Char", "keyword": "class"})
        self.assertEqual(ctx.exception.code, "param_reserved")

    def test_identifier_with_dot_is_refused(self):
        with self.assertRaises(ft.FixTemplateError) as ctx:
            ft.validate_params("python.remove_keyword", {"callee": "fields.Char", "keyword": "a.b"})
        self.assertEqual(ctx.exception.code, "param_invalid")

    def test_empty_and_overlong_names_are_refused(self):
        self.assertRefused(_row({"module": "odoo.api", "name": ""}), "IDENTITY_DECORATOR_REMOVED", contains="empty")
        self.assertRefused(_row({"module": "odoo.api", "name": "a" * 121}), "IDENTITY_DECORATOR_REMOVED",
                           contains="longer")

    def test_non_string_params_are_refused(self):
        self.assertRefused(_row({"module": "odoo.api", "name": 5}), "IDENTITY_DECORATOR_REMOVED", contains="string")
        self.assertRefused(_row({"module": "odoo.api", "name": None}), "IDENTITY_DECORATOR_REMOVED", contains="string")

    def test_identical_replacement_is_refused(self):
        self.assertRefused(_row({"module": "odoo.tools.helpers", "old": "same", "new": "same"}),
                           "REPLACEMENT_CONFIRMED", contains="must differ")

    def test_non_identifier_symbol_names_are_refused(self):
        self.assertRefused(_row({"module": "odoo.tools.helpers", "old": "env.attr", "new": "new_round"}),
                           "REPLACEMENT_CONFIRMED", contains="param_invalid")

    def test_unsupported_change_class_is_refused(self):
        params, _ = SAMPLES["python.rename_keyword"]
        self.assertRefused(_row(params), "IDENTITY_DECORATOR_REMOVED", contains="disabled")
        self.assertRefused(_row(params), "UNKNOWN", contains="disabled")
        self.assertRefused(_row(IMPORTED_REMOVE_PARAMS), "REPLACEMENT_CONFIRMED", contains="not served")
        self.assertRefused(_row(IMPORTED_REMOVE_PARAMS), "DELEGATING_ALIAS", contains="not served")
        self.assertRefused(_row(IMPORTED_REWRITE_PARAMS), "IDENTITY_DECORATOR_REMOVED", contains="not served")
        self.assertRefused(_row(IMPORTED_REWRITE_PARAMS), "NOT_A_CLASS", contains="not served")

    def test_missing_change_class_is_refused(self):
        self.assertRefused(_row(IMPORTED_REMOVE_PARAMS), None, contains="not supplied")

    def test_rename_keyword_is_ineligible_with_a_clear_reason(self):
        params, _ = SAMPLES["python.rename_keyword"]
        for origin in (None, "MANUAL"):
            for cls in ("RENAMED_CANDIDATE", None):
                with self.subTest(origin=origin, change_class=cls):
                    template_id, reason = ft.eligible(_row(params, origin), cls)
                    self.assertIsNone(template_id)
                    self.assertIn("python.rename_keyword is disabled", reason)
        self.assertEqual(ft.FIX_TEMPLATES["python.rename_keyword"].change_classes, ())

    def test_remove_keyword_is_disabled_with_the_exact_reason(self):
        params, _ = SAMPLES["python.remove_keyword"]
        for origin in (None, "BUILTIN", "MANUAL"):
            for cls in (None, "IDENTITY_DECORATOR_REMOVED", "REPLACEMENT_CONFIRMED", "REMOVED",
                        "REPLACEMENT_CANDIDATE"):
                with self.subTest(origin=origin, change_class=cls):
                    self.assertEqual(ft.eligible(_row(params, origin), cls), (None, REMOVE_KEYWORD_REASON))
        self.assertEqual(ft.FIX_TEMPLATES["python.remove_keyword"].change_classes, ())

    def test_each_enabled_template_serves_only_its_own_classes(self):
        for template_id, (params, cls) in SAMPLES.items():
            if not ft.FIX_TEMPLATES[template_id].change_classes:
                continue
            with self.subTest(template=template_id):
                self.assertEqual(ft.eligible(_row(params), cls)[0], template_id)
                for other in ft.LEDGER_CLASSES + ft.DERIVED_CLASSES:
                    if other in ft.FIX_TEMPLATES[template_id].change_classes:
                        continue
                    self.assertIsNone(ft.eligible(_row(params), other)[0])

    def test_ledger_classes_never_certify_any_template(self):
        for template_id, (params, _) in SAMPLES.items():
            for cls in ft.LEDGER_CLASSES:
                with self.subTest(template=template_id, change_class=cls):
                    template_id_out, reason = ft.eligible(_row(params), cls)
                    self.assertIsNone(template_id_out)
                    self.assertTrue(reason)
                    if ft.FIX_TEMPLATES[template_id].change_classes:
                        self.assertIn("unproven", reason)
                        self.assertIn("never certifies", reason)

    def test_replacement_candidate_is_refused_as_unconfirmed(self):
        template_id, reason = ft.eligible(_row(IMPORTED_REWRITE_PARAMS), "REPLACEMENT_CANDIDATE")
        self.assertIsNone(template_id)
        self.assertIn("unconfirmed", reason)
        self.assertIn("never certifies", reason)

    def test_renamed_candidate_is_refused_as_unconfirmed(self):
        template_id, reason = ft.eligible(_row(IMPORTED_REWRITE_PARAMS), "RENAMED_CANDIDATE")
        self.assertIsNone(template_id)
        self.assertIn("unconfirmed", reason)
        self.assertIn("never certifies", reason)

    def test_candidate_classes_are_refused_for_every_template(self):
        for template_id, (params, _) in SAMPLES.items():
            for cls in CANDIDATE_CLASSES:
                for origin in (None, "MANUAL"):
                    with self.subTest(template=template_id, change_class=cls, origin=origin):
                        template_id_out, reason = ft.eligible(_row(params, origin), cls)
                        self.assertIsNone(template_id_out)
                        self.assertTrue(reason)
                        if ft.FIX_TEMPLATES[template_id].change_classes:
                            self.assertIn("never certifies", reason)

    def test_removed_and_deprecated_do_not_prove_a_decorator_removal(self):
        for cls in ("REMOVED", "DEPRECATED"):
            with self.subTest(change_class=cls):
                template_id, reason = ft.eligible(_row(IMPORTED_REMOVE_PARAMS), cls)
                self.assertIsNone(template_id)
                self.assertIn("unproven", reason)
                self.assertIn("behaviour-preserving", reason)

    def test_unproven_ledger_classes_are_refused_by_every_enabled_template(self):
        for template_id, (params, _) in SAMPLES.items():
            if not ft.FIX_TEMPLATES[template_id].change_classes:
                continue
            for cls in UNPROVEN_LEDGER_CLASSES:
                with self.subTest(template=template_id, change_class=cls):
                    template_id_out, reason = ft.eligible(_row(params), cls)
                    self.assertIsNone(template_id_out)
                    self.assertIn("unproven", reason)


if __name__ == "__main__":
    unittest.main()
