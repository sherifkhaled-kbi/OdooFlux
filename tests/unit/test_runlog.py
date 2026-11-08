"""TST-003-014 (REQ-SAF-006): fsync per entry; reader accepts schema /0 and /1; truncated tail ignored."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.core.recovery.runlog import RunLog, read_runlog

from ._setup import SRC  # noqa: F401


class RunLogTests(unittest.TestCase):
    def test_append_fsyncs_each_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = RunLog(Path(tmp) / "log" / "run_log.jsonl", "run-1", reversible=True)
            with mock.patch("os.fsync") as fsync:
                log.append("file_written", path="a")
                log.append("file_written", path="b")
            self.assertEqual(fsync.call_count, 2)
            entries, warnings = read_runlog(log.path)
            self.assertEqual([e["path"] for e in entries], ["a", "b"])
            self.assertEqual(entries[0]["schema"], "odooflux.runlog/1")
            self.assertEqual(warnings, [])

    def test_reader_accepts_p0_schema_and_ignores_truncated_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_log.jsonl"
            path.write_text(
                json.dumps({"schema": "odooflux.runlog/0", "event": "file_written", "path": "old"}) + "\n"
                + json.dumps({"schema": "odooflux.runlog/1", "event": "file_written", "path": "new"}) + "\n"
                + '{"schema": "odooflux.runlog/1", "event": "fil', encoding="utf-8")
            entries, warnings = read_runlog(path)
            self.assertEqual([e["path"] for e in entries], ["old", "new"])
            self.assertEqual(len(warnings), 1)

    def test_unknown_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_log.jsonl"
            path.write_text(json.dumps({"schema": "other/9", "event": "x"}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_runlog(path)


if __name__ == "__main__":
    unittest.main()
