"""Deterministic `.ofkp` package builder (REQ-KAP-022, REQ-KAP-024, REQ-KAP-028; contracts/knowledge-package-format.md
"Writer (export)").

`export_package(release_dir, out)` packs a complete release tree (its `release.json` plus every file except the
lifecycle `state.json`) into a ZIP with fixed ZipInfo fields, sorted entries, and `package.json` and
`integrity/SHA256SUMS` generated from the same entry list. The bytes depend only on the release contents, never on
mtimes, the umask, or the directory the release lives in. Before anything is written the release tree is verified
against its manifest, and every included file is scanned for planted canaries, credential shapes, and absolute
paths (redaction scan, `utils/redaction.py`). The written file is re-read with the safe reader as a self-check.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from odooflux import __version__
from odooflux.knowledge.package.archive import MANIFEST_NAME, PackageError, read_package_archive
from odooflux.knowledge.release.manifest import MANIFEST_NAME as RELEASE_MANIFEST, STATE_NAME, require_intact
from odooflux.utils.redaction import scan_for_canaries, scan_for_shapes

PACKAGE_FORMAT = "odooflux.package/1"
SUMS_NAME = "integrity/SHA256SUMS"
SCANNER_VERSION = "1"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (stat.S_IFREG | 0o644) << 16
FORBIDDEN_PREFIXES = ("staging/", "snapshots/")
# Only snapshot MANIFESTS (metadata: file list and hashes, written by release/provenance.py) may ship, never blobs or other
# content under snapshots/ (source content can be licensed). Staging is never exported.
SNAPSHOT_MANIFEST_RE = re.compile(r"^snapshots/ss-[0-9a-f]{12}\.json$")


def is_forbidden_entry(rel: str) -> bool:
    return rel.startswith(FORBIDDEN_PREFIXES) and not SNAPSHOT_MANIFEST_RE.match(rel)


@dataclass(frozen=True)
class PackageInfo:
    path: Path
    release_id: str
    release_digest: str
    sha256: str
    entry_count: int
    total_size: int
    contains_enterprise_derived: bool


def _release_files(release_dir: Path) -> list:
    """Relative POSIX names of every release file that goes into the package (state.json excluded)."""
    names = []
    for path in release_dir.rglob("*"):
        if path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            raise PackageError("P03", "release tree contains a non-regular file", path.name)
        rel = path.relative_to(release_dir).as_posix()
        if rel == STATE_NAME:
            continue
        if is_forbidden_entry(rel):
            raise PackageError("EXPORT_REFUSED", "snapshots and staging are never exported", rel)
        names.append(rel)
    return sorted(names, key=lambda n: n.encode("utf-8"))


def _scan_entry(path: Path, rel: str, release_dir: Path, canaries) -> None:
    """Redaction scan of one included file (REQ-KAP-028): canaries, credential shapes, absolute paths."""
    if canaries and scan_for_canaries([path], canaries):
        raise PackageError("P09", "planted secret canary found in entry", rel)
    if scan_for_shapes([path]):
        raise PackageError("P09", "credential-shaped string found in entry", rel)
    data = path.read_bytes()
    needles = {str(release_dir.resolve()), str(Path.home())}
    for needle in needles:
        if len(needle) >= 4 and needle.encode("utf-8") in data:
            raise PackageError("P09", "absolute path found in entry", rel)


def sums_text(entries: list) -> bytes:
    return "".join(f"{e['sha256']}  {e['path']}\n" for e in entries).encode("utf-8")


def _zip_bytes_to(path: Path, members: list) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = FILE_ATTR
            zf.writestr(info, data)


def export_package(release_dir, out_path, *, include_enterprise_derived: bool = False, canaries=()) -> PackageInfo:
    """Write the deterministic package for `release_dir` to `out_path` (replaced atomically).

    Raises KnowledgeReleaseError if the release tree does not verify, PackageError (P09, EXPORT_REFUSED, P03) if
    content is refused. Nothing is written on refusal."""
    release_dir = Path(release_dir)
    out_path = Path(out_path)
    require_intact(release_dir)
    release = json.loads((release_dir / RELEASE_MANIFEST).read_text(encoding="utf-8"))

    enterprise = any(isinstance(s, dict) and s.get("enterprise_derived") is True for s in release.get("sources", []))
    if enterprise and not include_enterprise_derived:
        raise PackageError("EXPORT_REFUSED", "release contains Enterprise-derived records; not exported by default")

    names = [RELEASE_MANIFEST] + _release_files(release_dir)
    members = {}
    for rel in names:
        data = (release_dir / rel).read_bytes()
        _scan_entry(release_dir / rel, rel, release_dir, canaries)
        members[rel] = data
    entries = [{"path": rel, "sha256": hashlib.sha256(members[rel]).hexdigest(), "size": len(members[rel])}
               for rel in sorted(members, key=lambda n: n.encode("utf-8"))]
    total = sum(e["size"] for e in entries)
    framework = release["framework"]
    package = {
        "format": PACKAGE_FORMAT,
        "release_id": release["release_id"],
        "release_digest": release["release_digest"],
        "created_with": f"odooflux {__version__}",
        "compat": {"min_framework": framework["min_framework"], "max_framework": framework["max_framework"],
                   "schemas": release["schema_versions"]},
        "entries": entries,
        "entry_count": len(entries),
        "total_size": total,
        "contains_enterprise_derived": enterprise,
        "redaction_scan": {"status": "PASSED", "scanner_version": SCANNER_VERSION},
    }
    package_bytes = (json.dumps(package, indent=2, sort_keys=True) + "\n").encode("utf-8")
    all_members = [(MANIFEST_NAME, package_bytes), (SUMS_NAME, sums_text(entries))]
    all_members += [(e["path"], members[e["path"]]) for e in entries]
    all_members.sort(key=lambda item: item[0].encode("utf-8"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _zip_bytes_to(tmp, all_members)
        with tempfile.TemporaryDirectory() as scratch:
            read_package_archive(tmp, scratch).discard()  # self-check with the safe reader
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return PackageInfo(path=out_path, release_id=release["release_id"], release_digest=release["release_digest"],
                       sha256=digest, entry_count=len(entries), total_size=total,
                       contains_enterprise_derived=enterprise)
