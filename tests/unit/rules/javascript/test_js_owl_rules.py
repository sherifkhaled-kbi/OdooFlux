"""TST-006-031 (REQ-JS-002): JS/OWL review rules derived from the T019 evidence (EV-390..EV-395)."""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.javascript import generic as jg
from odooflux.rules.owl import generic as og
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

DEFINE = "16-17.js.odoo-define-legacy-form"
REGISTRY_ON = "15-16.js.service-registry-on"
MOUNTED = "15-16.owl.mounted-method"


def ctx(rid):
    return RuleContext(rule_id=rid, severity="WARNING", step="x", message="m", suggestion="s")


def doc(text):
    return Document.from_text("static/src/a.js", text)


class OdooDefineTests(unittest.TestCase):
    def detect(self, text):
        return jg.flag_odoo_define_legacy_form(doc(text), ctx(DEFINE))

    def test_two_argument_function_form_is_reported(self):
        findings = self.detect("odoo.define('m.a', function (require) {\n    'use strict';\n});\n")
        self.assertEqual([f.line for f in findings], [1])

    def test_arrow_and_async_function_forms_are_reported(self):
        self.assertEqual(len(self.detect('odoo.define("m.a", (require) => {});\n')), 1)
        self.assertEqual(len(self.detect('odoo.define("m.a", async function (require) {});\n')), 1)

    def test_dependency_array_form_is_not_reported(self):
        self.assertEqual(self.detect("odoo.define('m.a', ['web.core'], function (require) {});\n"), [])

    def test_comment_and_string_text_are_ignored(self):
        self.assertEqual(self.detect("// odoo.define('m.a', function (require) {});\nconst s = \"odoo.define('x', function(){})\";\n"), [])

    def test_other_define_is_not_reported(self):
        self.assertEqual(self.detect("other.define('m.a', function () {});\n"), [])


class RegistryOnTests(unittest.TestCase):
    def detect(self, text):
        return jg.flag_service_registry_on(doc(text), ctx(REGISTRY_ON))

    def test_on_listener_is_reported(self):
        self.assertEqual(len(self.detect('serviceRegistry.on("UPDATE", null, async (payload) => {});\n')), 1)

    def test_add_event_listener_is_not_reported(self):
        self.assertEqual(self.detect('serviceRegistry.addEventListener("UPDATE", async (ev) => {});\n'), [])

    def test_other_registry_on_is_not_reported(self):
        self.assertEqual(self.detect('bus.on("x", null, f);\n'), [])


class MountedTests(unittest.TestCase):
    def detect(self, text, method="mounted"):
        return og.flag_component_method(doc(text), ctx(MOUNTED), method=method)

    def test_mounted_method_is_reported(self):
        src = "class A extends Component {\n    mounted() {\n        this.x = 1;\n    }\n}\n"
        self.assertEqual([f.line for f in self.detect(src)], [2])

    def test_async_method_is_reported(self):
        self.assertEqual(len(self.detect("class A extends Component {\n    async mounted() {}\n}\n")), 1)

    def test_hook_and_call_are_not_reported(self):
        src = "class A extends Component {\n    setup() {\n        onMounted(() => {});\n        this.mounted();\n    }\n}\n"
        self.assertEqual(self.detect(src), [])

    def test_class_not_extending_component_is_not_reported(self):
        self.assertEqual(self.detect("class A {\n    mounted() {}\n}\n"), [])

    def test_invalid_method_name_raises(self):
        with self.assertRaises(ValueError):
            self.detect("x", method="a b")


class CatalogueTests(unittest.TestCase):
    def test_entries_bind_as_detect_only_review(self):
        rules = {r["id"]: r for r in load_knowledge().rules}
        for rid, evidence in ((DEFINE, {"EV-390", "EV-391"}), (REGISTRY_ON, {"EV-393"}), (MOUNTED, {"EV-395"})):
            bound = bind_rule(rules[rid], BINDABLE_MODULES)
            self.assertEqual(bound.maturity, "DETECT_ONLY", rid)
            self.assertTrue(bound.review_required, rid)
            self.assertIsNone(bound.fixer, rid)
            self.assertTrue(evidence <= set(rules[rid]["evidence"]), rid)


if __name__ == "__main__":
    unittest.main()
