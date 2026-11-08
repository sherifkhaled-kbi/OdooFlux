"""TST-007-017 (REQ-TST-005, REQ-AI-003): one regression test per legacy AI finding of the P0 audit
(docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md): F-AI-1, F-AI-2, F-AI-4, F-AI-5, F-AI-6, F-AI-7."""

import json
import re
import unittest
from pathlib import Path

from tests.integration.ai import test_pipeline_pass as pp
from tests.unit.ai import _helpers as h
from odooflux.core.orchestrator.run import report_from_dict
from odooflux.utils.hashing import digest_tree

SRC = h.SRC / "odooflux"


def reply(replacement, **kw):
    d = {"replacement": replacement, "notes": "", "cannot_fix": False, "usage": {"input": 40, "output": 8}}
    d.update(kw)
    return d


ToyRule, make_module = pp.ToyRule, pp.make_module


class LegacyAIFindingRegressions(pp.PipelineAIPassTests):
    """Reuses the pipeline fixture (fake provider, toy rule, tmp state); inherited tests are skipped here."""

    def setUp(self):
        super().setUp()

    def _script(self, entries):
        self.script.write_text(json.dumps({"entries": entries}))

    def test_F_AI_1_findings_are_scanned_on_the_text_that_is_sent_not_taken_from_stale_report_lines(self):
        # a leading block shifts every line; the report's own lines (computed earlier) are not used for escalation
        module = make_module(self.tmp, "# pad\n" * 30 + "from odoo import models\n\n\nclass A(models.Model):\n    _name = 'kbi.a'\n\n"
                                       "    def f_ok(self):\n        return old_api(1)\n")
        self._script([{"match": {"contains": "def f_ok"}, "response": reply("    def f_ok(self):\n        return new_api(1)\n")}])
        state, _ = self.run_ai(module)
        text = (module / "models" / "a.py").read_text()
        self.assertIn("new_api(1)", text)
        self.assertEqual(text.count("# pad"), 30)  # nothing else in the file moved
        self.assertEqual(state["ai_usage"]["requests"], 1)

    def test_F_AI_2_one_region_per_request_and_truncation_is_rejected_with_a_reason(self):
        body = "from odoo import models\n\n\nclass A(models.Model):\n    _name = 'kbi.a'\n" + "".join(
            f"\n    def f{i}(self):\n        return old_api({i})\n" for i in range(3)) + \
            "\n    def big(self):\n" + "        x = 1\n" * 200
        module = make_module(self.tmp, body)
        self._script([{"match": {"contains": "def f0"}, "response": reply("    def f0(self):\n        return new_", stop_reason="max_tokens")},
                      {"match": {"contains": "def f1"}, "response": reply("    def f1(self):\n        return new_api(1)\n")},
                      {"match": {"contains": "def f2"}, "response": reply("    def f2(self):\n        return new_api(2)\n")}])
        state, _ = self.run_ai(module)
        usage = state["ai_usage"]
        self.assertEqual(usage["requests"], 3)  # one request per finding, never one bundle
        self.assertEqual(usage["rejections"], {"truncated": 1})  # stop_reason is checked
        text = (module / "models" / "a.py").read_text()
        self.assertIn("return old_api(0)", text)  # no partial edit applied
        self.assertIn("new_api(1)", text)

    def test_F_AI_4_a_finding_is_fixed_only_when_the_rescan_no_longer_reports_it(self):
        module = make_module(self.tmp)
        self._script([{"match": {"contains": "def f_ok"}, "response": reply("    def f_ok(self):\n        return old_api(1)  # touched\n")}])
        state, _ = self.run_ai(module)
        report = report_from_dict(dict(state["modules"][0]["report"]))
        toy = [i for i in report.issues if i.category == "toy.old-api"]
        self.assertTrue(toy)
        self.assertFalse(any(i.fix_applied for i in toy))  # the model claimed a fix; the re-scan disagreed
        self.assertEqual(state["ai_usage"]["rejections"], {"finding_unresolved": 1})

    def test_F_AI_5_same_file_name_in_two_directories_never_cross_applies(self):
        module = make_module(self.tmp)
        (module / "wizards").mkdir()
        (module / "wizards" / "a.py").write_text(
            "from odoo import models\n\n\nclass W(models.TransientModel):\n    _name = 'kbi.w'\n\n"
            "    def w_run(self):\n        return old_api(2)\n")
        self._script([{"match": {"contains": "def f_ok"}, "response": reply("    def f_ok(self):\n        return new_api(1)\n")},
                      {"match": {"contains": "def w_run"}, "response": reply("    def w_run(self):\n        return new_api(2)\n")}])
        self.run_ai(module)
        self.assertIn("def f_ok(self):\n        return new_api(1)", (module / "models" / "a.py").read_text())
        self.assertNotIn("w_run", (module / "models" / "a.py").read_text())
        self.assertIn("def w_run(self):\n        return new_api(2)", (module / "wizards" / "a.py").read_text())
        self.assertNotIn("f_ok", (module / "wizards" / "a.py").read_text())

    def test_F_AI_6_model_is_configuration_key_is_not_on_the_command_line_and_no_debug_file_in_the_module(self):
        # configuration: no model identifier in the new AI code; the key is read from the environment or a secrets file
        from tests.unit.ai.test_catalog import LEGACY, MODEL_NAMES
        ai_root = SRC / "ai"
        for path in ai_root.rglob("*.py"):
            if path.relative_to(ai_root).as_posix() not in LEGACY:
                self.assertIsNone(MODEL_NAMES.search(path.read_text(encoding="utf-8")), path.name)
        from odooflux.cli.main import build_parser
        options = {a for action in build_parser()._subparsers._group_actions[0].choices["migrate"]._actions
                   for a in action.option_strings}
        self.assertFalse({"--ai-api-key", "--ai-key"} & options)
        # artefacts: nothing but the edited file changes inside the module
        module = make_module(self.tmp)
        before = dict(digest_tree(module))
        self._script([{"match": {"contains": "def f_ok"}, "response": reply("    def f_ok(self):\n        return new_api(1)\n")}])
        self.run_ai(module)
        after = dict(digest_tree(module))
        self.assertEqual(sorted(set(after) ^ set(before)), [])  # no new file (no ai_response_debug.txt)
        # the deterministic pass may also rewrite the manifest; the AI pass adds nothing and edits only a.py
        self.assertTrue(set(p for p in after if after[p] != before[p]) <= {"models/a.py", "__manifest__.py"})
        self.assertIn("models/a.py", [p for p in after if after[p] != before[p]])

    def test_F_AI_7_protected_identifiers_are_verified_not_just_syntax(self):
        module = make_module(self.tmp, "from odoo import models, fields\n\n\nclass A(models.Model):\n    _name = 'kbi.a'\n"
                                       "    qty = fields.Integer()\n    legacy_defaults = {'qty': 1}\n")
        renamed = ("class A(models.Model):\n    _name = 'kbi.a'\n    quantity = fields.Integer()\n")
        self._script([{"match": {"contains": "legacy_defaults"}, "response": reply(renamed)}])
        metas = dict(h.TOY_METAS)
        state, _ = self.run_ai(module, rule=ToyRule("toy.legacy-defaults", "legacy_defaults"), metas=metas)
        self.assertEqual(state["ai_usage"]["rejections"], {"protected_identifier_changed": 1})
        self.assertIn("qty = fields.Integer()", (module / "models" / "a.py").read_text())


# only the F-AI tests above belong in this module; drop the inherited fixture tests from collection
for _name in [n for n in dir(pp.PipelineAIPassTests) if n.startswith("test_")]:
    if not _name.startswith("test_F_AI_"):
        setattr(LegacyAIFindingRegressions, _name, None)


if __name__ == "__main__":
    unittest.main()
