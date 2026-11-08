"""TST-011-074 (REQ-KAP-036): the view-index reader takes an optional knowledge root; the default is built-in.

An absent index in a release is reported as None (unverifiable), never as an error.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.view_index import VIEW_INDEX_DIR, load_view_index


class ViewIndexReaderRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        index = load_view_index("16.0")
        self.assertIsNotNone(index)
        self.assertEqual("16.0", index.version)
        shipped = json.loads((VIEW_INDEX_DIR / "16.0.json").read_text(encoding="utf-8"))
        self.assertEqual(shipped["revision"], index.revision)
        self.assertEqual(index.revision, load_view_index("16.0", root=VIEW_INDEX_DIR).revision)
        self.assertEqual(VIEW_INDEX_DIR, KNOWLEDGE_ROOT / "compatibility" / "view_index")

    def test_release_root_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(tmp) / "knowledge"
            target = knowledge / "compatibility" / "view_index"
            target.mkdir(parents=True)
            shutil.copy(VIEW_INDEX_DIR / "16.0.json", target / "16.0.json")
            index = load_view_index("16.0", knowledge_root=knowledge)
            self.assertIsNotNone(index)
            self.assertEqual(json.loads((target / "16.0.json").read_text(encoding="utf-8"))["revision"],
                             index.revision)
            self.assertIsNone(load_view_index("17.0", knowledge_root=knowledge))
            self.assertIsNone(load_view_index("16.0", knowledge_root=Path(tmp) / "empty"))


if __name__ == "__main__":
    unittest.main()
