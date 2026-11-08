"""TST-004-001 (REQ-EVD-002): the stdlib checker handles every keyword the schemas use."""

import unittest

from odooflux.knowledge import validator as v

from .helpers import SHIPPED  # noqa: F401


class SchemaCheckerTests(unittest.TestCase):
    def ok(self, value, schema):
        self.assertEqual(v.check(value, schema), [], value)

    def bad(self, value, schema, pointer=None):
        problems = v.check(value, schema)
        self.assertTrue(problems, f"expected a problem for {value!r}")
        if pointer is not None:
            self.assertIn(pointer, [p for p, _ in problems])
        return problems

    def test_type_string(self):
        self.ok("x", {"type": "string"})
        self.bad(1, {"type": "string"}, "")

    def test_type_integer_rejects_bool(self):
        self.ok(3, {"type": "integer"})
        self.bad(True, {"type": "integer"})

    def test_type_number_and_boolean_and_null(self):
        self.ok(1.5, {"type": "number"})
        self.ok(False, {"type": "boolean"})
        self.ok(None, {"type": "null"})
        self.bad("1", {"type": "number"})

    def test_union_types(self):
        self.ok(None, {"type": ["string", "null"]})
        self.ok("x", {"type": ["string", "null"]})
        self.bad(3, {"type": ["string", "null"]})

    def test_enum(self):
        self.ok("LOW", {"enum": ["LOW", "HIGH"]})
        self.bad("MID", {"enum": ["LOW", "HIGH"]})

    def test_const(self):
        self.ok("1.0.0", {"const": "1.0.0"})
        self.bad("2.0.0", {"const": "1.0.0"})

    def test_pattern(self):
        self.ok("EV-001", {"type": "string", "pattern": "^EV-\\d{3}$"})
        self.bad("EV-1", {"type": "string", "pattern": "^EV-\\d{3}$"})

    def test_min_and_max_length(self):
        self.bad("", {"type": "string", "minLength": 1})
        self.bad("x" * 301, {"type": "string", "maxLength": 300})
        self.ok("x" * 300, {"type": "string", "maxLength": 300})

    def test_minimum_and_maximum(self):
        self.ok(1, {"type": "integer", "minimum": 1})
        self.bad(0, {"type": "integer", "minimum": 1})
        self.bad(5, {"type": "integer", "maximum": 4})

    def test_required_keys(self):
        self.bad({"a": 1}, {"type": "object", "required": ["a", "b"]}, "")

    def test_nested_object_pointer(self):
        schema = {"type": "object", "properties": {"inner": {"type": "object", "required": ["x"]}}}
        self.bad({"inner": {}}, schema, "/inner")

    def test_additional_properties_false_flags_unknown_keys(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}}
        problems = self.bad({"a": "x", "zzz": 1}, schema)
        self.assertEqual(problems[0][0], "/zzz")

    def test_array_items_pointers(self):
        problems = self.bad([1, "x", 3], {"type": "array", "items": {"type": "integer"}})
        self.assertEqual([p for p, _ in problems], ["/1"])

    def test_min_items(self):
        self.bad([], {"type": "array", "minItems": 1})
        self.ok([1], {"type": "array", "minItems": 1})

    def test_json_pointer_escaping(self):
        problems = self.bad({"a/b": 1}, {"type": "object", "properties": {"a/b": {"type": "string"}}})
        self.assertEqual(problems[0][0], "/a~1b")

    def test_wrong_type_stops_further_keywords(self):
        self.assertEqual(len(v.check(3, {"type": "string", "pattern": "^x$", "minLength": 9})), 1)

    def test_every_shipped_schema_is_valid_json_with_known_keywords(self):
        import json
        known = {"$schema", "title", "type", "enum", "const", "pattern", "required", "properties",
                 "additionalProperties", "items", "minItems", "minLength", "maxLength", "minimum", "maximum",
                 "description", "$id", "$defs", "$ref"}
        from odooflux.knowledge.loader import KNOWLEDGE_ROOT
        for path in sorted((KNOWLEDGE_ROOT / "schemas").glob("*.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))

            def walk(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in ("properties", "$defs") and isinstance(value, dict):
                            for sub in value.values():  # property names are not keywords; their schemas are
                                walk(sub)
                            continue
                        if key not in known and not key.startswith("$"):
                            self.assertIn(key, known | {"default"}, f"{path.name}: unknown keyword {key}")
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)
            walk(schema)


if __name__ == "__main__":
    unittest.main()
