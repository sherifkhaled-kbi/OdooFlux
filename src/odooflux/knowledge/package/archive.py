"""Safe package archive reader (contract knowledge-package-format, reader algorithm steps 1 and 2; REQ-KAP-023).

Phase 1 reads the central directory only and applies P01, P02, P03, P05 (declared sizes and ratio), P08 (container
features) and the P04 entry-set check against `package.json`. Phase 2 creates a fresh 0700 staging directory and
streams every entry into it with exclusive creation, enforcing caps while streaming. Any failure removes the staging
directory and raises PackageError. P06 (hash verification), P07, P09, P10 and P11 run on the staged tree in T012.
"""

import hashlib
import json
import os
import shutil
import stat
import uuid
import zlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.package.limits import (
    MAX_ENTRIES,
    MAX_ENTRY_BYTES,
    MAX_RATIO,
    MAX_TOTAL_BYTES,
    EntryNameError,
    entry_key,
    validate_entry_name,
)

CHUNK_BYTES = 64 * 1024
MANIFEST_NAME = "package.json"
# Entries that cannot appear in their own manifest (package.json holds the manifest; SHA256SUMS hashes it).
MANIFEST_EXEMPT = frozenset({MANIFEST_NAME, "integrity/SHA256SUMS"})
_ALLOWED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_ENCRYPTED_FLAG = 0x1


class PackageError(Exception):
    """A package was rejected. `code` is P01..P11, LIMIT_EXCEEDED or ZIP_CORRUPT; `entry` is the offending name."""

    def __init__(self, code: str, detail: str, entry=None):
        self.code = code
        self.detail = detail
        self.entry = entry
        suffix = f" [{entry!r}]" if entry is not None else ""
        super().__init__(f"{code}: {detail}{suffix}")


@dataclass(frozen=True)
class StagedEntry:
    path: str
    size: int
    sha256: str


@dataclass
class StagedPackage:
    """A fully streamed staging tree. The caller either moves `staging_dir` into place or calls `discard()`."""

    staging_dir: Path
    entries: tuple
    manifest: dict

    def discard(self) -> None:
        shutil.rmtree(self.staging_dir, ignore_errors=True)


def _corrupt() -> PackageError:
    """Low-level zip and deflate failures all map to ZIP_CORRUPT."""
    return PackageError("ZIP_CORRUPT", "container data is corrupt or unreadable")


def _preflight(zf: zipfile.ZipFile) -> dict:
    """Header-only checks (P01, P02, P03, P05, P08, MAX_ENTRIES, MAX_TOTAL_BYTES). Returns name -> ZipInfo."""
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise PackageError("LIMIT_EXCEEDED", f"more than {MAX_ENTRIES} entries")
    seen = set()
    by_name = {}
    total = 0
    for info in infos:
        name = info.filename
        if name.endswith("/"):
            raise PackageError("P03", "directory entry is not allowed", name)
        try:
            validate_entry_name(name)
        except EntryNameError as exc:
            raise PackageError("P01", exc.reason, name) from None
        key = entry_key(name)
        if key in seen:
            raise PackageError("P02", "duplicate entry name (case or normalisation)", name)
        seen.add(key)
        mode = info.external_attr >> 16
        if mode and not stat.S_ISREG(mode):
            kind = "symlink" if stat.S_ISLNK(mode) else "non-regular file"
            raise PackageError("P03", f"{kind} is not allowed", name)
        if info.flag_bits & _ENCRYPTED_FLAG:
            raise PackageError("P08", "encrypted entry", name)
        if info.compress_type not in _ALLOWED_METHODS:
            raise PackageError("P08", f"compression method {info.compress_type} not allowed", name)
        if getattr(info, "volume", 0):
            raise PackageError("P08", "multi-disk archive", name)
        if info.file_size > MAX_ENTRY_BYTES:
            raise PackageError("P05", f"declared size {info.file_size} exceeds {MAX_ENTRY_BYTES}", name)
        if info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise PackageError("P05", f"compression ratio above {MAX_RATIO}", name)
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise PackageError("LIMIT_EXCEEDED", f"total declared size above {MAX_TOTAL_BYTES}")
        by_name[name] = info
    return by_name


def _read_capped(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one entry fully into memory, never beyond its declared size (used for package.json only)."""
    chunks = []
    total = 0
    try:
        with zf.open(info) as src:
            while True:
                chunk = src.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > info.file_size:
                    raise PackageError("P05", "streamed bytes exceed declared size", info.filename)
                chunks.append(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
        raise _corrupt() from None
    data = b"".join(chunks)
    if len(data) != info.file_size:
        raise PackageError("P05", "streamed bytes differ from declared size", info.filename)
    return data


def _check_manifest(manifest, by_name: dict) -> None:
    """P04: entries set equals manifest entries exactly; entry_count and total_size match; sizes agree."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("entries"), list):
        raise PackageError("P07", "package.json has no entries list", MANIFEST_NAME)
    listed = {}
    for item in manifest["entries"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("size"), int):
            raise PackageError("P07", "malformed manifest entry", MANIFEST_NAME)
        listed[item["path"]] = item["size"]
    actual = {n: i for n, i in by_name.items() if n not in MANIFEST_EXEMPT}
    for name in sorted(set(actual) - set(listed)):
        raise PackageError("P04", "entry not listed in manifest", name)
    for name in sorted(set(listed) - set(actual)):
        raise PackageError("P04", "manifest lists a missing entry", name)
    for name, size in listed.items():
        if size != actual[name].file_size:
            raise PackageError("P04", "manifest size differs from archive header", name)
    if manifest.get("entry_count") != len(actual):
        raise PackageError("P04", "entry_count does not match the entry set", MANIFEST_NAME)
    if manifest.get("total_size") != sum(i.file_size for i in actual.values()):
        raise PackageError("P04", "total_size does not match the entry set", MANIFEST_NAME)


def _stream_into(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path, budget: list) -> StagedEntry:
    """Stream one entry to `target` with exclusive create, hashing as it writes. `budget[0]` is bytes left."""
    digest = hashlib.sha256()
    total = 0
    try:
        with zf.open(info) as src, open(target, "xb") as dst:
            while True:
                chunk = src.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                budget[0] -= len(chunk)
                if total > info.file_size:
                    raise PackageError("P05", "streamed bytes exceed declared size", info.filename)
                if budget[0] < 0:
                    raise PackageError("LIMIT_EXCEEDED", f"total streamed bytes above {MAX_TOTAL_BYTES}")
                digest.update(chunk)
                dst.write(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
        raise _corrupt() from None
    if total != info.file_size:
        raise PackageError("P05", "streamed bytes differ from declared size", info.filename)
    return StagedEntry(info.filename, total, digest.hexdigest())


def _inside(path: Path, root: Path) -> bool:
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    return os.path.commonpath([real_root, real_path]) == real_root


def read_package_archive(archive_path, staging_root) -> StagedPackage:
    """Validate and stream a package archive into a new staging directory under `staging_root`.

    Raises PackageError on any rejection; the staging directory is removed before the error propagates.
    Hashes are recorded but not compared with the manifest here (P06 runs in T012).
    """
    archive_path = Path(archive_path)
    staging_root = Path(staging_root)
    try:
        zf = zipfile.ZipFile(archive_path)
    except NotImplementedError:
        raise PackageError("P08", "multi-disk archive") from None
    except (zipfile.BadZipFile, OSError, ValueError):
        raise _corrupt() from None
    with zf:
        by_name = _preflight(zf)
        if MANIFEST_NAME not in by_name:
            raise PackageError("P04", "package.json is missing", MANIFEST_NAME)
        raw = _read_capped(zf, by_name[MANIFEST_NAME])
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise PackageError("P07", "package.json is not valid JSON", MANIFEST_NAME) from None
        _check_manifest(manifest, by_name)

        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = staging_root / uuid.uuid4().hex
        os.mkdir(staging_dir, 0o700)
        try:
            budget = [MAX_TOTAL_BYTES]
            staged = []
            for name in sorted(by_name):
                info = by_name[name]
                target = staging_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not _inside(target.parent, staging_dir):
                    raise PackageError("P03", "entry resolves outside staging", name)
                staged.append(_stream_into(zf, info, target, budget))
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
    return StagedPackage(staging_dir=staging_dir, entries=tuple(staged), manifest=manifest)
