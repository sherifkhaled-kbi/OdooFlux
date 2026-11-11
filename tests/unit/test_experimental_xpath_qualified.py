"""Qualified ``inherit_id`` refs resolved through module context (VR-1).

An inherited view's ``<xpath expr="//field[@name='x']">`` is converted only when its target is proven: the
``inherit_id`` ref names one ``ir.ui.view`` record (or ``<template>`` id) in the module it names (a bare ref names
the document's own module), that record is a base view whose arch is one ``<form>``, and the field is found once
in it, not nested.
The module context is the module directories beside the document (its addons root), read through a ``ModuleViews``
object that one run shares. Without that context a qualified ref is refused exactly as before.

Real files in temporary module trees; nothing outside them is written, and no network or CLI is used.
"""

import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tests.unit import _setup  # noqa: F401  (puts src/ on sys.path)

from odooflux.core.engine.documents import Document
from odooflux.core.engine.edits import apply_edits
from odooflux.rules.experimental import attrs_accounting as acc
from odooflux.rules.experimental import xml_modifiers as xm
from odooflux.rules.shared.emit import RuleContext

ATTRS = "16-17.xml.attrs-removed"
TARGET = "inherited-target-not-form"
EXPR = "//field[@name='name']"
HIDE = "{'invisible': [('state', '=', 'done')]}"
HIDDEN = "invisible=\"state == 'done'\""

FORM = ('<record id="order_form" model="ir.ui.view"><field name="name">order form</field>'
        '<field name="model">kbi.order</field><field name="arch" type="xml">'
        '<form><sheet><group><field name="name"/></group></sheet></form></field></record>')


def form_record(view_id: str, arch: str = None, extra: str = "") -> str:
    arch = arch or '<form><sheet><group><field name="name"/></group></sheet></form>'
    return (f'<record id="{view_id}" model="ir.ui.view"><field name="name">{view_id}</field>'
            f'<field name="model">kbi.order</field>{extra}<field name="arch" type="xml">{arch}</field></record>')


def inheriting(ref: str, view_id: str = "order_form_ext", expr: str = EXPR) -> str:
    """An extension of ``ref`` whose xpath adds a field carrying ``attrs`` (converted when the target is proven)."""
    return (f'<record id="{view_id}" model="ir.ui.view"><field name="name">{view_id}</field>'
            f'<field name="model">kbi.order</field><field name="inherit_id" ref="{ref}"/>'
            f'<field name="arch" type="xml"><xpath expr="{expr}" position="after">'
            f'<field name="note" attrs="{HIDE}"/></xpath></field></record>')


def odoo(*records: str) -> str:
    return "<odoo>" + "".join(records) + "</odoo>"


def hidden(text: str) -> str:
    """The expected output: the ``attrs`` attribute of the converted field replaced by its ``invisible`` form."""
    return text.replace(f'attrs="{HIDE}"', HIDDEN)


def ctx():
    return RuleContext(rule_id=ATTRS, severity="CRITICAL", step="16-17")


class ModuleTreeCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)

    def module(self, name: str, files: dict) -> pathlib.Path:
        base = self.root / name
        base.mkdir()
        (base / "__manifest__.py").write_text("{'name': 'x', 'version': '16.0.1.0.0'}\n", encoding="utf-8")
        for rel, text in files.items():
            path = base / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return base

    def plan(self, path, views):
        return xm.plan_attrs(Document.from_bytes(str(path), path.read_bytes()), ctx(), views=views)

    def convert(self, path, views):
        """(converted text, plan) for the file at ``path``; the text is unchanged when nothing converted."""
        document = Document.from_bytes(str(path), path.read_bytes())
        result = xm.plan_attrs(document, ctx(), views=views)
        text = apply_edits(document, result.edits, precedence=[ATTRS]).text if result.edits else document.text
        return text, result

    def refused_reasons(self, result):
        return [r.reason for r in result.refused]


class CrossFileTests(ModuleTreeCase):
    def test_qualified_ref_to_form_in_other_file_converts_byte_exact(self):
        base = self.module("kbi_orders", {"views/form.xml": odoo(FORM),
                                          "views/ext.xml": odoo(inheriting("kbi_orders.order_form"))})
        source = (base / "views/ext.xml").read_text(encoding="utf-8")
        text, result = self.convert(base / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(len(result.converted), 1)
        self.assertEqual(result.refused, ())
        self.assertEqual(text, hidden(source))
        ET.fromstring(text)  # well-formed

    def test_bare_ref_to_form_in_other_file_of_same_module_converts(self):
        base = self.module("kbi_orders", {"views/form.xml": odoo(FORM),
                                          "views/ext.xml": odoo(inheriting("order_form"))})
        source = (base / "views/ext.xml").read_text(encoding="utf-8")
        text, result = self.convert(base / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(len(result.converted), 1)
        self.assertEqual(text, hidden(source))

    def test_own_module_qualified_ref_in_same_document_converts(self):
        base = self.module("kbi_orders", {"views/all.xml": odoo(FORM, inheriting("kbi_orders.order_form"))})
        source = (base / "views/all.xml").read_text(encoding="utf-8")
        text, result = self.convert(base / "views/all.xml", xm.ModuleViews())
        self.assertEqual(len(result.converted), 1)
        self.assertEqual(text, hidden(source))


class CrossModuleTests(ModuleTreeCase):
    def test_sibling_module_form_converts_byte_exact(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        source = (ext / "views/ext.xml").read_text(encoding="utf-8")
        text, result = self.convert(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(len(result.converted), 1)
        self.assertEqual(text, hidden(source))
        ET.fromstring(text)

    def test_one_views_object_serves_every_document_of_a_run(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders", {"views/a.xml": odoo(inheriting("kbi_base.order_form", "a_ext")),
                                         "views/b.xml": odoo(inheriting("kbi_base.order_form", "b_ext"))})
        views = xm.ModuleViews()
        converted = [self.plan(ext / "views" / name, views).converted for name in ("a.xml", "b.xml")]
        self.assertEqual([len(c) for c in converted], [1, 1])


class RefusalTests(ModuleTreeCase):
    def assert_refused(self, files, path, reason=TARGET, views=None):
        base = self.module("kbi_orders", files)
        result = self.plan(base / path, views or xm.ModuleViews())
        self.assertEqual(result.converted, ())
        self.assertEqual(self.refused_reasons(result), [reason])
        return base

    def test_list_target_is_refused(self):
        list_view = ('<record id="order_list" model="ir.ui.view"><field name="name">l</field>'
                     '<field name="model">kbi.order</field><field name="arch" type="xml">'
                     '<list><field name="name"/></list></field></record>')
        self.assert_refused({"views/list.xml": odoo(list_view),
                             "views/ext.xml": odoo(inheriting("kbi_orders.order_list"))}, "views/ext.xml")

    def test_duplicate_xmlid_in_two_files_is_refused(self):
        self.assert_refused({"views/a.xml": odoo(FORM), "views/b.xml": odoo(FORM),
                             "views/ext.xml": odoo(inheriting("kbi_orders.order_form"))}, "views/ext.xml")

    def test_template_with_same_id_is_ambiguous_and_refused(self):
        template = '<template id="order_form"><div/></template>'
        self.assert_refused({"views/form.xml": odoo(FORM), "views/t.xml": odoo(template),
                             "views/ext.xml": odoo(inheriting("kbi_orders.order_form"))}, "views/ext.xml")

    def test_missing_target_is_refused(self):
        self.assert_refused({"views/form.xml": odoo(FORM),
                             "views/ext.xml": odoo(inheriting("kbi_orders.no_such_view"))}, "views/ext.xml")

    def test_cyclic_inherit_chain_is_refused(self):
        a = form_record("view_a", extra='<field name="inherit_id" ref="kbi_orders.view_b"/>')
        b = form_record("view_b", extra='<field name="inherit_id" ref="kbi_orders.view_a"/>')
        self.assert_refused({"views/cycle.xml": odoo(a, b),
                             "views/ext.xml": odoo(inheriting("kbi_orders.view_a"))}, "views/ext.xml")

    def test_target_that_itself_inherits_is_refused(self):
        base_view = form_record("view_base")
        child = form_record("view_child", extra='<field name="inherit_id" ref="kbi_orders.view_base"/>')
        self.assert_refused({"views/a.xml": odoo(base_view, child),
                             "views/ext.xml": odoo(inheriting("kbi_orders.view_child"))}, "views/ext.xml")

    def test_core_module_ref_is_refused_without_a_sibling_module(self):
        self.assert_refused({"views/ext.xml": odoo(inheriting("base.view_partner_form"))}, "views/ext.xml")

    def test_core_module_ref_is_not_resolved_to_a_same_named_local_form(self):
        text = odoo(FORM, inheriting("base.order_form"))
        base = self.module("kbi_orders", {"views/all.xml": text})
        result = self.plan(base / "views/all.xml", xm.ModuleViews())
        self.assertEqual(result.converted, ())
        self.assertEqual(self.refused_reasons(result), [TARGET])

    def test_ref_naming_a_path_outside_the_addons_root_is_refused(self):
        self.assert_refused({"views/ext.xml": odoo(inheriting("../kbi_orders.order_form"))}, "views/ext.xml")

    def test_unreadable_sibling_module_is_refused(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM), "views/broken.xml": "<odoo><record"})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        result = self.plan(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(result.converted, ())
        self.assertEqual(self.refused_reasons(result), [TARGET])

    def test_target_field_missing_from_form_keeps_its_specific_reason(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders",
                          {"views/ext.xml": odoo(inheriting("kbi_base.order_form", expr="//field[@name='zz']"))})
        result = self.plan(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(self.refused_reasons(result), ["inherited-target-field-not-found"])

    def test_target_field_nested_in_a_tree_keeps_its_specific_reason(self):
        arch = ('<form><sheet><field name="lines"><tree><field name="name"/></tree></field></sheet></form>')
        self.module("kbi_base", {"views/form.xml": odoo(form_record("order_form", arch))})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        result = self.plan(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(self.refused_reasons(result), ["inherited-target-field-nested"])


class ContextAbsentTests(ModuleTreeCase):
    def test_single_document_qualified_ref_is_refused_as_before(self):
        text = odoo(FORM, inheriting("kbi_orders.order_form"))
        result = xm.plan_attrs(Document.from_text("v.xml", text), ctx())
        self.assertEqual(result.converted, ())
        self.assertEqual([r.reason for r in result.refused], [TARGET])

    def test_document_outside_any_module_is_refused_even_with_views(self):
        loose = self.root / "loose"
        loose.mkdir()
        path = loose / "ext.xml"
        path.write_text(odoo(inheriting("kbi_orders.order_form")), encoding="utf-8")
        result = self.plan(path, xm.ModuleViews())
        self.assertEqual(self.refused_reasons(result), [TARGET])

    def test_same_document_bare_ref_converts_with_and_without_context(self):
        # PA-4 behaviour: a bare ref to one base form in the same document is proven without any module context
        text = odoo(FORM, inheriting("order_form"))
        self.assertEqual(len(xm.plan_attrs(Document.from_text("v.xml", text), ctx()).converted), 1)
        base = self.module("kbi_orders", {"views/all.xml": text})
        self.assertEqual(len(self.plan(base / "views/all.xml", xm.ModuleViews()).converted), 1)


class IdempotenceTests(ModuleTreeCase):
    def test_second_pass_finds_nothing(self):
        base = self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        path = ext / "views/ext.xml"
        text, first = self.convert(path, xm.ModuleViews())
        self.assertEqual(len(first.converted), 1)
        path.write_text(text, encoding="utf-8")
        text2, second = self.convert(path, xm.ModuleViews())
        self.assertEqual(text2, text)
        self.assertEqual(second.edits, ())
        self.assertEqual(second.converted, ())
        self.assertEqual(second.refused, ())
        self.assertTrue(base.exists())


class AccountingTests(ModuleTreeCase):
    def test_accounting_tree_with_module_views_counts_the_cross_file_conversion(self):
        self.module("kbi_orders", {"views/form.xml": odoo(FORM),
                                   "views/ext.xml": odoo(inheriting("kbi_orders.order_form"))})
        without = acc.account_tree(self.root)
        with_views = acc.account_tree(self.root, xm.ModuleViews())
        self.assertEqual(without.totals.converted, 0)
        self.assertEqual(with_views.totals.converted, 1)
        self.assertEqual(with_views.totals.unreconciled, 0)
        self.assertTrue(acc.check(with_views))



class BindingContextTests(ModuleTreeCase):
    """The orchestrator hands the run's module context to the bound experimental fixer (fix and explain alike)."""

    def bound_rule(self, views_factory):
        from odooflux.core.orchestrator import knowledge_rules as kr
        from odooflux.knowledge.loader import load_knowledge
        from odooflux.rules.bindable import BINDABLE_MODULES
        from odooflux.rules.experimental import registry

        row = next(r for r in load_knowledge().rules if r["id"] == ATTRS)
        experimental = kr.ExperimentalFixers(entries=registry.ENTRIES, modules=registry.MODULES, views=views_factory)
        rules, _gaps = kr.bind_knowledge_rules([row], BINDABLE_MODULES, {}, ("16-17",), experimental=experimental)
        return next(r for r in rules if r.key == ATTRS)

    def test_bound_fixer_converts_a_cross_module_ref_with_the_run_context(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        path = ext / "views/ext.xml"
        source = path.read_text(encoding="utf-8")
        rule = self.bound_rule(xm.ModuleViews)
        document = Document.from_bytes(str(path), path.read_bytes())
        self.assertEqual(len(rule.explain(document).converted), 1)
        edits = rule.fix(document)
        self.assertEqual(apply_edits(document, edits, precedence=[ATTRS]).text, hidden(source))

    def test_bound_fixer_without_run_context_refuses_the_same_ref(self):
        self.module("kbi_base", {"views/form.xml": odoo(FORM)})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form"))})
        path = ext / "views/ext.xml"
        rule = self.bound_rule(None)
        document = Document.from_bytes(str(path), path.read_bytes())
        self.assertEqual(rule.explain(document).converted, ())
        self.assertEqual(rule.fix(document), [])


class FormFieldTargetTests(ModuleTreeCase):
    """``/form/field[@name='x']`` is checked in a readable target form and accepted when the target is a core ref."""

    def test_core_ref_form_field_shape_converts_as_before(self):
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("base.view_partner_form",
                                                                          expr="/form/field[@name='name']"))})
        text, result = self.convert(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(result.refused, ())
        self.assertEqual(len(result.converted), 1)
        self.assertEqual(text, hidden((ext / "views/ext.xml").read_text(encoding="utf-8")))

    def test_sibling_form_with_duplicate_field_is_refused_as_ambiguous(self):
        dup = ('<form><field name="name"/><group><field name="name"/></group></form>')
        self.module("kbi_base", {"views/form.xml": odoo(form_record("order_form", dup))})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_form",
                                                                          expr="//form/field[@name='name']"))})
        result = self.plan(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(result.converted, ())
        self.assertEqual(self.refused_reasons(result), ["inherited-target-field-ambiguous"])

    def test_sibling_list_target_for_form_field_shape_is_refused_as_not_form(self):
        list_view = ('<record id="order_list" model="ir.ui.view"><field name="name">l</field>'
                     '<field name="model">kbi.order</field><field name="arch" type="xml">'
                     '<list><field name="name"/></list></field></record>')
        self.module("kbi_base", {"views/list.xml": odoo(list_view)})
        ext = self.module("kbi_orders", {"views/ext.xml": odoo(inheriting("kbi_base.order_list",
                                                                          expr="/form/field[@name='name']"))})
        result = self.plan(ext / "views/ext.xml", xm.ModuleViews())
        self.assertEqual(result.converted, ())
        self.assertEqual(self.refused_reasons(result), [TARGET])


if __name__ == "__main__":
    unittest.main()
