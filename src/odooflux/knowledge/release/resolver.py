"""Resolve the knowledge release to use, read-only and fail-closed (REQ-KAP-036, REQ-KAP-005, REQ-KAP-001;
contracts/migration-integration.md "Resolution").

Order: explicit `kb_home`, else `ODOOFLUX_KB_HOME`, else `default_kb_home()` (OD-K1). With no `active.json` the built-in
handle is returned and nothing else happens. With `active.json` the pointed-to release must exist, be loadable
(INSTALLED or ACTIVE), verify against its `release.json`, and match the pointer. Any failure raises
`KnowledgeReleaseError`; there is no fallback to the built-in release.

No directory is created, no lock is taken, no file is written, and there are no network calls.

With no active release the handle carries `builtin_digest()` (the release-style digest of the bytes actually loaded;
see `knowledge/release/builtin.py`), so a migration report can record a release id and digest.

Verification cache (per process only): a fresh process always runs the full `require_intact` content check. Within a
process, a successful verification is reused only while `tree_fingerprint(release_dir)` is unchanged. The fingerprint
is a stat-only hash of (relative path, st_size, st_mtime_ns) over every file in the release directory, including
`release.json`; it reads no file contents. Any added, removed, resized or touched file changes it and forces a full
re-verification. `resolve_knowledge` is the only entry point and computes the fingerprint once per call, never per
rule lookup. Residual risk: a same-size edit whose mtime is restored with `os.utime` to the cached value is not
detected until the process restarts (the fingerprint is stat-only by design). The built-in digest cache has the same
residual risk.
"""

import json
import os
from dataclasses import replace
from pathlib import Path

from odooflux.knowledge.release.builtin import builtin_digest, builtin_handle, clear_digest_cache, tree_fingerprint
from odooflux.knowledge.release.manifest import MANIFEST_NAME, require_intact
from odooflux.knowledge.release.model import LOADABLE_STATES, KnowledgeHandle, KnowledgeReleaseError
from odooflux.knowledge.release.store import read_active, read_release_state

HOME_ENV = "ODOOFLUX_KB_HOME"
_VERIFIED: dict = {}  # (release dir, digest) -> (fingerprint, manifest)


def default_kb_home() -> Path:
    """OD-K1: `$XDG_DATA_HOME/odooflux/kb` (absolute XDG value only), else `~/.local/share/odooflux/kb`; Windows uses
    `%LOCALAPPDATA%\\odooflux\\kb`. Computes a path; creates nothing."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "odooflux" / "kb"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "share"
    return base / "odooflux" / "kb"


def clear_cache() -> None:
    _VERIFIED.clear()
    clear_digest_cache()


def _verified_manifest(release_dir: Path, pointer: dict, fingerprint: str) -> dict:
    key = (str(release_dir), pointer["digest"])
    cached = _VERIFIED.get(key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    require_intact(release_dir)
    try:
        manifest = json.loads((release_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KnowledgeReleaseError(f"{release_dir}: unreadable release manifest ({type(exc).__name__})") from None
    if manifest.get("release_digest") != pointer["digest"] or manifest.get("release_id") != pointer["release_id"]:
        raise KnowledgeReleaseError(f"{release_dir}: active pointer does not match the release manifest")
    _VERIFIED[key] = (fingerprint, manifest)
    return manifest


def resolve_knowledge(kb_home=None, *, require_complete: bool = False) -> KnowledgeHandle:
    if kb_home is None:
        kb_home = os.environ.get(HOME_ENV) or default_kb_home()
    home = Path(kb_home)
    pointer = read_active(home)
    if pointer is None:
        return replace(builtin_handle(), digest=builtin_digest())

    release_dir = home / "releases" / pointer["release_id"]
    if not release_dir.is_dir():
        raise KnowledgeReleaseError(f"active release {pointer['release_id']} is missing from {home}")
    if read_release_state(release_dir) not in LOADABLE_STATES:
        raise KnowledgeReleaseError(f"active release {pointer['release_id']} is not loadable")
    fingerprint = tree_fingerprint(release_dir)  # once per call, stat only; taken before verification
    manifest = _verified_manifest(release_dir, pointer, fingerprint)

    completeness = manifest.get("completeness")
    if require_complete and completeness != "COMPLETE":
        raise KnowledgeReleaseError(f"active release {pointer['release_id']} is {completeness}, not COMPLETE")
    steps = {entry["step"]: entry["completeness"] for entry in manifest.get("steps_covered") or []
             if isinstance(entry, dict) and "step" in entry}
    return KnowledgeHandle(root=release_dir, release_id=pointer["release_id"], digest=pointer["digest"],
                           builtin=False, completeness=completeness, steps=steps)
