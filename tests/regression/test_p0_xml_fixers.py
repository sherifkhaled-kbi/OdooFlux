"""P0 XML fixers: F-XML-1, F-XML-2, F-XML-4."""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import odooflux.rules.shared.legacy_rules as legacy
from odooflux.rules.shared.legacy_rules import (
    MigrationReport, apply_xml_fixes, check_content)


class StatesFixTests(unittest.TestCase):
    """TST-001-013 / TST-001-014 (F-XML-1, F-XML-4)."""

    def test_states_fix_well_formed(self):
        src = '<root><button name="a" states="draft" type="object"/></root>'
        out = apply_xml_fixes(src, 14, verified_state_field=True)
        ET.fromstring(out)
        self.assertNotIn("<!--", out)
        self.assertIn('invisible="state not in [\'draft\']"', out)
        self.assertNotIn("states=", out)

    def test_states_fix_skipped_when_invisible_present(self):
        src = '<root><button name="a" states="draft" invisible="0" type="object"/></root>'
        out = apply_xml_fixes(src, 14)
        self.assertEqual(out, src)
        self.assertNotIn("<!--", out)


class AttrsDetectOnlyTests(unittest.TestCase):
    """TST-001-024 (F-XML-2, EV-109): attrs= is never rewritten; it is a review finding."""

    SRC = "<root><field name=\"x\" attrs=\"{'invisible': [('state', '=', 'done')]}\"/></root>"

    def test_attrs_detect_only(self):
        self.assertEqual(apply_xml_fixes(self.SRC, 14), self.SRC)
        report = MigrationReport(module_path="", from_version=14, to_version=19)
        check_content(self.SRC, "view.xml", legacy.XML_RULES_C, 14, report)
        attrs = [i for i in report.issues if i.category == "Attrs Attribute"]
        self.assertEqual(len(attrs), 1)
        self.assertEqual(attrs[0].status, "NEEDS_REVIEW")
        self.assertIn("later release", attrs[0].suggestion)


if __name__ == "__main__":
    unittest.main()
