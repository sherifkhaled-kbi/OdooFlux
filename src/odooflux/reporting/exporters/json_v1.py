"""JSON v1 export: the canonical, schema-validated report (FR-002, REQ-REP-001). Pure function of the model."""

import json

from odooflux.reporting.model.schema_check import validate_report


class InvalidReportError(ValueError):
    """The model does not validate against report.schema.json; nothing is written."""


def export_json_v1(report: dict) -> str:
    problems = validate_report(report)
    if problems:
        raise InvalidReportError("report model violates schema v1: " + "; ".join(problems[:5]))
    return json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
