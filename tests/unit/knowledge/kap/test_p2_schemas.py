"""TST-011-005 (REQ-KAP-022, REQ-KAP-047): release_manifest, package_manifest and active_pointer schemas.

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
RELEASE_ID = "kr-" + "ab" * 6
TS = "2026-11-08T10:00:00Z"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def _release_manifest() -> dict:
    return {
        "release_id": RELEASE_ID,
        "label": "community-17.0-18.0-2026.11",
        "format": "odooflux.release/1",
        "parent_release": None,
        "framework": {"built_with": "1.0.0", "min_framework": "1.0.0", "max_framework": None},
        "schema_versions": {"evidence": "1", "rule_metadata": "1"},
        "files": [{"path": "knowledge/evidence/EV-001.json", "sha256": SHA_A, "size": 120}],
        "sources": [{"source_id": "odoo-17.0", "revision": "a" * 40, "snapshot_digest": SHA_B,
                     "official": True, "status": "VERIFIED"}],
        "steps_covered": [{"step": "17-18", "completeness": "COMPLETE", "ledger_digest": SHA_A}],
        "coverage_manifest_digest": SHA_B,
        "completeness": "COMPLETE",
        "build": {"tool_version": "1.0.0", "build_time": TS, "host_free": True},
        "release_digest": "ab" * 32,
    }


def _package_manifest() -> dict:
    return {
        "format": "odooflux.package/1",
        "release_id": RELEASE_ID,
        "release_digest": "ab" * 32,
        "created_with": "odooflux 1.0.0",
        "compat": {"min_framework": "1.0.0", "max_framework": None, "schemas": {"evidence": "1"}},
        "entries": [{"path": "release.json", "sha256": SHA_A, "size": 800}],
        "entry_count": 1,
        "total_size": 800,
        "contains_enterprise_derived": False,
        "redaction_scan": {"status": "PASSED", "scanner_version": "1"},
    }


def _active_pointer() -> dict:
    return {
        "format": "odooflux.active/1",
        "release_id": RELEASE_ID,
        "digest": "ab" * 32,
        "activated_at": TS,
        "previous": [{"release_id": "kr-" + "cd" * 6, "digest": "cd" * 32, "deactivated_at": TS}],
    }


SAMPLES = {
    "release_manifest": _release_manifest,
    "package_manifest": _package_manifest,
    "active_pointer": _active_pointer,
}


class P2SchemaTests(unittest.TestCase):
    def test_valid_samples(self):
        for name, make in SAMPLES.items():
            with self.subTest(schema=name):
                self.assertEqual(v.check(make(), _load(name)), [])
        # an active pointer with no previous releases is valid (first activation)
        sample = _active_pointer()
        sample["previous"] = []
        self.assertEqual(v.check(sample, _load("active_pointer")), [])

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

    def test_nested_shape_and_patterns(self):
        bad_release_id = copy.deepcopy(_release_manifest())
        bad_release_id["release_id"] = "kr-XYZ"
        self.assertTrue(v.check(bad_release_id, _load("release_manifest")))
        bad_digest = copy.deepcopy(_package_manifest())
        bad_digest["entries"][0]["sha256"] = "A" * 64  # uppercase is not canonical
        self.assertTrue(v.check(bad_digest, _load("package_manifest")))
        bad_format = copy.deepcopy(_active_pointer())
        bad_format["format"] = "odooflux.active/9"
        self.assertTrue(v.check(bad_format, _load("active_pointer")))


if __name__ == "__main__":
    unittest.main()
