"""Snapshot builder (REQ-KAP-010, REQ-KAP-013; source-adapter contract rules 6, 7, 8).

Walks a source tree without following symlinks, stores every in-scope file in the blob store and returns a
SourceSnapshot dict (`schemas/snapshot.schema.json`). Nothing is dropped silently: out-of-scope files, symlinks and
non-UTF-8 names are listed in `limits.excluded` with a reason. Entries are sorted, so the same tree gives the same
`snapshot_digest` (sha256 of canonical JSON over `source_id`, `revision` and `entries`).
"""

import fnmatch
import os
from datetime import datetime, timezone
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.release.canonical import digest_obj


def _rel_text(parts: str) -> str:
    """Printable form of a relative path. Undecodable bytes are shown with backslash escapes."""
    return parts.encode("utf-8", "backslashreplace").decode("utf-8")


def _is_utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _kind(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    padded = "/" + rel
    if name == "__manifest__.py":
        return "manifest"
    if name.endswith(".py") and "/migrations/" in padded:
        return "migration"
    if "/security/" in padded and name.endswith(".csv"):
        return "security"
    suffix = name.rsplit(".", 1)[-1] if "." in name else ""
    return {"py": "python", "xml": "xml", "js": "js", "rst": "docs", "csv": "csv"}.get(suffix, "other")


def _excluded_by_scope(rel: str, rules: list):
    for rule in rules:
        if fnmatch.fnmatchcase(rel, rule["pattern"]):
            return rule["reason"]
    return None


def build_snapshot(root, source_id: str, revision: str, store: BlobStore, *, scope_exclude=(),
                   created_at=None) -> dict:
    """Snapshot of the directory tree at *root*. `scope_exclude` is a list of `{pattern, reason}` (fnmatch on the
    relative POSIX path). `created_at` is not digested; default is the current UTC time."""
    root = Path(root)
    if not root.is_dir():
        raise SourceError("IO_ERROR", source_id, f"{root} is not a directory")
    rules = list(scope_exclude)
    entries: list = []
    excluded: list = []

    def skip(rel_text: str, reason: str) -> None:
        excluded.append({"path": _rel_text(rel_text), "reason": reason})

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = os.path.relpath(dirpath, root)
        base = "" if base == "." else base.replace(os.sep, "/") + "/"
        for name in sorted(dirnames):
            full = Path(dirpath) / name
            rel = base + name
            if not _is_utf8(rel):
                skip(rel, "NON_UTF8_NAME")
            elif full.is_symlink():
                skip(rel, _symlink_reason(full, root))
            else:
                continue
            dirnames.remove(name)  # never descend into excluded directories
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = base + name
            if not _is_utf8(rel):
                skip(rel, "NON_UTF8_NAME")
                continue
            if full.is_symlink():
                skip(rel, _symlink_reason(full, root))
                continue
            reason = _excluded_by_scope(rel, rules)
            if reason is not None:
                skip(rel, reason)
                continue
            data = full.read_bytes()
            entries.append({"path": rel, "sha256": store.put(data), "size": len(data), "kind": _kind(rel)})

    entries.sort(key=lambda e: e["path"])
    excluded.sort(key=lambda e: e["path"])
    digest = digest_obj({"source_id": source_id, "revision": revision, "entries": entries})
    if created_at is None:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "snapshot_id": "ss-" + digest[:12],
        "source_id": source_id,
        "revision": revision,
        "entries": entries,
        "snapshot_digest": digest,
        "created_at": created_at,
        "limits": {"excluded": excluded},
    }


def _symlink_reason(link: Path, root: Path) -> str:
    try:
        target = link.resolve(strict=False)
        target.relative_to(root.resolve())
        return "SYMLINK"  # points inside the tree; still not followed, so not snapshotted
    except (ValueError, OSError):
        return "SYMLINK_ESCAPE"
