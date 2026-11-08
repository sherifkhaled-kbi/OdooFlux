"""TST-005-004 (REQ-TRF-004, SC-002): random non-overlapping edits on every feature 002 golden fixture
file never change a byte outside the edited spans. Fixed seed; any violation fails the test."""

import pathlib
import random
import unittest

from odooflux.core.engine import documents as docs
from odooflux.core.engine import edits as eng

from .. import _setup

FIXTURES = _setup.REPO / "tests" / "golden_fixtures" / "p0_kbi_demo_v14"
SEED = 20260506
AFTERS = ("", "X", "zz\n", "<!-- x -->", "\r\n", "é")
RULE = "harness.random"


def random_edits(doc: docs.Document, rng: random.Random) -> list:
    """Pairs of sorted cut points give disjoint spans; an empty pair is an insertion."""
    count = rng.randint(1, 8) * 2
    cuts = sorted(rng.randint(0, len(doc.text)) for _ in range(count))
    edits = []
    for k in range(0, count, 2):
        start, end = cuts[k], cuts[k + 1]
        after = rng.choice(AFTERS)
        try:
            after.encode(doc.encoding, errors="surrogateescape")
        except UnicodeEncodeError:
            after = "X"
        edits.append(eng.Edit(
            id=f"h{k:05d}", rule_id=RULE, path=doc.path, start=start, end=end,
            before=doc.text[start:end], after=after, severity="WARNING", step="harness",
            validation=()))
    return edits


def outside_bytes_differ(doc: docs.Document, ordered: list, result_bytes: bytes) -> bool:
    """True when the output bytes differ from the input raw bytes outside the (sorted, disjoint) spans."""
    head = 3 if doc.bom else 0
    expected, pos_text, pos_raw = [doc.raw[:head]], 0, head
    for edit in ordered:
        segment = doc.text[pos_text:edit.start].encode(doc.encoding, errors="surrogateescape")
        if doc.raw[pos_raw:pos_raw + len(segment)] != segment:
            return True
        expected.append(segment)
        pos_raw += len(segment) + len(edit.before.encode(doc.encoding, errors="surrogateescape"))
        expected.append(edit.after.encode(doc.encoding, errors="surrogateescape"))
        pos_text = edit.end
    tail = doc.text[pos_text:].encode(doc.encoding, errors="surrogateescape")
    if doc.raw[pos_raw:pos_raw + len(tail)] != tail:
        return True
    expected.append(tail)
    return b"".join(expected) != result_bytes


class PreservationFixtureTests(unittest.TestCase):
    def test_no_byte_violations_on_feature_002_fixtures(self):
        files = sorted(p for p in FIXTURES.rglob("*") if p.is_file())
        self.assertTrue(files, "no golden fixture files found")
        rng = random.Random(SEED)
        violations, applied_total = [], 0
        for file in files:
            rel = file.relative_to(_setup.REPO).as_posix()
            doc = docs.Document.from_bytes(rel, file.read_bytes())
            self.assertEqual(doc.encode(), doc.raw, rel)
            batch = random_edits(doc, rng)
            result = eng.apply_edits(doc, batch, precedence=[RULE])
            applied_total += len(result.applied)
            if not result.preserved_ok or result.rejected:
                violations.append(f"{rel}: preserved_ok={result.preserved_ok} rejected={len(result.rejected)}")
                continue
            ordered = sorted(result.applied, key=lambda e: (e.start, e.end, e.id))
            out = doc.with_text(result.text).encode()
            if outside_bytes_differ(doc, ordered, out):
                violations.append(f"{rel}: bytes differ outside spans")
        self.assertEqual(violations, [])
        self.assertGreater(applied_total, 0)


if __name__ == "__main__":
    unittest.main()
