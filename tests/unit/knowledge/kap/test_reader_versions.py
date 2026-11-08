"""TST-011-073 (REQ-KAP-036): the versions reader takes an optional knowledge root; the default is the built-in file.

A release's versions file is `<release>/knowledge/compatibility/versions.json` (see test_loader_active.py).
"""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.versions.registry.loader import KNOWLEDGE_FILE, load_version_data


class VersionsReaderRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        versions, transitions = load_version_data()
        explicit_versions, explicit_transitions = load_version_data(KNOWLEDGE_FILE)
        self.assertEqual(len(versions), 8)
        self.assertEqual(len(transitions), 7)
        self.assertEqual(versions, explicit_versions)
        self.assertEqual(transitions, explicit_transitions)

    def test_release_root_used(self):
        data = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))
        data["transitions"] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "knowledge"
            (root / "compatibility").mkdir(parents=True)
            (root / "compatibility" / "versions.json").write_text(json.dumps(data), encoding="utf-8")
            versions, transitions = load_version_data(knowledge_root=root)
        self.assertEqual(len(versions), 8)
        self.assertEqual(transitions, {})


if __name__ == "__main__":
    unittest.main()
