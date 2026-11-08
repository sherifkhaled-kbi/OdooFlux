"""TST-005-016 (REQ-TRF-003, REQ-TRF-004, SC-002, SC-003): whole-corpus byte preservation and idempotence.

Byte preservation: every file under tests/golden_fixtures/transformations (python, xml, converter, js)
and every feature 002 golden fixture receives the same fixed-seed random non-overlapping edits used by
test_preservation_fixtures; no byte outside an applied span may change.

Idempotence: the converter corpus is re-converted from its own expected output and must yield zero edits.
The Python corpus idempotence check lives in tests/unit/transformers/test_python_helpers.py.
"""

import json
import random
import unittest

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng
from odooflux.transformers import modifiers as mod
from odooflux.parsers.xml import document as xmldoc

from ..unit import _setup  # noqa: F401  (src first on sys.path)
from ..unit.engine.test_preservation_fixtures import (
    FIXTURES, RULE, SEED, outside_bytes_differ, random_edits)
from ..unit.transformers.test_modifiers import _cases, _convert, _target

CORPUS_ROOT = _setup.REPO / "tests" / "golden_fixtures" / "transformations"


def _corpus_files():
    for root in (CORPUS_ROOT, FIXTURES):
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != ".gitkeep" and path.name != "meta.json":
                yield path


class CorpusPreservationTests(unittest.TestCase):
    def test_no_byte_violations_on_all_corpora_and_fixtures(self):
        rng = random.Random(SEED)
        files = list(_corpus_files())
        self.assertGreater(len(files), 100)
        violations, applied_total = [], 0
        for file in files:
            rel = file.relative_to(_setup.REPO).as_posix()
            doc = docs.Document.from_bytes(rel, file.read_bytes())
            if doc.encode() != doc.raw:
                violations.append(f"{rel}: round-trip not byte-identical")
                continue
            batch = random_edits(doc, rng)
            result = eng.apply_edits(doc, batch, precedence=[RULE])
            applied_total += len(result.applied)
            if not result.preserved_ok or result.rejected:
                violations.append(f"{rel}: preserved_ok={result.preserved_ok} rejected={len(result.rejected)}")
                continue
            ordered = sorted(result.applied, key=lambda e: (e.start, e.end, e.id))
            if outside_bytes_differ(doc, ordered, doc.with_text(result.text).encode()):
                violations.append(f"{rel}: bytes differ outside spans")
        self.assertEqual(violations, [])
        self.assertGreater(applied_total, 0)


class ConverterIdempotenceTests(unittest.TestCase):
    def test_converted_output_yields_no_second_pass_edits(self):
        checked = 0
        for name, meta, case_dir in _cases():
            with self.subTest(case=name):
                expected = (case_dir / "expected.xml").read_text(encoding="utf-8")
                conversion, _ = _convert(expected, meta)
                self.assertEqual(list(conversion.edits), [], "second pass must produce no edits")
                checked += 1
        self.assertGreaterEqual(checked, 60)


if __name__ == "__main__":
    unittest.main()
