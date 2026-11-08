"""TST-005-015 (REQ-PY-001, REQ-XML-001): parse + locate on generated 5,000-line files takes under 1 s each.

Opt-in: runs only when ODOOFLUX_BENCH=1, matching the other benchmarks in this folder."""

import os
import time
import unittest

from odooflux.core.engine.documents import Document
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import python as pyx

from ..unit import _setup  # noqa: F401  (src first on sys.path)

BUDGET_SECONDS = 1.0
LINES = 5000
RULE = "perf.parse-locate"


def generate_python(lines: int = LINES) -> str:
    out, n = ["from odoo import api, fields, models", ""], 0
    while len(out) < lines - 8:
        n += 1
        out += [
            f"class Model{n}(models.Model):",
            f"    _name = 'perf.model{n}'",
            f"    name = fields.Char(string='N{n}', size=64)",
            "",
            "    @api.multi",
            f"    def compute_{n}(self):",
            f"        return self.search([('state', '=', 'draft')]).mapped('name')",
            "",
        ]
    out += [f"# pad {i}" for i in range(lines - len(out))]
    return "\n".join(out) + "\n"


def generate_xml(lines: int = LINES) -> str:
    out = ["<odoo>"]
    n = 0
    while len(out) < lines - 1:
        n += 1
        out += [
            f'  <record id="view_{n}" model="ir.ui.view">',
            f'    <field name="name">View {n}</field>',
            f'    <field name="arch" type="xml">',
            f'      <form><field name="state" attrs="{{\'invisible\': [(\'state\', \'=\', \'done\')]}}"/></form>',
            "    </field>",
            "  </record>",
        ]
    out.append("</odoo>")
    return "\n".join(out[:lines]) + "\n"


@unittest.skipUnless(os.environ.get("ODOOFLUX_BENCH") == "1", "set ODOOFLUX_BENCH=1 to run")
class ParseLocatePerfTests(unittest.TestCase):
    def test_python_parse_and_locate_under_budget(self):
        source = generate_python()
        self.assertGreaterEqual(source.count("\n"), LINES - 1)
        document = Document.from_text("perf_generated.py", source)
        started = time.perf_counter()
        parsed = pydoc.parse_document(document)
        edits = pyx.remove_decorator(parsed, "api.multi", rule_id=RULE)
        elapsed = time.perf_counter() - started
        print(f"\npython parse+locate: {elapsed:.3f}s ({len(edits)} decorator spans)")
        self.assertIsNone(parsed.parse_error)
        self.assertGreater(len(edits), 0)
        self.assertLess(elapsed, BUDGET_SECONDS)

    def test_xml_parse_and_locate_under_budget(self):
        source = generate_xml()
        self.assertGreaterEqual(source.count("\n"), LINES - 1)
        document = Document.from_text("perf_generated.xml", source)
        started = time.perf_counter()
        xdoc = xmldoc.parse(document)
        found = xmldoc.find(xdoc, tag="field", attr="attrs")
        elapsed = time.perf_counter() - started
        print(f"\nxml parse+locate: {elapsed:.3f}s ({len(found)} attrs elements)")
        self.assertIsNone(xdoc.parse_error)
        self.assertGreater(len(found), 0)
        self.assertLess(elapsed, BUDGET_SECONDS)


if __name__ == "__main__":
    unittest.main()
