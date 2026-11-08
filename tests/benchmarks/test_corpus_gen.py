"""T001 (REQ-PRF-001): the 300-module corpus generator is seeded and byte-deterministic.

Small corpora are used here (3 modules); the 300 x 30 shape is checked arithmetically and by the opt-in benchmark."""

import tempfile
import unittest
from pathlib import Path

from . import corpus_gen


class CorpusGeneratorTests(unittest.TestCase):
    def _make(self, seed, modules=3):
        root = Path(tempfile.mkdtemp()) / "corpus"
        info = corpus_gen.generate(root, modules=modules, files_per_module=30, seed=seed)
        return root, info

    def test_same_seed_gives_identical_digest(self):
        a, info_a = self._make(1)
        b, info_b = self._make(1)
        self.assertEqual(corpus_gen.corpus_digest(a), corpus_gen.corpus_digest(b))
        self.assertEqual(info_a["digest"], info_b["digest"])
        self.assertEqual(info_a["digest"], corpus_gen.corpus_digest(a))

    def test_different_seed_differs(self):
        a, _ = self._make(1)
        b, _ = self._make(2)
        self.assertNotEqual(corpus_gen.corpus_digest(a), corpus_gen.corpus_digest(b))

    def test_each_module_has_exactly_thirty_files_of_every_kind(self):
        root, info = self._make(1)
        self.assertEqual(info["modules"], 3)
        self.assertEqual(info["files"], 90)
        for module in sorted(p for p in root.iterdir() if p.is_dir()):
            files = [p for p in module.rglob("*") if p.is_file()]
            self.assertEqual(len(files), 30, module.name)
            suffixes = {p.suffix for p in files}
            self.assertTrue({".py", ".xml", ".js", ".csv"} <= suffixes)
            self.assertTrue((module / "__manifest__.py").is_file())

    def test_full_scale_shape_is_300_by_30(self):
        self.assertEqual(corpus_gen.DEFAULT_MODULES, 300)
        self.assertEqual(corpus_gen.DEFAULT_FILES_PER_MODULE, 30)
        self.assertEqual(corpus_gen.planned_file_count(300, 30), 9000)

    def test_templates_come_from_golden_fixtures_not_customer_code(self):
        self.assertTrue(all("golden_fixtures" in str(p) for p in corpus_gen.TEMPLATE_SOURCES))
        self.assertTrue(all(p.is_file() for p in corpus_gen.TEMPLATE_SOURCES))

    def test_rejects_unsupported_files_per_module(self):
        with self.assertRaises(ValueError):
            corpus_gen.generate(Path(tempfile.mkdtemp()) / "c", modules=1, files_per_module=3, seed=1)


if __name__ == "__main__":
    unittest.main()
