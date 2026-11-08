"""Test-archive generator for TST-011-010 (REQ-KAP-023). Not a test module (leading underscore).

Builds valid and malicious knowledge-package ZIP files with stdlib zipfile only. Header-level lies are produced by
patching the central directory after writing, so they are deterministic.
"""

import hashlib
import json
import stat
import struct
import warnings
import zipfile
from pathlib import Path

FORMAT = "odooflux.package/1"
EXEMPT = ("package.json", "integrity/SHA256SUMS")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_files() -> dict:
    """Data entries of a minimal valid package (everything except package.json and SHA256SUMS)."""
    return {
        "release.json": b'{"release_id": "kr-test"}\n',
        "knowledge/evidence/EV-001.json": b'{"id": "EV-001"}\n',
        "coverage/coverage-manifest.json": b'{"items": []}\n',
        "provenance/sources.json": b'{"sources": []}\n',
    }


def make_package_json(files: dict, *, entry_count=None, total_size=None) -> bytes:
    entries = [{"path": p, "sha256": sha256_hex(d), "size": len(d)} for p, d in sorted(files.items())]
    doc = {
        "format": FORMAT,
        "release_id": "kr-test",
        "release_digest": "0" * 64,
        "created_with": "odooflux test",
        "compat": {"min_framework": "0.0.0", "max_framework": None, "schemas": {}},
        "entries": entries,
        "entry_count": len(entries) if entry_count is None else entry_count,
        "total_size": sum(len(d) for d in files.values()) if total_size is None else total_size,
        "contains_enterprise_derived": False,
        "redaction_scan": {"status": "PASSED", "scanner_version": "1"},
    }
    return json.dumps(doc, sort_keys=True).encode("utf-8")


def valid_entries(files: dict = None) -> list:
    """(name, data) list for a valid package whose manifest describes exactly `files`."""
    files = base_files() if files is None else files
    return [
        ("package.json", make_package_json(files)),
        ("integrity/SHA256SUMS", b""),
        *sorted(files.items()),
    ]


def write_zip(path, entries) -> Path:
    """Write `entries` in order. Each item is (name, data) or (name, data, opts) with opts keys:
    mode (unix mode for external_attr), method (zipfile compress type), flags (flag_bits OR-ed in)."""
    path = Path(path)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # duplicate names are written on purpose
        with zipfile.ZipFile(path, "w") as zf:
            for item in entries:
                name, data = item[0], item[1]
                opts = item[2] if len(item) > 2 else {}
                info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
                info.compress_type = opts.get("method", zipfile.ZIP_DEFLATED)
                mode = opts.get("mode", stat.S_IFREG | 0o644)
                info.external_attr = (mode & 0xFFFF) << 16
                zf.writestr(info, data)
    flagged = [(item[0], item[2]["flags"]) for item in entries if len(item) > 2 and "flags" in item[2]]
    for name, flags in flagged:
        patch_central_flags(path, name, flags)
    return path


def _central_records(data: bytearray):
    """Yield (offset, name) for every central-directory record, in order."""
    eocd = data.rfind(b"PK\x05\x06")
    pos = struct.unpack_from("<I", data, eocd + 16)[0]
    count = struct.unpack_from("<H", data, eocd + 10)[0]
    for _ in range(count):
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, pos + 28)
        name = bytes(data[pos + 46 : pos + 46 + name_len]).decode("utf-8")
        yield pos, name
        pos += 46 + name_len + extra_len + comment_len


def patch_central_file_size(path, name: str, new_size: int) -> None:
    """Overwrite the declared uncompressed size of `name` in the central directory only (header lie)."""
    path = Path(path)
    data = bytearray(path.read_bytes())
    for pos, rec_name in _central_records(data):
        if rec_name == name:
            struct.pack_into("<I", data, pos + 24, new_size)
            path.write_bytes(bytes(data))
            return
    raise AssertionError(f"no central record for {name!r}")


def patch_central_flags(path, name: str, flags: int) -> None:
    """Set general-purpose flag bits of `name` in the central directory (zipfile resets them on write)."""
    path = Path(path)
    data = bytearray(path.read_bytes())
    for pos, rec_name in _central_records(data):
        if rec_name == name:
            struct.pack_into("<H", data, pos + 8, flags)
            path.write_bytes(bytes(data))
            return
    raise AssertionError(f"no central record for {name!r}")


def flip_stored_byte(path, name: str) -> None:
    """Corrupt one payload byte of a STORED entry so its CRC fails during streaming."""
    path = Path(path)
    data = bytearray(path.read_bytes())
    for pos, rec_name in _central_records(data):
        if rec_name == name:
            local = struct.unpack_from("<I", data, pos + 42)[0]
            name_len, extra_len = struct.unpack_from("<HH", data, local + 26)
            payload = local + 30 + name_len + extra_len
            data[payload] ^= 0xFF
            path.write_bytes(bytes(data))
            return
    raise AssertionError(f"no central record for {name!r}")
