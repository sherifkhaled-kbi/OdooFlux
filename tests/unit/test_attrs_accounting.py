"""AF-8: every ``attrs`` occurrence lands in exactly one bucket (converted / refused / not visited / residual).

Synthetic fixtures only: no corpus, no network. The residual is exercised by replacing the fixer with one that drops a
candidate, so the identity check is shown to fail when the fixer leaves a site unvisited.
"""

import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.engine.documents import Document
from odooflux.rules.experimental import attrs_accounting as acc
from odooflux.rules.experimental import xml_modifiers as xm

REPO = pathlib.Path(__file__).resolve().parents[2]
PLAIN_ATTRS = "{'invisible': [('state', '=', 'draft')]}"


def view(inner: str, inherit: bool = False) -> str:
    inherit_field = '<field name="inherit_id" ref="base.view_x"/>' if inherit else ""
    return (f'<odoo><record id="v" model="ir.ui.view"><field name="name">v</field>{inherit_field}'
            f'<field name="model">kbi.exp</field><field name="arch" type="xml">{inner}</field></record></odoo>')


def form(inner: str) -> str:
    return view(f"<form>{inner}</form>")


def account(text: str, path: str = "v.xml") -> acc.FileAccounting:
    return acc.account_document(Document.from_text(path, text))


def assert_identity(test: unittest.TestCase, result: acc.FileAccounting) -> None:
    test.assertEqual(result.bucket_sum, result.occurrences)
    test.assertEqual(result.unreconciled, 0)


class BucketTests(unittest.TestCase):
    def test_plain_form_element_is_converted(self):
        result = account(form(f'<field name="a" attrs="{PLAIN_ATTRS}"/>'))
        self.assertEqual((result.occurrences, result.converted), (1, 1))
        self.assertEqual(sum(result.refused.values()), 0)
        assert_identity(self, result)

    def test_element_outside_form_is_refused_with_reason(self):
        result = account(view(f'<div><field name="a" attrs="{PLAIN_ATTRS}"/></div>'))
        self.assertEqual(result.converted, 0)
        self.assertEqual(result.refused, {"not-in-form": 1})
        self.assertEqual(result.occurrences, 1)
        assert_identity(self, result)

    def test_falsy_literal_refusal_and_reason_counts(self):
        falsy = "{'invisible': [('state', '=', False)]}"
        text = form(f'<field name="a" attrs="{falsy}"/><field name="b" attrs="{falsy}"/>'
                    f'<field name="c" attrs="{PLAIN_ATTRS}"/>')
        result = account(text)
        self.assertEqual(result.converted, 1)
        self.assertEqual(result.refused, {"falsy-literal": 2})
        self.assertEqual(result.occurrences, 3)
        assert_identity(self, result)

    def test_comment_occurrence_is_not_visited_not_refused(self):
        text = form(f'<!-- <field name="old" attrs="{PLAIN_ATTRS}"/> -->')
        result = account(text)
        self.assertEqual(result.occurrences, 1)
        self.assertEqual((result.converted, sum(result.refused.values())), (0, 0))
        self.assertEqual(result.not_visited, {"in-comment": 1})
        assert_identity(self, result)

    def test_cdata_occurrence_is_not_visited(self):
        text = form(f'<field name="x"/><![CDATA[ attrs="{PLAIN_ATTRS}" ]]>')
        result = account(text)
        self.assertEqual(result.not_visited, {"in-cdata": 1})
        assert_identity(self, result)

    def test_text_and_attribute_value_occurrences_are_not_visited(self):
        text = form(f'<field name="a" string=" attrs=x"/> plain text attrs={PLAIN_ATTRS}')
        result = account(text)
        self.assertEqual(result.occurrences, 2)
        self.assertEqual(result.not_visited, {"in-attribute-value": 1, "in-text": 1})
        assert_identity(self, result)

    def test_unparseable_file_counts_every_raw_match_as_unparsed(self):
        text = f'<odoo><record><field name="arch"> attrs="{PLAIN_ATTRS}"</field></record><unclosed attrs="x">'
        result = account(text)
        self.assertIsNotNone(result.parse_error)
        self.assertEqual(result.occurrences, 2)
        self.assertEqual(result.not_visited, {"unparsed-file": 2})
        self.assertEqual(result.structural, 0)
        assert_identity(self, result)


class InheritedSiteTests(unittest.TestCase):
    def test_inherited_attribute_element_on_form_is_converted_and_counted_as_structural(self):
        text = view(f'<xpath expr="//form" position="attributes"><attribute name="attrs">'
                    f"{PLAIN_ATTRS}</attribute></xpath>", inherit=True)
        result = account(text)
        self.assertEqual((result.occurrences, result.converted, result.structural), (1, 1, 1))
        self.assertEqual(result.converted_structural, 1)
        self.assertEqual(sum(result.refused.values()), 0)
        assert_identity(self, result)

    def test_inherited_attribute_element_with_non_form_target_is_refused_as_structural(self):
        text = view(f'<xpath expr="//field[@name=\'a\']" position="attributes"><attribute name="attrs">'
                    f"{PLAIN_ATTRS}</attribute></xpath>", inherit=True)
        result = account(text)
        self.assertEqual(result.refused, {"inherited-target-not-form": 1})
        self.assertEqual((result.structural, result.converted_structural), (1, 0))
        assert_identity(self, result)

    def test_element_with_attrs_attribute_and_name_attrs_is_one_occurrence(self):
        # Carries both an attrs attribute and name="attrs": the fixer treats it as one candidate (start-tag site).
        text = view(f'<xpath expr="//form" position="attributes"><attribute name="attrs" '
                    f'attrs="{PLAIN_ATTRS}"/></xpath>', inherit=True)
        result = account(text)
        self.assertEqual(result.occurrences, 1)
        self.assertEqual(result.structural, 0)
        assert_identity(self, result)


class ConsistencyTests(unittest.TestCase):
    def test_regex_and_parsed_sites_do_not_double_count(self):
        text = form(f'<field name="a" attrs="{PLAIN_ATTRS}"/><field name="b" attrs="{PLAIN_ATTRS}"/>'
                    f'<!-- attrs="{PLAIN_ATTRS}" -->')
        result = account(text)
        self.assertEqual(result.occurrences, 3)
        self.assertEqual(result.converted, 2)
        self.assertEqual(result.not_visited, {"in-comment": 1})
        assert_identity(self, result)

    def test_residual_is_reported_when_fixer_drops_a_candidate(self):
        text = form(f'<field name="a" attrs="{PLAIN_ATTRS}"/><field name="b" attrs="{PLAIN_ATTRS}"/>')
        real_plan = xm.plan_attrs

        def dropping(document, ctx=None):
            plan = real_plan(document, ctx)
            return xm.Plan(edits=plan.edits, converted=plan.converted[:1], refused=plan.refused)

        with mock.patch.object(xm, "plan_attrs", dropping):
            result = account(text)
        self.assertEqual(result.unreconciled, 1)
        self.assertEqual(result.bucket_sum, result.occurrences)  # the residual is what keeps the sum closed
        self.assertFalse(acc.check(acc.Accounting(totals=result)))

    def test_fixer_exception_is_reported_as_not_visited_not_hidden(self):
        text = form(f'<field name="a" attrs="{PLAIN_ATTRS}"/>')
        with mock.patch.object(xm, "plan_attrs", side_effect=RuntimeError("boom")):
            result = account(text)
        self.assertEqual(result.not_visited, {"fixer-error:RuntimeError": 1})
        self.assertEqual(result.converted, 0)
        assert_identity(self, result)


class TreeTests(unittest.TestCase):
    def _tree(self, root: pathlib.Path) -> None:
        (root / "kbi_a" / "views").mkdir(parents=True)
        (root / "kbi_a" / "views" / "v.xml").write_text(
            form(f'<field name="a" attrs="{PLAIN_ATTRS}"/><!-- attrs="{PLAIN_ATTRS}" -->'), encoding="utf-8")
        (root / "kbi_b").mkdir()
        (root / "kbi_b" / "broken.xml").write_text(f'<odoo attrs="{PLAIN_ATTRS}"><unclosed>', encoding="utf-8")
        (root / "kbi_b" / "tests.py").write_text(f'x = """ attrs={PLAIN_ATTRS}"""\n', encoding="utf-8")

    def test_tree_totals_identity_and_informational_non_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._tree(root)
            accounting = acc.account_tree(root)
        totals = accounting.totals
        self.assertEqual(accounting.xml_files, 2)
        self.assertEqual(totals.occurrences, 3)
        self.assertEqual((totals.converted, totals.refused, totals.not_visited),
                         (1, {}, {"in-comment": 1, "unparsed-file": 1}))
        self.assertTrue(acc.check(accounting))
        self.assertEqual(dict(accounting.non_xml_matches), {".py": 1})  # outside the universe, not counted above
        self.assertEqual([path for path, _ in accounting.parse_errors], ["kbi_b/broken.xml"])
        report = acc.to_dict(accounting)
        self.assertTrue(report["identity_holds"])
        self.assertEqual(report["occurrences"], report["converted"] + report["refused_total"]
                         + report["not_visited_total"] + report["unreconciled"])

    def test_cli_exit_status_follows_identity(self):
        spec = importlib.util.spec_from_file_location("attrs_corpus_accounting", REPO / "tools" / "attrs_corpus_accounting.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._tree(root)
            out = root.parent / (root.name + ".json")
            self.assertEqual(module.main([str(root), "--json", str(out)]), 0)
            self.assertTrue(out.exists())
            out.unlink()
            real_plan = xm.plan_attrs

            def dropping(document, ctx=None):
                plan = real_plan(document, ctx)
                return xm.Plan(edits=plan.edits, converted=(), refused=plan.refused)

            with mock.patch.object(xm, "plan_attrs", dropping):
                self.assertEqual(module.main([str(root)]), 1)


if __name__ == "__main__":
    unittest.main()
