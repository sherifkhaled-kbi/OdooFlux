"""TST-011-075 (REQ-KAP-036): the RNG map reader takes an optional knowledge root; the default is the built-in file."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.validation.static.rng import RNG_SCHEMAS_FILE, load_rng_map


class RngReaderRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(KNOWLEDGE_ROOT / "compatibility" / "rng_schemas.json", RNG_SCHEMAS_FILE)
        shipped = json.loads(RNG_SCHEMAS_FILE.read_text(encoding="utf-8"))
        self.assertTrue(shipped["versions"])
        for record in shipped["versions"]:
            self.assertEqual(load_rng_map(record["id"]), load_rng_map(record["id"], knowledge_root=KNOWLEDGE_ROOT))
        self.assertIsNone(load_rng_map("0.0"))

    def test_release_root_used(self):
        record = {"id": "99.0", "views": {"form": "form.rng", "tree": "tree.rng"}}
        with tempfile.TemporaryDirectory() as tmp:
            knowledge = Path(tmp) / "knowledge"
            (knowledge / "compatibility").mkdir(parents=True)
            (knowledge / "compatibility" / "rng_schemas.json").write_text(
                json.dumps({"versions": [record]}), encoding="utf-8")
            self.assertEqual({"form": "form.rng", "tree": "tree.rng"},
                             load_rng_map("99.0", knowledge_root=knowledge))
            self.assertIsNone(load_rng_map("99.0", knowledge_root=Path(tmp) / "empty"))
            self.assertIsNone(load_rng_map("16.0", knowledge_root=knowledge))


if __name__ == "__main__":
    unittest.main()
