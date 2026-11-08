"""TST-008-012 (REQ-XML-004, FR-010): RNG view validation returns FAIL for a malformed view when lxml is
present and UNAVAILABLE with a reason when lxml or the schema directory is missing. lxml is not installed in
the test environment, so the present branch injects a fake module with the interface rng.py calls."""

import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from odooflux.core.contracts.records import Document
from odooflux.validation.static.rng import validate_views

from .._setup import SRC  # noqa: F401

ALLOWED_TAGS = {"list", "tree", "field", "group", "form"}


def _view_doc(path: str, view_type: str, body: str) -> Document:
    text = (f'<odoo><record id="v" model="ir.ui.view"><field name="model">kbi.x</field>'
            f'<field name="arch" type="xml"><{view_type}>{body}</{view_type}></field></record></odoo>')
    return Document(path, text)


GOOD_LIST = _view_doc("views/list.xml", "list", '<field name="name"/>')
BAD_LIST = _view_doc("views/bad_list.xml", "list", "<bogus/>")
BAD_TREE = _view_doc("views/bad_tree.xml", "tree", "<bogus/>")


class _Entry:
    def __init__(self, message):
        self.message = message


class _XMLSyntaxError(Exception):
    pass


class _RelaxNG:
    """Fake with lxml's interface: RelaxNG(schema), validate(tree) -> bool, error_log entries with .message.
    Rule: only ALLOWED_TAGS may appear in a view."""

    def __init__(self, schema):
        if not Path(schema).is_file():
            raise OSError(f"schema not found: {schema}")
        self._errors = []

    def validate(self, tree):
        self._errors = [_Entry(f"Element {el.tag} not allowed here")
                        for el in tree.iter() if el.tag not in ALLOWED_TAGS]
        return not self._errors

    @property
    def error_log(self):
        return list(self._errors)


def _fake_lxml():
    etree = types.ModuleType("lxml.etree")

    def fromstring(text):
        try:
            return ET.fromstring(text)
        except ET.ParseError as exc:
            raise _XMLSyntaxError(str(exc)) from exc

    etree.XMLSyntaxError = _XMLSyntaxError
    etree.fromstring = fromstring
    etree.parse = lambda path: str(path)
    etree.RelaxNG = _RelaxNG
    package = types.ModuleType("lxml")
    package.etree = etree
    return package, etree


class RngValidationTests(unittest.TestCase):
    def setUp(self):
        self.schemas = Path(tempfile.mkdtemp(prefix="odooflux-rng-"))
        self.addCleanup(shutil.rmtree, self.schemas, True)
        (self.schemas / "list_view.rng").write_text("<grammar/>", encoding="utf-8")
        (self.schemas / "tree_view.rng").write_text("<grammar/>", encoding="utf-8")

    def test_malformed_list_view_fails_when_lxml_present(self):
        package, etree = _fake_lxml()
        with mock.patch.dict(sys.modules, {"lxml": package, "lxml.etree": etree}):
            findings, result = validate_views([BAD_LIST], target_version="19.0", schema_dir=self.schemas)
        self.assertEqual(result.layer, 2)
        self.assertEqual(result.outcome, "FAIL")
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.path, "views/bad_list.xml")
        self.assertIn("list", finding.message)
        self.assertIn("Element bogus not allowed here", finding.message)

    def test_malformed_tree_view_fails_for_16_0_when_lxml_present(self):
        package, etree = _fake_lxml()
        with mock.patch.dict(sys.modules, {"lxml": package, "lxml.etree": etree}):
            findings, result = validate_views([BAD_TREE], target_version="16.0", schema_dir=self.schemas)
        self.assertEqual(result.outcome, "FAIL")
        self.assertEqual([f.path for f in findings], ["views/bad_tree.xml"])
        self.assertIn("tree", findings[0].message)

    def test_valid_view_passes_when_lxml_present(self):
        package, etree = _fake_lxml()
        with mock.patch.dict(sys.modules, {"lxml": package, "lxml.etree": etree}):
            findings, result = validate_views([GOOD_LIST], target_version="19.0", schema_dir=self.schemas)
        self.assertEqual(findings, [])
        self.assertEqual(result.outcome, "PASS")

    def test_unavailable_with_reason_when_lxml_absent(self):
        with mock.patch.dict(sys.modules, {"lxml": None}):
            findings, result = validate_views([BAD_LIST], target_version="19.0", schema_dir=self.schemas)
        self.assertEqual(findings, [])
        self.assertEqual(result.outcome, "UNAVAILABLE")
        self.assertIn("lxml", result.reason)

    def test_unavailable_with_reason_when_no_schema_dir(self):
        package, etree = _fake_lxml()
        with mock.patch.dict(sys.modules, {"lxml": package, "lxml.etree": etree}):
            findings, result = validate_views([BAD_LIST], target_version="19.0", schema_dir=None)
        self.assertEqual(findings, [])
        self.assertEqual(result.outcome, "UNAVAILABLE")
        self.assertIn("schema", result.reason)

    def test_unavailable_when_schema_file_for_version_is_missing(self):
        package, etree = _fake_lxml()
        (self.schemas / "list_view.rng").unlink()
        with mock.patch.dict(sys.modules, {"lxml": package, "lxml.etree": etree}):
            _findings, result = validate_views([BAD_LIST], target_version="19.0", schema_dir=self.schemas)
        self.assertEqual(result.outcome, "UNAVAILABLE")
        self.assertIn("list_view.rng", result.reason)


class AvailableTests(unittest.TestCase):
    def test_available_matches_lxml_importability(self):
        from odooflux.validation.static import rng
        try:
            import lxml.etree  # noqa: F401
            expected = True
        except ImportError:
            expected = False
        self.assertIs(rng.available(), expected)


if __name__ == "__main__":
    unittest.main()
