"""Stdlib schema checker for the subset of JSON Schema (2020-12) keywords used by
knowledge/schemas/*.schema.json: type, enum, const, pattern, required, properties,
additionalProperties, items, minItems, minLength, maxLength, minimum, maximum.

Returns (pointer, message) pairs. Pointers follow JSON Pointer syntax (RFC 6901)."""

import re

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _is_type(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def check(value, schema: dict, pointer: str = "") -> list:
    """Validate *value* against *schema*. Returns a list of (pointer, message)."""
    problems = []
    if "const" in schema and value != schema["const"]:
        problems.append((pointer, f"must be {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        problems.append((pointer, f"{value!r} is not one of {schema['enum']}"))
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, n) for n in names):
            problems.append((pointer, f"expected {'/'.join(names)}, got {type(value).__name__}"))
            return problems  # further keywords assume the right type
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append((pointer, f"{value!r} does not match {schema['pattern']}"))
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append((pointer, f"shorter than {schema['minLength']} characters"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append((pointer, f"longer than {schema['maxLength']} characters"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append((pointer, f"must be >= {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            problems.append((pointer, f"must be <= {schema['maximum']}"))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append((pointer, f"missing required key {key!r}"))
        props = schema.get("properties", {})
        for key, sub in props.items():
            if key in value:
                problems += check(value[key], sub, f"{pointer}/{_escape(key)}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    problems.append((f"{pointer}/{_escape(key)}", "unknown key"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            problems.append((pointer, f"needs at least {schema['minItems']} item(s)"))
        if "items" in schema:
            for index, item in enumerate(value):
                problems += check(item, schema["items"], f"{pointer}/{index}")
    return problems
