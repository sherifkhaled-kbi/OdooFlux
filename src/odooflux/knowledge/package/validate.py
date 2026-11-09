"""Reader validation of a package on its staged tree (P04, P06, P07, P09, P11, P12; contracts/knowledge-package-format.md).

`validate_package(archive, staging_root)` runs the streaming reader (P01 to P05, P08), then P12 (internal or
Enterprise-derived release, `package/confidentiality.py`), P07 compatibility, P06
hash and digest verification, P04 release file set, P09 redaction scan, the optional `--expect-digest` check, and
P11 (`knowledge validate` rules on the staged `knowledge/` tree). Any failure discards the staging directory and
raises PackageError. Success returns the staged tree, which the caller either moves into kb-home or discards.
Nothing is installed here.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from odooflux import __version__
from odooflux.knowledge import validator
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.package.archive import MANIFEST_NAME, PackageError, read_package_archive
from odooflux.knowledge.package.builder import SUMS_NAME, sums_text
from odooflux.knowledge.package.compat import check_compat, check_release_format
from odooflux.knowledge.package.confidentiality import assess, declares_enterprise, refusal_text
from odooflux.knowledge.release.canonical import digest_obj
from odooflux.knowledge.release.manifest import MANIFEST_NAME as RELEASE_MANIFEST
from odooflux.knowledge.release.model import release_id_from_digest
from odooflux.utils.redaction import scan_for_shapes

KNOWLEDGE_DIR = "knowledge"
_EXCLUDED_FROM_DIGEST = ("release_id", "release_digest")
_SCHEMA_DIR = KNOWLEDGE_ROOT / "schemas"


@dataclass(frozen=True)
class ValidatedPackage:
    staging_dir: Path
    manifest: dict
    release: dict
    release_id: str
    release_digest: str
    knowledge_root: "Path | None"


def _p06(detail: str, entry=None) -> PackageError:
    return PackageError("P06", detail, entry)


def _schema_problems(data, schema_name: str, where: str) -> None:
    """P07: `data` must satisfy the named schema in knowledge/schemas (stdlib checker, no third-party code)."""
    schema = json.loads((_SCHEMA_DIR / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    problems = validator.check(data, schema)
    if problems:
        pointer, message = problems[0]
        raise PackageError("P07", f"{schema_name} violation at {pointer or '/'}: {message}", where)


def _check_release(staging: Path, manifest: dict) -> dict:
    """P06 release digest recomputed from release.json; P04 release file set; per-file sizes and hashes."""
    try:
        release = json.loads((staging / RELEASE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PackageError("P06", "release.json is missing or unreadable", RELEASE_MANIFEST) from None
    check_release_format(release)
    _schema_problems(release, "release_manifest", RELEASE_MANIFEST)
    body = {k: v for k, v in release.items() if k not in _EXCLUDED_FROM_DIGEST}
    if digest_obj(body) != release.get("release_digest"):
        raise _p06("release_digest does not recompute from release.json", RELEASE_MANIFEST)
    try:
        expected_id = release_id_from_digest(release["release_digest"])
    except (KeyError, ValueError):
        raise _p06("release_digest is not a valid digest", RELEASE_MANIFEST) from None
    if release.get("release_id") != expected_id:
        raise _p06("release_id does not match release_digest", RELEASE_MANIFEST)
    if manifest.get("release_id") != release["release_id"] or manifest.get("release_digest") != release["release_digest"]:
        raise _p06("package.json does not describe the release in release.json", MANIFEST_NAME)

    listed = {entry["path"]: entry for entry in manifest["entries"]}
    release_files = release.get("files")
    if not isinstance(release_files, list):
        raise PackageError("P04", "release.json files is not a list", RELEASE_MANIFEST)
    expected_names = {RELEASE_MANIFEST} | {item.get("path") for item in release_files if isinstance(item, dict)}
    if expected_names != set(listed):
        extra = sorted(set(listed) - expected_names)
        missing = sorted(expected_names - set(listed))
        detail = extra[0] if extra else (missing[0] if missing else "")
        raise PackageError("P04", "package entries differ from release.json file set", detail or None)
    for item in release_files:
        entry = listed[item["path"]]
        if entry["sha256"] != item.get("sha256") or entry["size"] != item.get("size"):
            raise _p06("release file hash or size differs from release.json", item["path"])
    return release


def _check_sums(staging: Path, manifest: dict) -> None:
    try:
        data = (staging / SUMS_NAME).read_bytes()
    except OSError:
        raise PackageError("P04", "integrity/SHA256SUMS is missing", SUMS_NAME) from None
    if data != sums_text(sorted(manifest["entries"], key=lambda e: e["path"].encode("utf-8"))):
        raise _p06("SHA256SUMS does not match the manifest entries", SUMS_NAME)


def _check_redaction(staging: Path, manifest: dict) -> None:
    status = (manifest.get("redaction_scan") or {}).get("status")
    if status != "PASSED":
        raise PackageError("P09", f"redaction scan status is {status!r}", MANIFEST_NAME)
    hits = scan_for_shapes([staging])
    if hits:
        raise PackageError("P09", "credential-shaped string in package content", Path(hits[0][0]).relative_to(staging).as_posix())
    home = str(Path.home())
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        if len(home) >= 4 and home.encode("utf-8") in path.read_bytes():
            raise PackageError("P09", "absolute path in package content", path.relative_to(staging).as_posix())


def _check_knowledge(staging: Path):
    tree = staging / KNOWLEDGE_DIR
    if not tree.is_dir():
        raise PackageError("P11", "knowledge/ tree is missing", KNOWLEDGE_DIR)
    findings = validate_knowledge(load_knowledge(tree))
    errors = [f for f in findings if f.severity == "ERROR"]
    if errors:
        first = errors[0]
        raise PackageError("P11", f"knowledge validation failed: {first.code} in {first.file}", first.file)
    return tree


def check_internal(staging: Path, manifest: dict) -> None:
    """P12 (INTERNAL_RELEASE_REFUSED): an internal or Enterprise-derived release never leaves the machine.

    Runs before any other release check, so an internal release is reported as P12 rather than as a schema failure
    (its `confidentiality` and Enterprise source fields are outside the public schema). A release.json that cannot be
    read as an object is left to P06. The detail carries reason labels and counts only."""
    try:
        release = json.loads((staging / RELEASE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(release, dict):
        return
    reasons = assess(staging)
    if declares_enterprise(manifest):
        reasons.append("package.json declares Enterprise-derived content")
    if reasons:
        raise PackageError("P12", "internal release refused: " + refusal_text(reasons), RELEASE_MANIFEST)


def _validate_staged(staged, running_version, expect_digest) -> ValidatedPackage:
    manifest = staged.manifest
    staging = staged.staging_dir
    check_internal(staging, manifest)
    _schema_problems(manifest, "package_manifest", MANIFEST_NAME)
    check_compat(manifest, running_version)
    computed = {entry.path: entry.sha256 for entry in staged.entries}
    for item in manifest["entries"]:
        if computed.get(item["path"]) != item["sha256"]:
            raise _p06("sha256 does not match the manifest", item["path"])
    release = _check_release(staging, manifest)
    _check_sums(staging, manifest)
    _check_redaction(staging, manifest)
    if expect_digest is not None and expect_digest != release["release_digest"]:
        raise _p06("release digest differs from --expect-digest")
    knowledge_root = _check_knowledge(staging)
    return ValidatedPackage(staging_dir=staging, manifest=manifest, release=release,
                            release_id=release["release_id"], release_digest=release["release_digest"],
                            knowledge_root=knowledge_root)


def validate_package(archive, staging_root, *, running_version: str = None, expect_digest: str = None) -> ValidatedPackage:
    """Validate `archive` into a new staging directory under `staging_root`. Installs nothing.

    On any rejection the staging directory is removed and PackageError (with its P-code) is raised."""
    staged = read_package_archive(archive, staging_root)
    try:
        return _validate_staged(staged, running_version or __version__, expect_digest)
    except BaseException:
        staged.discard()
        raise
