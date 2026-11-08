"""Package entry-name rules (P01) and default limits (research R4, REQ-KAP-023).

`validate_entry_name` is the single P01 check. Names are relative POSIX paths: UTF-8, NFC, no NUL, no backslash,
not absolute, no drive letter, no `.` or `..` segment, no empty segment, bounded length and depth.
"""

import re
import unicodedata

MAX_ENTRIES = 20_000
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_RATIO = 200
MAX_PATH_LEN = 240
MAX_DEPTH = 12

_DRIVE = re.compile(r"^[A-Za-z]:")


class EntryNameError(ValueError):
    """An entry name violates P01. `code` is always `P01`; `name` is the offending value."""

    code = "P01"

    def __init__(self, name, reason: str):
        super().__init__(f"P01: {reason}: {name!r}")
        self.name = name
        self.reason = reason


def validate_entry_name(name: str) -> str:
    """Return `name` unchanged when it is a valid package entry name; raise EntryNameError otherwise."""
    if not isinstance(name, str):
        raise EntryNameError(name, "name is not a string")
    if name == "":
        raise EntryNameError(name, "empty name")
    if "\x00" in name:
        raise EntryNameError(name, "NUL byte")
    try:
        encoded = name.encode("utf-8")
    except UnicodeEncodeError:
        raise EntryNameError(name, "not encodable as UTF-8") from None
    if unicodedata.normalize("NFC", name) != name:
        raise EntryNameError(name, "not NFC")
    if "\\" in name:
        raise EntryNameError(name, "backslash")
    if name.startswith("/"):
        raise EntryNameError(name, "absolute path")
    if _DRIVE.match(name):
        raise EntryNameError(name, "drive letter")
    if len(encoded) > MAX_PATH_LEN:
        raise EntryNameError(name, f"longer than {MAX_PATH_LEN} bytes")
    segments = name.split("/")
    if len(segments) > MAX_DEPTH:
        raise EntryNameError(name, f"deeper than {MAX_DEPTH} segments")
    for segment in segments:
        if segment == "":
            raise EntryNameError(name, "empty segment")
        if segment in (".", ".."):
            raise EntryNameError(name, "dot segment")
    return name


def entry_key(name: str) -> str:
    """Duplicate-detection key: NFC then casefold (P02 treats entries with equal keys as duplicates)."""
    return unicodedata.normalize("NFC", name).casefold()
