"""Release manifest build and verification (REQ-KAP-022, REQ-KAP-024; contracts/release-lifecycle.md).

The manifest lists every file of a release tree (sorted `path`, `sha256`, `size`) except the root-level
`release.json` (the manifest itself) and `state.json` (lifecycle state, outside the digest). The release digest is
sha256 of the canonical JSON of the manifest without `release_id` and `release_digest`; `release_id` is derived
from that digest, so it cannot be part of the digested body.
"""

import hashlib
import json
from pathlib import Path

from odooflux.knowledge.release.canonical import CanonicalError, digest_obj, write_json_file
from odooflux.utils.redaction import scrub
from odooflux.knowledge.release.model import KnowledgeReleaseError, release_id_from_digest

FORMAT = "odooflux.release/1"
MANIFEST_NAME = "release.json"
STATE_NAME = "state.json"
EXCLUDED_ROOT_FILES = frozenset({MANIFEST_NAME, STATE_NAME})
META_FIELDS = frozenset({"label", "parent_release", "framework", "schema_versions", "sources", "steps_covered",
                         "coverage_manifest_digest", "completeness", "build"})
COMPUTED_FIELDS = frozenset({"release_id", "release_digest", "format", "files"})


def _scan(tree_root: Path) -> list:
    """Sorted `{path, sha256, size}` entries for every regular file under `tree_root`, manifest excluded."""
    root = Path(tree_root)
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXCLUDED_ROOT_FILES:
            continue
        if path.is_symlink() or not path.is_file():
            raise KnowledgeReleaseError(f"release tree entry is not a regular file: {rel}")
        data = path.read_bytes()
        entries.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    return sorted(entries, key=lambda entry: entry["path"])


def _digested_body(manifest: dict) -> dict:
    return {k: v for k, v in manifest.items() if k not in ("release_id", "release_digest")}


def build_manifest(tree_root, meta: dict, *, secrets=()) -> dict:
    """Hash every file under `tree_root` and return the complete manifest. Writes nothing.

    `meta` carries the non-computed fields (`META_FIELDS`); computed fields are refused in it. It is scrubbed first
    (REQ-KAP-046): registered `secrets` values and credential-shaped strings are masked, so a secret passed in a label or
    a source entry never reaches `release.json` (the same mechanism the audit log uses). Metadata without secrets is
    unchanged, so existing release digests do not move."""
    meta = scrub(meta, secrets)
    missing = META_FIELDS - set(meta)
    if missing:
        raise KnowledgeReleaseError(f"manifest metadata missing fields: {sorted(missing)}")
    forbidden = COMPUTED_FIELDS & set(meta)
    if forbidden:
        raise KnowledgeReleaseError(f"manifest metadata must not set computed fields: {sorted(forbidden)}")
    body = {"format": FORMAT, "files": _scan(Path(tree_root))}
    body.update({key: meta[key] for key in sorted(META_FIELDS)})
    digest = digest_obj(body)
    return {"release_id": release_id_from_digest(digest), **body, "release_digest": digest}


def write_release_manifest(tree_root, meta: dict, *, secrets=()) -> dict:
    """Build the manifest for `tree_root` and write `release.json` into it (repo JSON convention)."""
    manifest = build_manifest(tree_root, meta, secrets=secrets)
    write_json_file(Path(tree_root) / MANIFEST_NAME, manifest)
    return manifest


def verify_release_tree(tree_root) -> list:
    """Problems found in a release tree against its `release.json`; an empty list means intact."""
    root = Path(tree_root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_NAME} missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{MANIFEST_NAME} unreadable: {type(exc).__name__}"]
    if not isinstance(manifest, dict):
        return [f"{MANIFEST_NAME} is not a JSON object"]

    problems = []
    if manifest.get("format") != FORMAT:
        problems.append(f"{MANIFEST_NAME} format is not {FORMAT}")
    claimed = manifest.get("release_digest")
    try:
        if digest_obj(_digested_body(manifest)) != claimed:
            problems.append("release_digest does not match the manifest contents")
    except (CanonicalError, TypeError) as exc:
        problems.append(f"manifest cannot be digested: {exc}")
    try:
        if manifest.get("release_id") != release_id_from_digest(claimed):
            problems.append("release_id does not match release_digest")
    except ValueError:
        problems.append("release_digest is not a valid digest")

    listed = manifest.get("files")
    if not isinstance(listed, list):
        return problems + ["files is not a list"]
    listed_map = {}
    for entry in listed:
        if not isinstance(entry, dict) or "path" not in entry:
            problems.append("malformed file entry in manifest")
            continue
        listed_map[entry["path"]] = entry

    try:
        actual = {entry["path"]: entry for entry in _scan(root)}
    except KnowledgeReleaseError as exc:
        return problems + [str(exc)]

    for path in sorted(set(listed_map) - set(actual)):
        problems.append(f"missing file listed in manifest: {path}")
    for path in sorted(set(actual) - set(listed_map)):
        problems.append(f"extra file not in manifest: {path}")
    for path in sorted(set(listed_map) & set(actual)):
        want, got = listed_map[path], actual[path]
        if want.get("sha256") != got["sha256"] or want.get("size") != got["size"]:
            problems.append(f"changed file, sha256 or size differs from manifest: {path}")
    return problems


def require_intact(tree_root) -> None:
    """Raise `KnowledgeReleaseError` naming every problem unless the release tree verifies."""
    problems = verify_release_tree(tree_root)
    if problems:
        raise KnowledgeReleaseError("; ".join(problems))
