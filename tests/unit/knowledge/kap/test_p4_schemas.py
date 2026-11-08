"""TST-011-031 (REQ-KAP-006, REQ-KAP-010): source_registry (SourceSpec entry) and snapshot (SourceSnapshot) schemas.

Samples are built in code. Each schema must accept its valid sample, reject a sample missing a required key, and
reject an unknown extra key (the stdlib checker enforces `additionalProperties: false`).
"""

import copy
import json
import unittest

from odooflux.knowledge import validator as v
from odooflux.knowledge.loader import KNOWLEDGE_ROOT

SCHEMAS = KNOWLEDGE_ROOT / "schemas"
SHA_A = "a" * 64
SHA_B = "b" * 64
REV = "c" * 40
TS = "2026-11-08T10:00:00Z"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _source_registry() -> dict:
    return {
        "source_id": "odoo-community-17.0",
        "kind": "GIT_COMMUNITY",
        "official": True,
        "url": "https://github.com/odoo/odoo/",
        "licence_access": "PUBLIC_OPEN",
        "licence_id": "LGPL-3.0",
        "branch": "17.0",
        "revision": REV,
        "scope": {
            "modules": "*",
            "include": ["**/*.py", "**/*.xml"],
            "exclude": [{"pattern": "**/tests/**", "reason": "test code is not extracted"}],
            "file_kinds": ["python", "xml"],
        },
        "retrieved_at": TS,
        "checksum": SHA_A,
        "status": "VERIFIED",
        "failure_reason": None,
        "required": True,
    }


def _snapshot() -> dict:
    return {
        "snapshot_id": "ss-" + "ab" * 6,
        "source_id": "odoo-community-17.0",
        "revision": REV,
        "entries": [
            {"path": "addons/base/__manifest__.py", "sha256": SHA_A, "size": 120, "kind": "manifest"},
            {"path": "addons/base/models/res_users.py", "sha256": SHA_B, "size": 990, "kind": "python"},
        ],
        "snapshot_digest": "ab" * 32,
        "created_at": TS,
        "limits": {"excluded": [{"path": "addons/x/link.py", "reason": "SYMLINK_ESCAPE"}]},
    }


SAMPLES = {
    "source_registry": _source_registry,
    "snapshot": _snapshot,
}


class P4SchemaTests(unittest.TestCase):
    def test_valid_samples(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                self.assertEqual(v.check(make(), _load(name)), [])
        # a directory or pack source uses a content digest as revision; a null checksum is valid before retrieval
        registry = _source_registry()
        registry.update({"kind": "DIRECTORY", "official": False, "url": "local:/srv/kb",
                         "revision": "sha256:" + SHA_A, "status": "DECLARED", "checksum": None,
                         "retrieved_at": None})
        self.assertEqual(v.check(registry, _load("source_registry")), [])
        # a snapshot with nothing excluded is valid
        snap = _snapshot()
        snap["limits"] = {"excluded": []}
        self.assertEqual(v.check(snap, _load("snapshot")), [])

    def test_missing_field_fails(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                schema = _load(name)
                for key in schema["required"]:
                    sample = make()
                    del sample[key]
                    problems = v.check(sample, schema)
                    self.assertTrue(any(f"missing required key {key!r}" in msg for _, msg in problems),
                                    f"{name} without {key}: {problems}")

    def test_additional_property_fails(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                sample = make()
                sample["unexpected_field"] = 1
                problems = v.check(sample, _load(name))
                self.assertIn("/unexpected_field", [p for p, _ in problems])

    def test_status_enum_closed(self):
        schema = _load("source_registry")
        for status in ("DECLARED", "RETRIEVED", "VERIFIED", "UNAVAILABLE", "FAILED", "SKIPPED_UNAUTHORIZED"):
            with self.subTest(status=status):
                sample = _source_registry()
                sample["status"] = status
                self.assertEqual(v.check(sample, schema), [])
        bogus = _source_registry()
        bogus["status"] = "PENDING"
        self.assertTrue(v.check(bogus, schema))

    def test_kind_enum_closed(self):
        schema = _load("source_registry")
        bogus = _source_registry()
        bogus["kind"] = "GITHUB"
        self.assertTrue(v.check(bogus, schema))
        self.assertTrue(v.check(dict(_source_registry(), licence_access="FREE"), schema))

    def test_sha_pattern(self):
        registry_schema = _load("source_registry")
        for bad in ("A" * 40, "c" * 39, "g" * 40, "sha256:" + "A" * 64):
            with self.subTest(revision=bad):
                sample = _source_registry()
                sample["revision"] = bad
                self.assertTrue(v.check(sample, registry_schema))
        snap_schema = _load("snapshot")
        bad_entry = copy.deepcopy(_snapshot())
        bad_entry["entries"][0]["sha256"] = "A" * 64  # uppercase is not canonical
        self.assertTrue(v.check(bad_entry, snap_schema))
        bad_digest = copy.deepcopy(_snapshot())
        bad_digest["snapshot_digest"] = "ab" * 31
        self.assertTrue(v.check(bad_digest, snap_schema))
        bad_id = copy.deepcopy(_snapshot())
        bad_id["snapshot_id"] = "ss-XYZ"
        self.assertTrue(v.check(bad_id, snap_schema))

    def test_origin_fields_are_optional_and_https_only(self):
        registry_schema = _load("source_registry")
        snap_schema = _load("snapshot")
        self.assertNotIn("expected_origin", registry_schema["required"])
        self.assertNotIn("origin_url", registry_schema["required"])
        self.assertNotIn("origin_url", snap_schema["required"])
        self.assertEqual(v.check(_source_registry(), registry_schema), [])  # records without the new fields pass
        for field in ("expected_origin", "origin_url"):
            with self.subTest(field=field):
                ok = {**_source_registry(), field: "https://github.com/odoo/odoo"}
                self.assertEqual(v.check(ok, registry_schema), [])
                self.assertTrue(v.check({**_source_registry(), field: "git@github.com:odoo/odoo.git"},
                                        registry_schema))
        self.assertEqual(v.check(_snapshot(), snap_schema), [])
        self.assertEqual(v.check({**_snapshot(), "origin_url": "https://github.com/odoo/odoo"}, snap_schema), [])
        self.assertTrue(v.check({**_snapshot(), "origin_url": "http://github.com/odoo/odoo"}, snap_schema))


if __name__ == "__main__":
    unittest.main()
