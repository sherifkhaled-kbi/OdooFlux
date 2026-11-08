"""Built-in release descriptor and identity (REQ-KAP-036, REQ-KAP-005; contracts/migration-integration.md "Resolution").

The built-in release is the knowledge tree shipped in the package (`KNOWLEDGE_ROOT`). It has no `release.json`, so its
identity is `builtin_digest()`: a release-style content digest over every file of the tree except `__pycache__` and
`*.pyc`. It uses the per-file hash and digest function of `knowledge/release/manifest.py` (`_scan`, `digest_obj`,
`FORMAT`), so it is independent of mtime, umask and path. `_scan` also skips root-level `release.json` and
`state.json`; the shipped knowledge tree contains neither.

The digest is computed from the bytes actually loaded. There is no shipped reference digest to compare against; the
wheel hash is the integrity anchor. Residual risk: the digest records what is on disk when it is computed, so a tree
altered before the process starts is digested as altered.

Caching: `builtin_digest` is computed once per process and cached per tree. The cache entry is keyed by
`tree_fingerprint`, a stat-only hash of (relative path, st_size, st_mtime_ns) of the tree, so a changed tree is
re-digested. The fingerprint does not read file contents; a same-size edit whose mtime is restored is not detected
(the same residual risk as the release resolver cache).

Nothing in this module writes to the filesystem, creates directories, or makes network calls.
"""

import os
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.release.manifest import FORMAT, _scan
from odooflux.knowledge.release.model import BUILTIN_RELEASE_ID, builtin_handle

__all__ = ["BUILTIN_RELEASE_ID", "builtin_descriptor", "builtin_digest", "builtin_handle", "clear_digest_cache",
           "tree_fingerprint"]

_DIGEST_CACHE: dict = {}


def _ignored(rel: str) -> bool:
    return "__pycache__" in rel.split("/") or rel.endswith(".pyc")


def tree_fingerprint(root, ignore=None) -> str:
    """sha256 over the sorted (relative path, st_size, st_mtime_ns) of every file under `root`, `ignore(rel)` excluded.

    Stat only: no file is opened or read. Symlinks are stat'ed with lstat and not followed."""
    base = Path(root)
    rows = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = Path(full).relative_to(base).as_posix()
            if ignore is not None and ignore(rel):
                continue
            st = os.lstat(full)
            rows.append([rel, st.st_size, st.st_mtime_ns])
    rows.sort()
    return digest_obj(rows)


def builtin_digest(root=KNOWLEDGE_ROOT) -> str:
    """Release-style digest of the built-in knowledge tree as loaded, cached per process (see module docstring)."""
    base = Path(root)
    key = str(base)
    fingerprint = tree_fingerprint(base, ignore=_ignored)
    cached = _DIGEST_CACHE.get(key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    entries = [entry for entry in _scan(base) if not _ignored(entry["path"])]
    digest = digest_obj({"format": FORMAT, "files": entries})
    _DIGEST_CACHE[key] = (fingerprint, digest)
    return digest


def clear_digest_cache() -> None:
    _DIGEST_CACHE.clear()


def builtin_descriptor(root=KNOWLEDGE_ROOT) -> dict:
    return {"release_id": BUILTIN_RELEASE_ID, "root": str(Path(root)), "builtin": True, "digest": None,
            "completeness": None}
