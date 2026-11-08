"""Stdlib validator for the JSON Schema subset used by report.schema.json (type, required, enum,
const, properties, items). Used as the documentation-grade schema check of contracts/result-model-v1.md."""

import json
from pathlib import Path

SCHEMA_FILE = Path(__file__).with_name("report.schema.json")

_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}


def _check(value, schema: dict, where: str, errors: list) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{where}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} not in {schema['enum']}")
    expected = schema.get("type")
    if expected:
        kinds = expected if isinstance(expected, list) else [expected]
        ok = any(isinstance(value, _TYPES[k]) and not (k == "integer" and isinstance(value, bool))
                 for k in kinds)
        if not ok:
            errors.append(f"{where}: expected {expected}, got {type(value).__name__}")
            return
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing required key {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                _check(value[key], sub, f"{where}.{key}", errors)
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _check(item, schema["items"], f"{where}[{index}]", errors)


def validate_report(report: dict, schema_path: Path = SCHEMA_FILE) -> list:
    """Return a list of human-readable errors; empty means valid."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors: list = []
    _check(report, schema, "report", errors)
    return errors
