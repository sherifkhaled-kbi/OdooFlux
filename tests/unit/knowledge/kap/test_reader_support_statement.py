"""TST-011-078 (REQ-KAP-036): the support statement can be computed from an optional knowledge root; the default is the
built-in tree and its output is unchanged. A release-based statement claims no path as supported without recorded
runtime runs (the claim rule is not relaxed)."""

import json
import tempfile
import unittest
from pathlib import Path

from odooflux.cli import support_statement as ss
from odooflux.knowledge.loader import KNOWLEDGE_ROOT


class SupportStatementRootTests(unittest.TestCase):
    def test_default_path_unchanged(self):
        self.assertEqual(ss.generate_text(), ss.generate_text(knowledge_root=KNOWLEDGE_ROOT))
        self.assertEqual(ss.build_rows()[0], ss.build_rows(knowledge_root=KNOWLEDGE_ROOT)[0])

    def test_release_root_used(self):
        versions = {"versions": [{"id": "17.0"}, {"id": "18.0"}], "transitions": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compatibility").mkdir()
            (root / "compatibility" / "versions.json").write_text(json.dumps(versions), encoding="utf-8")
            rows, facts = ss.build_rows(knowledge_root=root)
            self.assertEqual([(r.source, r.target) for r in rows], [("17.0", "18.0")])
            self.assertEqual(facts, [])
            self.assertNotEqual(ss.generate_text(knowledge_root=root), ss.generate_text())
            self.assertIn("Paths: 0 supported, 0 experimental, 1 unsupported", ss.generate_text(knowledge_root=root))

    def test_release_without_runtime_runs_claims_no_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compatibility").mkdir()
            shipped = (KNOWLEDGE_ROOT / "compatibility" / "versions.json").read_text(encoding="utf-8")
            (root / "compatibility" / "versions.json").write_text(shipped, encoding="utf-8")
            rows, _ = ss.build_rows(knowledge_root=root)
            self.assertTrue(rows)
            self.assertFalse([r for r in rows if r.status == "supported"])


if __name__ == "__main__":
    unittest.main()
