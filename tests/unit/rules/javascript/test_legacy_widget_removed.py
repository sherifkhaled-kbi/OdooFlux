"""TST-006-031 (REQ-JS-002): ``17-18.js.legacy-widget-removed`` (detect-only, review; EV-392)."""

import unittest

from odooflux.core.engine.documents import Document
from odooflux.knowledge.loader import load_knowledge
from odooflux.rules.bindable import BINDABLE_MODULES
from odooflux.rules.javascript import generic as jg
from odooflux.rules.shared.emit import RuleContext
from odooflux.rules.shared.loader import bind_rule

from ... import _setup  # noqa: F401

RULE = "17-18.js.legacy-widget-removed"


def detect(src):
    ctx = RuleContext(rule_id=RULE, severity="WARNING", step="17-18", message="m", suggestion="s")
    return jg.flag_legacy_widget_import(Document.from_text("static/src/a.js", src), ctx)


class PositiveTests(unittest.TestCase):
    def test_esm_import(self):
        findings = detect('/** @odoo-module **/\nimport Widget from "@web/legacy/js/core/widget";\n')
        self.assertEqual([f.line for f in findings], [2])
        self.assertEqual(findings[0].rule_id, RULE)

    def test_single_quotes_and_js_suffix(self):
        self.assertEqual(len(detect("import W from '@web/legacy/js/core/widget.js';\n")), 1)

    def test_side_effect_import_and_require(self):
        self.assertEqual(len(detect('import "@web/legacy/js/core/widget";\n')), 1)
        self.assertEqual(len(detect('const W = require("@web/legacy/js/core/widget");\n')), 1)


class NegativeTests(unittest.TestCase):
    def test_other_legacy_module(self):
        self.assertEqual(detect('import c from "@web/legacy/js/core/class";\n'), [])

    def test_longer_path(self):
        self.assertEqual(detect('import w from "@web/legacy/js/core/widget_extra";\n'), [])

    def test_comment_string_and_template(self):
        src = '// import W from "@web/legacy/js/core/widget";\nconst t = "@web/legacy/js/core/widget";\nconst u = `@web/legacy/js/core/widget`;\n'
        self.assertEqual(detect(src), [])


class CatalogueTests(unittest.TestCase):
    def test_entry_is_detect_only_review_without_fixer(self):
        meta = next(r for r in load_knowledge().rules if r["id"] == RULE)
        bound = bind_rule(meta, BINDABLE_MODULES)
        self.assertEqual(bound.maturity, "DETECT_ONLY")
        self.assertTrue(bound.review_required)
        self.assertIsNone(bound.fixer)
        self.assertEqual(meta["evidence"], ["EV-392"])
        doc = Document.from_text("a.js", 'import W from "@web/legacy/js/core/widget";')
        self.assertEqual(bound.fix(doc), [])
        self.assertEqual(len(bound.detect(doc)), 1)


if __name__ == "__main__":
    unittest.main()
