"""TST-009-001 (REQ-REP-001): JSON v1 export validates against report.schema.json for every golden model."""

import json
import unittest

from ._setup import SRC  # noqa: F401
from .helpers import all_goldens
from .schema_validator import Validator, load, metaschema_validator

SCHEMA = None


def _schema():
    from odooflux.reporting.model.schema_check import SCHEMA_FILE
    return load(SCHEMA_FILE)


class JsonV1Tests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self):
        self.assertEqual(metaschema_validator().errors(_schema()), [])
        self.assertEqual(_schema()["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_export_validates_for_every_golden(self):
        from odooflux.reporting.exporters.json_v1 import export_json_v1
        validator = Validator(_schema())
        for name, model in all_goldens().items():
            document = json.loads(export_json_v1(model))
            self.assertEqual(validator.errors(document), [], name)

    def test_export_is_deterministic_and_lossless(self):
        from odooflux.reporting.exporters.json_v1 import export_json_v1
        model = all_goldens()["mixed"]
        text = export_json_v1(model)
        self.assertEqual(text, export_json_v1(model))
        self.assertEqual(json.loads(text), model)
        self.assertTrue(text.endswith("\n"))

    def test_schema_rejects_bad_documents(self):
        validator = Validator(_schema())
        bad = json.loads(json.dumps(all_goldens()["mixed"]))
        bad["modules"][0]["status"] = "MAYBE"
        self.assertTrue(validator.errors(bad))
        bad = json.loads(json.dumps(all_goldens()["mixed"]))
        del bad["summary"]
        self.assertTrue(validator.errors(bad))
        bad = json.loads(json.dumps(all_goldens()["mixed"]))
        bad["modules"][0]["layers"]["L4"]["outcome"] = "MAYBE"
        self.assertTrue(validator.errors(bad))

    def test_exporter_refuses_invalid_model(self):
        from odooflux.reporting.exporters.json_v1 import export_json_v1, InvalidReportError
        bad = json.loads(json.dumps(all_goldens()["mixed"]))
        bad["schema_version"] = "9"
        with self.assertRaises(InvalidReportError):
            export_json_v1(bad)

    def test_stdlib_subset_check_agrees(self):
        from odooflux.reporting.model.schema_check import validate_report
        for name, model in all_goldens().items():
            self.assertEqual(validate_report(model), [], name)


if __name__ == "__main__":
    unittest.main()
