"""TST-012-T03 (feature 012, plan section 3): the update history is an append-only hash chain. Appends are validated,
redacted, serialised under the kb-home lock and refuse to extend a broken chain; tampering is detected and named."""

import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from odooflux.knowledge.update.history import (CHAIN_BROKEN, CORRUPT_LINE, GENESIS, HASH_MISMATCH, HISTORY_NAME,
                                               SEQ_MISMATCH, SYMLINK, TRUNCATED, UPDATES_DIR, HistoryError,
                                               UpdateHistory)

FP1 = "1" * 64
FP2 = "2" * 64


def _record(outcome="NOOP", fingerprint=FP1, reason=None, **extra):
    record = {"outcome": outcome, "fingerprint": fingerprint, "previous_release": None, "new_release": None,
              "source_revisions": {"odoo-16.0": "a" * 40}, "reason": reason}
    record.update(extra)
    return record


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="kap-history-")
        self.home = Path(self._tmp) / "kb-home"
        self.home.mkdir()
        self.path = self.home / UPDATES_DIR / HISTORY_NAME

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def history(self):
        return UpdateHistory(self.home)

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def write_lines(self, lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class AppendReadTests(HistoryTestCase):
    def test_append_stores_chain_fields(self):
        history = self.history()
        first = history.append(_record())
        second = history.append(_record(outcome="ACTIVE", fingerprint=FP2))
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        self.assertEqual(first["prev_hash"], GENESIS)
        self.assertEqual(second["prev_hash"], first["entry_hash"])
        self.assertRegex(first["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(len(self.lines()), 2)

    def test_read_is_newest_first_and_limit_keeps_newest(self):
        history = self.history()
        for n in range(1, 4):
            history.append(_record(reason=f"run {n}"))
        self.assertEqual([e["seq"] for e in history.read()], [3, 2, 1])
        self.assertEqual([e["reason"] for e in history.read(limit=2)], ["run 3", "run 2"])
        self.assertEqual(history.read(limit=0), [])

    def test_read_on_empty_home_is_empty_and_verifies(self):
        history = self.history()
        self.assertEqual(history.read(), [])
        self.assertEqual(history.verify(), (True, []))
        self.assertFalse((self.home / UPDATES_DIR).exists())  # construction and reads create nothing

    def test_history_survives_reopen(self):
        self.history().append(_record(outcome="ACTIVE"))
        self.assertEqual(self.history().read()[0]["outcome"], "ACTIVE")
        self.assertEqual(self.history().append(_record())["seq"], 2)

    def test_bad_limit_rejected(self):
        for bad in (-1, "2", True):
            with self.subTest(limit=bad), self.assertRaises(HistoryError):
                self.history().read(limit=bad)


class ValidationTests(HistoryTestCase):
    def assertRejected(self, record):
        with self.assertRaises(HistoryError) as ctx:
            self.history().append(record)
        self.assertEqual(ctx.exception.code, "history.invalid_record")
        self.assertFalse(self.path.exists())

    def test_invalid_outcome_rejected(self):
        self.assertRejected(_record(outcome="SUCCESS"))
        self.assertRejected(_record(outcome=None))

    def test_unknown_key_rejected(self):
        self.assertRejected(_record(extra_field=1))

    def test_chain_fields_cannot_be_supplied_by_caller(self):
        for key in ("seq", "ts", "prev_hash", "entry_hash"):
            with self.subTest(key=key):
                self.assertRejected(_record(**{key: "x"}))

    def test_missing_required_key_rejected(self):
        record = _record()
        del record["reason"]
        self.assertRejected(record)

    def test_fingerprint_must_be_none_or_sha256_hex(self):
        self.assertRejected(_record(fingerprint="abc"))
        self.assertRejected(_record(fingerprint=5))
        self.history().append(_record(fingerprint=None, outcome="BLOCKED"))  # None is allowed

    def test_types_of_other_fields_checked(self):
        self.assertRejected(_record(source_revisions=["x"]))
        self.assertRejected(_record(source_revisions={"odoo-16.0": 1}))
        self.assertRejected(_record(previous_release=""))
        self.assertRejected(_record(reason=3))
        self.assertRejected(_record(details=["not", "dict"]))
        self.assertRejected(_record(details={"ratio": 0.5}))

    def test_details_dict_accepted(self):
        entry = self.history().append(_record(details={"sources": 2, "note": "ok"}))
        self.assertEqual(entry["details"], {"sources": 2, "note": "ok"})


class TamperTests(HistoryTestCase):
    def build_three(self):
        history = self.history()
        for n in range(1, 4):
            history.append(_record(reason=f"run {n}"))
        return history

    def test_intact_chain_verifies(self):
        self.assertEqual(self.build_three().verify(), (True, []))

    def test_edited_line_is_detected(self):
        self.build_three()
        lines = self.lines()
        lines[1] = lines[1].replace("run 2", "run X")
        self.write_lines(lines)
        ok, problems = self.history().verify()
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith(HASH_MISMATCH) and "line 2" in p for p in problems), problems)
        self.assertEqual(len(problems), 1, problems)  # the next line still links to the recorded hash
        with self.assertRaises(HistoryError) as ctx:
            self.history().read()
        self.assertEqual(ctx.exception.code, HASH_MISMATCH)

    def test_deleted_middle_line_is_detected(self):
        self.build_three()
        lines = self.lines()
        del lines[1]
        self.write_lines(lines)
        ok, problems = self.history().verify()
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith(SEQ_MISMATCH) for p in problems), problems)
        self.assertTrue(any(p.startswith(CHAIN_BROKEN) for p in problems), problems)

    def test_reordered_lines_are_detected(self):
        self.build_three()
        lines = self.lines()
        lines[0], lines[1] = lines[1], lines[0]
        self.write_lines(lines)
        ok, problems = self.history().verify()
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith(SEQ_MISMATCH) for p in problems), problems)

    def test_corrupt_line_raises_stable_code_and_is_not_skipped(self):
        self.build_three()
        lines = self.lines()
        lines[1] = "{not json"
        self.write_lines(lines)
        ok, problems = self.history().verify()
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith(CORRUPT_LINE) for p in problems), problems)
        with self.assertRaises(HistoryError) as ctx:
            self.history().read()
        self.assertEqual(ctx.exception.code, CORRUPT_LINE)

    def test_partial_last_line_is_truncated(self):
        self.build_three()
        self.path.write_bytes(self.path.read_bytes()[:-20])
        ok, problems = self.history().verify()
        self.assertFalse(ok)
        self.assertTrue(any(p.startswith(TRUNCATED) for p in problems) or
                        any(p.startswith(CORRUPT_LINE) for p in problems), problems)


class BrokenChainAppendTests(HistoryTestCase):
    def test_append_refuses_to_extend_a_broken_chain(self):
        history = self.history()
        history.append(_record(reason="one"))
        history.append(_record(reason="two"))
        lines = self.lines()
        lines[0] = lines[0].replace('"one"', '"ONE"')
        self.write_lines(lines)
        before = self.path.read_bytes()
        with self.assertRaises(HistoryError) as ctx:
            self.history().append(_record(reason="three"))
        self.assertEqual(ctx.exception.code, HASH_MISMATCH)
        self.assertEqual(self.path.read_bytes(), before)  # nothing appended

    def test_append_refuses_corrupt_line(self):
        self.history().append(_record())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("garbage\n")
        with self.assertRaises(HistoryError) as ctx:
            self.history().append(_record())
        self.assertEqual(ctx.exception.code, CORRUPT_LINE)

    def test_append_refuses_partial_line_without_newline(self):
        self.history().append(_record())
        with self.path.open("ab") as fh:
            fh.write(b'{"seq": 2, "ts"')
        with self.assertRaises(HistoryError):
            self.history().append(_record())


class ConcurrencyTests(HistoryTestCase):
    def test_concurrent_appends_from_two_threads_form_a_valid_chain(self):
        per_thread = 15
        errors = []

        def writer(tag):
            history = self.history()  # one instance per thread, same kb-home
            try:
                for n in range(per_thread):
                    history.append(_record(reason=f"{tag}-{n}"))
            except Exception as exc:  # collected and asserted below
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(tag,)) for tag in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        ok, problems = self.history().verify()
        self.assertEqual((ok, problems), (True, []))
        entries = self.history().read()
        seqs = sorted(e["seq"] for e in entries)
        self.assertEqual(seqs, list(range(1, 2 * per_thread + 1)))
        self.assertEqual(len({e["entry_hash"] for e in entries}), 2 * per_thread)
        self.assertFalse((self.home / ".lock").exists())  # the lock is released


class LastSemanticsTests(HistoryTestCase):
    def test_last_successful_and_last_fingerprint_on_empty_history(self):
        history = self.history()
        self.assertIsNone(history.last_successful())
        self.assertIsNone(history.last_fingerprint())

    def test_last_successful_only_counts_active(self):
        history = self.history()
        history.append(_record(outcome="ACTIVE", fingerprint=FP1, reason="first"))
        history.append(_record(outcome="NOOP", fingerprint=FP2))
        history.append(_record(outcome="FAILED", fingerprint="3" * 64))
        self.assertEqual(history.last_successful()["reason"], "first")

    def test_last_successful_none_without_active(self):
        history = self.history()
        history.append(_record(outcome="NOOP"))
        history.append(_record(outcome="BLOCKED"))
        self.assertIsNone(history.last_successful())

    def test_last_fingerprint_counts_active_and_noop_only(self):
        history = self.history()
        history.append(_record(outcome="ACTIVE", fingerprint=FP1))
        history.append(_record(outcome="NOOP", fingerprint=FP2))
        history.append(_record(outcome="DRY_RUN", fingerprint="3" * 64))
        history.append(_record(outcome="FAILED", fingerprint="4" * 64))
        self.assertEqual(history.last_fingerprint(), FP2)

    def test_last_fingerprint_none_when_only_non_terminal_outcomes(self):
        history = self.history()
        history.append(_record(outcome="BLOCKED", fingerprint=FP1))
        self.assertIsNone(history.last_fingerprint())


class SymlinkTests(HistoryTestCase):
    def test_symlinked_updates_dir_is_rejected(self):
        outside = Path(self._tmp) / "elsewhere"
        outside.mkdir()
        (self.home / UPDATES_DIR).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HistoryError) as ctx:
            self.history()
        self.assertEqual(ctx.exception.code, SYMLINK)
        self.assertEqual(list(outside.iterdir()), [])  # nothing written through the link

    def test_symlinked_history_file_is_rejected(self):
        updates = self.home / UPDATES_DIR
        updates.mkdir()
        target = Path(self._tmp) / "target.jsonl"
        target.write_text("", encoding="utf-8")
        self.path.symlink_to(target)
        with self.assertRaises(HistoryError) as ctx:
            self.history().append(_record())
        self.assertEqual(ctx.exception.code, SYMLINK)
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_verify_reports_symlink_as_problem(self):
        outside = Path(self._tmp) / "elsewhere"
        outside.mkdir()
        (self.home / UPDATES_DIR).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(HistoryError):
            self.history().verify()


class RedactionTests(HistoryTestCase):
    def test_secret_values_and_credential_shapes_never_reach_the_file(self):
        secret = "hunter2-very-secret"
        history = self.history()
        history.append(_record(reason=f"fetch failed for {secret} via sk-abcdefghijklmnop1234",
                               details={"api_key": "raw-key-value-123", "note": f"see {secret}",
                                        "url": "https://user:pass-word-123@example.com/repo"}),
                       secrets=[secret])
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn(secret, text)
        self.assertNotIn("sk-abcdefghijklmnop1234", text)
        self.assertNotIn("raw-key-value-123", text)
        self.assertNotIn("pass-word-123", text)
        entry = self.history().read()[0]
        self.assertEqual(entry["details"]["api_key"], "***")
        self.assertIn("***", entry["reason"])

    def test_redacted_record_still_verifies(self):
        self.history().append(_record(reason="token leak"), secrets=["never-written-value"])
        self.assertEqual(self.history().verify(), (True, []))


class LockTests(HistoryTestCase):
    def test_busy_lock_times_out_with_stable_code(self):
        self.home.mkdir(exist_ok=True)
        (self.home / ".lock").write_text("1\n", encoding="utf-8")  # PID 1 is alive: a foreign live owner
        history = UpdateHistory(self.home, lock_timeout=0.05)
        with self.assertRaises(HistoryError) as ctx:
            history.append(_record())
        self.assertEqual(ctx.exception.code, "history.locked")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
