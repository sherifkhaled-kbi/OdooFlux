"""Canonical JSON and digests for knowledge releases (REQ-KAP-024, REQ-KAP-022).

Single place for digest bytes. Digests use compact, key-sorted UTF-8 JSON. Floats are refused in digested
objects so that no formatting drift can change a digest. Files on disk keep the repo convention
(`indent=2`, `sort_keys`, trailing newline), see `write_json_file`.
"""

import hashlib
import json
from pathlib import Path

from odooflux.utils.atomic import atomic_write_text


class CanonicalError(ValueError):
    """Raised when an object cannot be serialised canonically (floats, non-string keys)."""


def _check(value, where: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        raise CanonicalError(f"float not allowed in digested JSON at {where}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"non-string key {key!r} at {where}")
            _check(item, f"{where}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check(item, f"{where}[{index}]")
        return
    raise CanonicalError(f"unsupported type {type(value).__name__} at {where}")


def canonical_bytes(obj) -> bytes:
    """Compact, key-sorted UTF-8 JSON. Same logical object gives the same bytes regardless of key order."""
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_obj(obj) -> str:
    """sha256 hex of `canonical_bytes(obj)`."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def write_json_file(path, obj) -> None:
    """Write `obj` with the repo file convention (indent=2, sort_keys, trailing newline) atomically.

    Floats are refused before anything is written."""
    _check(obj)
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    atomic_write_text(Path(path), text)
