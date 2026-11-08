"""TST-006-030 (REQ-JS-002): ``17-18.js.rpc-service-removed`` (detect-only, review)."""

import unittest
from unittest import mock

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.parsers.javascript import treesitter_adapter
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.javascript import generic as jg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

RULE = "17-18.js.rpc-service-removed"


def detect(src):
    ctx = RuleContext(rule_id=RULE, severity="WARNING", step="17-18", message="m", suggestion="s")
    return jg.flag_rpc_service(Document.from_text("static/src/a.js", src), ctx)


class PositiveTests(unittest.TestCase):
    def test_use_service_rpc(self):
        findings = detect('setup() {\n    this.rpc = useService("rpc");\n}\n')
        self.assertEqual([f.line for f in findings], [2])
        self.assertEqual(findings[0].rule_id, RULE)

    def test_single_quotes(self):
        self.assertEqual(len(detect("const r = useService('rpc');\n")), 1)

    def test_env_services_rpc(self):
        self.assertEqual(len(detect("const r = this.env.services.rpc;\n")), 1)

    def test_services_subscript(self):
        self.assertEqual(len(detect('const r = env.services["rpc"];\n')), 1)

    def test_registry_get(self):
        self.assertEqual(len(detect('const s = registry.category("services").get("rpc");\n')), 1)


class NegativeTests(unittest.TestCase):
    def test_other_service(self):
        self.assertEqual(detect('const o = useService("orm");\n'), [])

    def test_rpc_function_import(self):
        self.assertEqual(detect('import { rpc } from "@web/core/network/rpc";\nawait rpc("/x");\n'), [])

    def test_comment_and_string_text_are_ignored(self):
        self.assertEqual(detect('// useService("rpc")\nconst t = "services.rpc";\n'), [])

    def test_template_text_is_ignored(self):
        self.assertEqual(detect("const t = `env.services.rpc`;\n"), [])

    def test_longer_names(self):
        self.assertEqual(detect('useService("rpc_extra"); env.services.rpcs;\n'), [])


class AdapterModeTests(unittest.TestCase):
    SRC = 'const a = useService("rpc");\nconst b = env.services.rpc;\n'

    def test_same_result_with_and_without_adapter(self):
        with mock.patch.object(treesitter_adapter, "available", return_value=False):
            lexer_mode = [f.line for f in detect(self.SRC)]
        with mock.patch.object(treesitter_adapter, "available", return_value=True):
            adapter_mode = [f.line for f in detect(self.SRC)]
        self.assertEqual(lexer_mode, [1, 2])
        self.assertEqual(adapter_mode, lexer_mode)


class CatalogueTests(unittest.TestCase):
    def test_entry_is_detect_only_review_without_fixer(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.review_required)
        self.assertIsNone(bound.fixer)
        self.assertEqual(meta["evidence"], ["EV-120", "EV-394"])
        doc = Document.from_text("a.js", 'useService("rpc")')
        self.assertEqual(bound.fix(doc), [])
        self.assertEqual(len(bound.detect(doc)), 1)


if __name__ == "__main__":
    unittest.main()
