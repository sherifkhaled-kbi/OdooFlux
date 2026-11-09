"""Append-only update history: `<kb-home>/updates/history.jsonl` (feature 012, plan section 3).

Each line is one update decision (`NOOP`, `ACTIVE`, `BLOCKED`, ...). Lines are hash-chained like `core/recovery/
audit_log.py`: `entry_hash` is the sha256 of the canonical JSON of the entry without `entry_hash`, and `prev_hash` is
the `entry_hash` of the previous line (64 zeros for the first). Editing, deleting, reordering or inserting a line breaks
the chain at that line and `verify` names it. As with the audit log, the last line has no successor, so truncation of
the final line alone is not detectable from the chain.

Appends run under the kb-home lock (`store.KbLock`), verify the whole chain first and refuse to extend a broken one.
Corrupt content is never skipped: `read` and `append` raise `HistoryError` with a stable `code`.
"""

import contextlib
import hashlib
import json
import os
import re
import time
from pathlib import Path

from odooflux.knowledge.release.canonical import CanonicalError, canonical_bytes
from odooflux.knowledge.release.store import KbLock, KbLockedError, utc_now
from odooflux.utils.redaction import scrub

UPDATES_DIR = "updates"
HISTORY_NAME = "history.jsonl"
GENESIS = "0" * 64
OUTCOMES = ("NOOP", "ACTIVE", "BLOCKED", "FAILED", "ROLLED_BACK", "DRY_RUN", "CHECK")
REQUIRED_KEYS = frozenset({"outcome", "fingerprint", "previous_release", "new_release", "source_revisions", "reason"})
OPTIONAL_KEYS = frozenset({"details"})
META_KEYS = frozenset({"seq", "ts", "prev_hash", "entry_hash"})

# Stable problem codes (HistoryError.code and the codes named by verify()).
INVALID_ARGUMENT = "history.invalid_argument"
INVALID_RECORD = "history.invalid_record"
CORRUPT_LINE = "history.corrupt_line"
TRUNCATED = "history.truncated"
HASH_MISMATCH = "history.hash_mismatch"
SEQ_MISMATCH = "history.seq_mismatch"
CHAIN_BROKEN = "history.chain_broken"
SYMLINK = "history.symlink"
NOT_DIRECTORY = "history.not_directory"
OUTSIDE_HOME = "history.outside_home"
LOCKED = "history.locked"
IO_ERROR = "history.io_error"

_HEX64 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class HistoryError(Exception):
    """The update history cannot be read or extended. `code` is one of the constants above."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _validate_record(record) -> None:
    if not isinstance(record, dict):
        raise HistoryError(INVALID_RECORD, "record must be a dict")
    unknown = set(record) - REQUIRED_KEYS - OPTIONAL_KEYS
    if unknown:
        raise HistoryError(INVALID_RECORD, f"unknown record key(s): {sorted(unknown)}")
    missing = REQUIRED_KEYS - set(record)
    if missing:
        raise HistoryError(INVALID_RECORD, f"missing record key(s): {sorted(missing)}")
    if record["outcome"] not in OUTCOMES:
        raise HistoryError(INVALID_RECORD, f"outcome must be one of {OUTCOMES}")
    fingerprint = record["fingerprint"]
    if fingerprint is not None and not (isinstance(fingerprint, str) and _HEX64.fullmatch(fingerprint)):
        raise HistoryError(INVALID_RECORD, "fingerprint must be None or a sha256 hex string")
    for key in ("previous_release", "new_release"):
        if record[key] is not None and not (isinstance(record[key], str) and record[key]):
            raise HistoryError(INVALID_RECORD, f"{key} must be None or a non-empty string")
    revisions = record["source_revisions"]
    if not isinstance(revisions, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                  for k, v in revisions.items()):
        raise HistoryError(INVALID_RECORD, "source_revisions must map source names to revision strings")
    if record["reason"] is not None and not isinstance(record["reason"], str):
        raise HistoryError(INVALID_RECORD, "reason must be None or a string")
    if "details" in record and not isinstance(record["details"], dict):
        raise HistoryError(INVALID_RECORD, "details must be a dict")
    try:
        canonical_bytes(record)
    except CanonicalError as exc:
        raise HistoryError(INVALID_RECORD, f"record is not canonical JSON: {exc}") from None


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def _check_entry(entry) -> None:
    """Structure of one stored line. Raises HistoryError(INVALID_RECORD) with the reason."""
    if not isinstance(entry, dict):
        raise HistoryError(INVALID_RECORD, "line is not a JSON object")
    if not META_KEYS <= set(entry):
        raise HistoryError(INVALID_RECORD, "line lacks seq/ts/prev_hash/entry_hash")
    seq = entry["seq"]
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise HistoryError(INVALID_RECORD, "seq must be a positive integer")
    if not (isinstance(entry["ts"], str) and _TIMESTAMP.fullmatch(entry["ts"])):
        raise HistoryError(INVALID_RECORD, "ts must be a UTC timestamp")
    for key in ("prev_hash", "entry_hash"):
        if not (isinstance(entry[key], str) and _HEX64.fullmatch(entry[key])):
            raise HistoryError(INVALID_RECORD, f"{key} must be a sha256 hex string")
    _validate_record({k: v for k, v in entry.items() if k not in META_KEYS})


class UpdateHistory:
    """Append-only history under `<home>/updates/`. Construction does not create anything on disk."""

    def __init__(self, home, *, clock=utc_now, lock_timeout: float = 30.0):
        if not isinstance(home, (str, os.PathLike)) or not str(home):
            raise HistoryError(INVALID_ARGUMENT, "home must be a path")
        self.home = Path(home)
        self._clock = clock
        self._lock_timeout = lock_timeout
        self._paths()  # refuse a hostile layout at construction time

    def _paths(self):
        """(updates dir, history file), or HistoryError when either is a symlink or resolves outside home."""
        updates = self.home / UPDATES_DIR
        history = updates / HISTORY_NAME
        if updates.is_symlink() or history.is_symlink():
            raise HistoryError(SYMLINK, f"{updates} is a symlink; refusing to use it")
        if updates.exists():
            if not updates.is_dir():
                raise HistoryError(NOT_DIRECTORY, f"{updates} exists and is not a directory")
            if updates.resolve().parent != self.home.resolve():
                raise HistoryError(OUTSIDE_HOME, f"{updates} resolves outside the kb-home")
        return updates, history

    @contextlib.contextmanager
    def _locked(self):
        """The kb-home lock. Same-process writers (threads) are waited for; a live foreign owner is waited for too,
        up to `lock_timeout` seconds."""
        lock = KbLock(self.home)
        deadline = time.monotonic() + self._lock_timeout
        while True:
            try:
                lock.acquire()
                break
            except KbLockedError:
                if time.monotonic() >= deadline:
                    raise HistoryError(LOCKED, f"kb-home {self.home} stayed locked for {self._lock_timeout}s") \
                        from None
                time.sleep(0.005)
        try:
            yield
        finally:
            lock.release()

    def _scan(self, history: Path):
        """(entries, problems). Each problem is (code, line number, message). Never raises on corrupt content."""
        if not history.exists():
            return [], []
        try:
            raw = history.read_bytes()
        except OSError as exc:
            raise HistoryError(IO_ERROR, f"cannot read {history}: {type(exc).__name__}") from None
        problems, entries = [], []
        if raw == b"":
            lines = []
        elif raw.endswith(b"\n"):
            lines = raw[:-1].split(b"\n")
        else:
            lines = raw.split(b"\n")
            problems.append((TRUNCATED, len(lines), "last line has no terminating newline"))
        previous = GENESIS  # None once a line is unreadable: the link to the next line cannot be checked then
        for number, raw_line in enumerate(lines, 1):
            try:
                entry = json.loads(raw_line.decode("utf-8"))
                _check_entry(entry)
            except (UnicodeDecodeError, ValueError, HistoryError) as exc:
                problems.append((CORRUPT_LINE, number, f"unreadable entry ({exc})"))
                previous = None
                continue
            entries.append(entry)
            recorded = entry["entry_hash"]
            if _entry_hash(entry) != recorded:
                problems.append((HASH_MISMATCH, number, "entry content does not match entry_hash (edited)"))
            if entry["seq"] != number:
                problems.append((SEQ_MISMATCH, number, f"seq {entry['seq']} at position {number} "
                                                       f"(deleted, reordered or inserted line)"))
            if previous is not None and entry["prev_hash"] != previous:
                problems.append((CHAIN_BROKEN, number, "prev_hash does not match the previous entry"))
            # Continue from the recorded hash, so one bad line is reported once, not once per following line.
            previous = recorded
        return entries, problems

    def _checked_entries(self, history: Path) -> list:
        entries, problems = self._scan(history)
        if problems:
            code, number, message = problems[0]
            raise HistoryError(code, f"line {number}: {message}")
        return entries

    def append(self, record: dict, *, secrets=()) -> dict:
        """Validate, redact, chain and durably append one record. Returns the stored entry.

        `secrets` are values to remove from the record before it is written; credential-shaped strings and
        secret-named keys are always masked (see `utils.redaction.scrub`)."""
        _validate_record(record)
        cleaned = {key: scrub(value, secrets) for key, value in record.items()}
        updates, history = self._paths()
        with self._locked():
            entries = self._checked_entries(history)
            entry = dict(cleaned)
            entry.update({"seq": len(entries) + 1, "ts": self._clock(),
                          "prev_hash": entries[-1]["entry_hash"] if entries else GENESIS})
            entry["entry_hash"] = _entry_hash(entry)
            line = canonical_bytes(entry) + b"\n"
            updates.mkdir(exist_ok=True)
            try:
                fd = os.open(history, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o644)
                with os.fdopen(fd, "ab") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                raise HistoryError(IO_ERROR, f"cannot append to {history}: {type(exc).__name__}") from None
        return entry

    def read(self, limit=None) -> list:
        """Verified entries, newest first. `limit` keeps only the newest N. Raises HistoryError on any problem."""
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise HistoryError(INVALID_ARGUMENT, "limit must be None or a non-negative integer")
        _, history = self._paths()
        entries = list(reversed(self._checked_entries(history)))
        return entries if limit is None else entries[:limit]

    def verify(self) -> tuple:
        """``(ok, problems)``. Problems are strings starting with the stable code; never raises on content."""
        _, history = self._paths()
        _, problems = self._scan(history)
        return (not problems, [f"{code} line {number}: {message}" for code, number, message in problems])

    def last_successful(self):
        """Newest ACTIVE entry, or None."""
        for entry in self.read():
            if entry["outcome"] == "ACTIVE":
                return entry
        return None

    def last_fingerprint(self):
        """Fingerprint of the newest ACTIVE or NOOP entry (None when there is none, or when that entry has none)."""
        for entry in self.read():
            if entry["outcome"] in ("ACTIVE", "NOOP"):
                return entry["fingerprint"]
        return None
