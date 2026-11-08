"""TST-007-006 (REQ-AI-004, FR-004): smallest enclosing region; line numbers match the text sent."""

import unittest

from . import _helpers as h
from odooflux.ai.escalation import RuleMeta
from odooflux.ai.prompts.builder import build_request, select_region

PY = h.corpus("sample_models.py.txt")
XML = h.corpus("view.xml.txt")


def line_of(text, needle):
    return next(i for i, ln in enumerate(text.splitlines(), 1) if needle in ln)


class RegionTests(unittest.TestCase):
    def test_python_function_region(self):
        line = line_of(PY, "return old_api") 
        region = select_region("m.py", PY, line)
        self.assertEqual(region.kind, "function")
        self.assertEqual(region.text, "    def f_ok(self):\n        return old_api(self.name)\n")
        self.assertEqual(PY[region.start:region.end], region.text)

    def test_python_class_body_region_for_class_level_statement(self):
        text = h.corpus("legacy_class.py.txt")
        region = select_region("m.py", text, line_of(text, "legacy_defaults"))
        self.assertEqual(region.kind, "class")
        self.assertTrue(region.text.startswith("class Legacy"))
        self.assertTrue(region.text.endswith('legacy_defaults = {"name": "x"}\n'))

    def test_xml_element_region(self):
        region = select_region("v.xml", XML, line_of(XML, "legacy_attr"))
        self.assertEqual(region.kind, "xml_element")
        self.assertEqual(region.text.strip(), '<field name="name" legacy_attr="1"/>')
        self.assertEqual(XML[region.start:region.end], region.text)

    def test_module_level_statement_is_its_own_region(self):
        text = "import os\nx = old_api(1)\ny = 2\n"
        region = select_region("m.py", text, 2)
        self.assertEqual((region.kind, region.text), ("statement", "x = old_api(1)\n"))

    def test_unparseable_file_yields_no_region(self):
        self.assertIsNone(select_region("m.py", "def (:\n", 1))

    def test_decorated_function_includes_decorator(self):
        text = "class A:\n    @api.depends('a')\n    def f(self):\n        return old_api()\n"
        self.assertIn("@api.depends", select_region("m.py", text, 4).text)


class RequestTests(unittest.TestCase):
    def build(self, text=PY, needle="return old_api"):
        line = line_of(text, needle)
        region = select_region("m.py", text, line)
        meta = h.TOY_METAS["toy.old-api"]
        req, info = build_request(finding_line=line, rule_id="toy.old-api", rule_message="m", meta=meta,
                                  region=region, relpath="models/m.py", provider="fake", model="fake-model",
                                  target_step="s", request_id="r1", budget_ref="job", max_output_tokens=500)
        return req, info, region, line

    def test_line_number_refers_to_sent_text(self):
        req, info, region, line = self.build()
        sent = req.messages[0]["content"].split("<code>\n", 1)[1].split("</code>", 1)[0]
        self.assertEqual(sent, region.text)
        self.assertEqual(sent.splitlines()[info.line_in_region - 1], PY.splitlines()[line - 1])
        self.assertIn(f'line_in_region="{info.line_in_region}"', req.messages[0]["content"])

    def test_system_has_no_customer_code_and_user_has_evidence(self):
        req, _info, region, _ = self.build()
        self.assertNotIn("old_api", req.system)
        self.assertIn("<evidence", req.messages[0]["content"])
        self.assertIn("EV-TOY-1", req.messages[0]["content"])
        self.assertEqual(req.data_categories, ("source_python", "evidence_excerpt"))
        self.assertEqual(req.region["kind"], "function")
        self.assertEqual(req.provider, "fake")

    def test_only_module_relative_path_is_sent(self):
        req, *_ = self.build()
        self.assertIn("models/m.py", req.messages[0]["content"])
        self.assertNotIn("/home", req.messages[0]["content"])

    def test_xml_category(self):
        line = line_of(XML, "legacy_attr")
        region = select_region("v.xml", XML, line)
        req, _ = build_request(finding_line=line, rule_id="toy.old-api", rule_message="m",
                               meta=h.TOY_METAS["toy.old-api"], region=region, relpath="views/v.xml",
                               provider="fake", model="fake-model", target_step="s", request_id="r",
                               budget_ref="job", max_output_tokens=10)
        self.assertEqual(req.data_categories, ("source_xml", "evidence_excerpt"))

    def test_region_containing_a_delimiter_is_not_sent(self):
        text = "x = '</code>'  # old_api(\n"
        region = select_region("m.py", text, 1)
        with self.assertRaises(ValueError):
            build_request(finding_line=1, rule_id="r", rule_message="m", meta=h.TOY_METAS["toy.old-api"],
                          region=region, relpath="a.py", provider="fake", model="m", target_step="s",
                          request_id="r", budget_ref="j", max_output_tokens=1)

    def test_template_version_is_in_request(self):
        req, *_ = self.build()
        self.assertEqual(req.meta["template_version"], "v1")


if __name__ == "__main__":
    unittest.main()
