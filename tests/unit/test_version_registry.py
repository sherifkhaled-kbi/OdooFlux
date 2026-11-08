"""TST-003-007 (REQ-VER-001): the knowledge file loads, validates its schema, and is totally ordered."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.versions.registry.loader import (
    KNOWLEDGE_FILE, VersionDataError, load_version_data)

from ._setup import SRC  # noqa: F401


def _write(data) -> Path:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "versions.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class VersionRegistryTests(unittest.TestCase):
    def test_shipped_data_covers_12_to_19_in_order(self):
        versions, transitions = load_version_data(KNOWLEDGE_FILE)
        self.assertEqual([v.id for v in versions],
                         ["12.0", "13.0", "14.0", "15.0", "16.0", "17.0", "18.0", "19.0"])
        self.assertEqual(len(transitions), 7)
        self.assertEqual(transitions[("14.0", "15.0")], "RESEARCH_SEEDED")

    def test_rejects_duplicate_ids(self):
        base = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        base["versions"].append(dict(base["versions"][0]))
        with self.assertRaises(VersionDataError):
            load_version_data(_write(base))

    def test_rejects_unknown_status_enum(self):
        base = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        base["transitions"][0]["research_status"] = "MAYBE"
        with self.assertRaises(VersionDataError):
            load_version_data(_write(base))

    def test_rejects_missing_keys(self):
        base = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        del base["versions"][0]["python_min"]
        with self.assertRaises(VersionDataError):
            load_version_data(_write(base))


if __name__ == "__main__":
    unittest.main()
