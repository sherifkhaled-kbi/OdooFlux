"""Stdlib JSON Schema validator for tests (drafts 04 and 2020-12 keyword subset used by the vendored
SARIF 2.1.0 schema and the 2020-12 meta-schema vocabularies). Test data only; not shipped in the core.

Supported: $ref (local pointer, relative document, "#/definitions", "#/$defs"), $dynamicRef "#meta" (resolved to
the root meta-schema), type, enum, const, required, properties, patternProperties, additionalProperties,
items (schema or array form), prefixItems, minItems, maxItems, uniqueItems, minimum, maximum, minLength,
maxLength, pattern, allOf, anyOf, oneOf, not, dependentRequired, propertyNames, if/then/else.
Annotation-only keywords (format, description, default, $comment, ...) are ignored.
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urldefrag

SCHEMAS = Path(__file__).resolve().parents[2] / "golden_fixtures" / "schemas"

_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
          "boolean": bool, "null": type(None)}


def _is_type(value, name):
    if name == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name in ("array", "object", "string", "null"):
        return isinstance(value, _TYPES[name])
    raise ValueError(f"unknown type {name!r}")


def _unique(items):
    seen = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            return False
        seen.append(key)
    return True


class Validator:
    def __init__(self, root: dict, documents: dict | None = None, base: str = ""):
        self.root = root
        self.base = base or root.get("$id") or root.get("id") or ""
        self.documents = dict(documents or {})
        if self.base:
            self.documents[urldefrag(self.base)[0]] = root

    def errors(self, instance) -> list:
        out: list = []
        self._check(instance, self.root, self.base, "$", out)
        return out

    def _resolve(self, ref: str, base: str):
        url, fragment = urldefrag(urljoin(base, ref)) if base else urldefrag(ref)
        doc = self.root if (not url or url == urldefrag(self.base)[0]) else self.documents.get(url)
        if doc is None:
            raise KeyError(f"unresolved $ref {ref!r} (base {base!r})")
        node = doc
        for part in [p for p in fragment.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node, (url or self.base)

    def _check(self, value, schema, base, where, out):
        if schema is True or schema == {}:
            return
        if schema is False:
            out.append(f"{where}: schema is false")
            return
        base = schema.get("$id", base) if isinstance(schema.get("$id"), str) else base
        if "$ref" in schema:
            node, new_base = self._resolve(schema["$ref"], base)
            self._check(value, node, new_base, where, out)
        if "$dynamicRef" in schema:
            self._check(value, self.root, self.base, where, out)
        if "type" in schema:
            kinds = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, k) for k in kinds):
                out.append(f"{where}: expected type {schema['type']}, got {type(value).__name__}")
                return
        if "const" in schema and value != schema["const"]:
            out.append(f"{where}: must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            out.append(f"{where}: {value!r} not in enum")
        for key, sub in (("allOf", None), ("anyOf", None), ("oneOf", None)):
            if key in schema:
                results = []
                for option in schema[key]:
                    errs: list = []
                    self._check(value, option, base, where, errs)
                    results.append(errs)
                passed = sum(1 for r in results if not r)
                if key == "allOf":
                    for r in results:
                        out.extend(r)
                elif key == "anyOf" and passed == 0:
                    out.append(f"{where}: matches none of anyOf")
                elif key == "oneOf" and passed != 1:
                    out.append(f"{where}: matches {passed} of oneOf (need exactly 1)")
        if "not" in schema:
            errs = []
            self._check(value, schema["not"], base, where, errs)
            if not errs:
                out.append(f"{where}: matches a 'not' schema")
        if "if" in schema:
            errs = []
            self._check(value, schema["if"], base, where, errs)
            branch = schema.get("then") if not errs else schema.get("else")
            if branch is not None:
                self._check(value, branch, base, where, out)
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append(f"{where}: shorter than {schema['minLength']}")
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                out.append(f"{where}: longer than {schema['maxLength']}")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append(f"{where}: does not match {schema['pattern']!r}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append(f"{where}: below minimum {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                out.append(f"{where}: above maximum {schema['maximum']}")
        if isinstance(value, dict):
            for key in schema.get("required", []) if isinstance(schema.get("required"), list) else []:
                if key not in value:
                    out.append(f"{where}: missing required {key!r}")
            for key, needs in schema.get("dependentRequired", {}).items():
                if key in value:
                    out.extend(f"{where}: {key!r} requires {n!r}" for n in needs if n not in value)
            props = schema.get("properties", {})
            patterns = schema.get("patternProperties", {})
            for key, item in value.items():
                matched = False
                if key in props:
                    matched = True
                    self._check(item, props[key], base, f"{where}.{key}", out)
                for pattern, sub in patterns.items():
                    if re.search(pattern, key):
                        matched = True
                        self._check(item, sub, base, f"{where}.{key}", out)
                if not matched and "additionalProperties" in schema:
                    extra = schema["additionalProperties"]
                    if extra is False:
                        out.append(f"{where}: unexpected property {key!r}")
                    elif isinstance(extra, dict):
                        self._check(item, extra, base, f"{where}.{key}", out)
            if "propertyNames" in schema:
                for key in value:
                    self._check(key, schema["propertyNames"], base, f"{where}.<name {key}>", out)
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append(f"{where}: fewer than {schema['minItems']} items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                out.append(f"{where}: more than {schema['maxItems']} items")
            if schema.get("uniqueItems") and not _unique(value):
                out.append(f"{where}: items are not unique")
            prefix = schema.get("prefixItems")
            items = schema.get("items")
            if isinstance(items, list):
                prefix, items = items, schema.get("additionalItems")
            for index, item in enumerate(value):
                if prefix and index < len(prefix):
                    self._check(item, prefix[index], base, f"{where}[{index}]", out)
                elif isinstance(items, dict) or items is False:
                    self._check(item, items, base, f"{where}[{index}]", out)


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sarif_validator() -> Validator:
    return Validator(load(SCHEMAS / "sarif-schema-2.1.0.json"), base="")


def metaschema_validator() -> Validator:
    root_dir = SCHEMAS / "json-schema-2020-12"
    root = load(root_dir / "schema.json")
    docs = {}
    for path in (root_dir / "meta").glob("*.json"):
        doc = load(path)
        docs[doc["$id"]] = doc
    return Validator(root, docs)
