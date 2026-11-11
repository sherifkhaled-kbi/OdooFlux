"""RC performance fix: build step 6 must read each pending evidence file once, not once per candidate.

On a real pair the loop over PROPOSED candidates re-read and re-parsed every pending evidence row for each candidate
(candidates x evidence files, tens of thousands of each). `_PendingEvidence` loads the folder once, answers each
candidate with the rows it cites in the old order (sorted by file name), and forgets rows as they are consumed.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.knowledge import pipeline as pl


def write(folder: Path, ids):
    folder.mkdir(parents=True, exist_ok=True)
    for ev_id in ids:
        (folder / f"{ev_id}.json").write_text(json.dumps({"id": ev_id, "n": ev_id}), encoding="utf-8")


class PendingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.folder = Path(self._t.name) / "evidence"

    def test_files_are_read_once_however_many_candidates_ask(self):
        write(self.folder, [f"EV-{n:03d}" for n in range(1, 201)])
        with mock.patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as reads:
            pending = pl._PendingEvidence(self.folder)
            for n in range(1, 201):
                pending.rows([f"EV-{n:03d}"])
            self.assertEqual(reads.call_count, 200)

    def test_rows_come_back_in_file_name_order_and_only_the_cited_ones(self):
        write(self.folder, ["EV-999", "EV-1000", "EV-100", "EV-002"])
        pending = pl._PendingEvidence(self.folder)
        got = [r["id"] for r in pending.rows({"EV-1000", "EV-100", "EV-002", "EV-404"})]
        expected = [p.stem for p in sorted(self.folder.glob("EV-*.json")) if p.stem in {"EV-1000", "EV-100", "EV-002"}]
        self.assertEqual(got, expected)

    def test_a_consumed_row_is_forgotten(self):
        write(self.folder, ["EV-001", "EV-002"])
        pending = pl._PendingEvidence(self.folder)
        pending.drop(["EV-001"])
        self.assertEqual([r["id"] for r in pending.rows(["EV-001", "EV-002"])], ["EV-002"])

    def test_missing_folder_is_empty(self):
        self.assertEqual(pl._PendingEvidence(self.folder).rows(["EV-001"]), [])


if __name__ == "__main__":
    unittest.main()
