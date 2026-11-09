"""Package importer: stage, verify, gate, atomic move, optional activate (REQ-KAP-025, REQ-KAP-026, REQ-KAP-027;
contracts/knowledge-package-format.md "Reader algorithm" and P10, contracts/release-lifecycle.md "Activation").

Order: P12 first, on a scratch read outside kb-home (an internal or Enterprise-derived package is refused before
anything is staged). Then validate into `<kb-home>/staging/` (P01 to P09, P11), then P10: every FIX_ENABLED rule in the package is
re-gated locally with `release/safety.py` (built-in-origin rules included, because a package is never trusted). A
failing rule is refused by default. With `downgrade_unverified` it is capped to DETECT_ONLY in the staged tree and the
release manifest is recomputed, so the installed release digest describes the bytes that are installed.

The import holds the kb-home lock for its whole run. The release directory is published with one `os.replace` from
staging; activation is one atomic `active.json` write. Any failure before the audit record is complete removes the
published directory, restores the previous pointer, and removes the staging directory. Import never leaves kb-home
changed on failure. `fault_at` injects a failure at a named boundary for tests.
"""

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.package.archive import PackageError, read_package_archive
from odooflux.knowledge.package.builder import SUMS_NAME
from odooflux.knowledge.package.archive import MANIFEST_NAME as PACKAGE_MANIFEST
from odooflux.knowledge.package.validate import check_internal, validate_package
from odooflux.knowledge.release.audit import KbAudit
from odooflux.knowledge.release.canonical import write_json_file
from odooflux.knowledge.release.manifest import MANIFEST_NAME as RELEASE_MANIFEST, META_FIELDS, STATE_NAME, \
    require_intact, write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError, ReleaseState
from odooflux.knowledge.release.safety import package_fix_findings
from odooflux.knowledge.release.store import ACTIVE_NAME, KbLock, build_pointer, ensure_layout, read_active, \
    utc_now, write_active
from odooflux.utils.atomic import atomic_write_text

FAULT_POINTS = ("extract", "verify", "gates", "state", "move", "activate", "audit")
DOWNGRADED_MATURITY = "DETECT_ONLY"
FIX_ENABLED = "FIX_ENABLED"


class ImportFault(RuntimeError):
    """Injected failure at a named import boundary (tests only)."""


@dataclass(frozen=True)
class ImportResult:
    release_id: str
    release_digest: str
    installed: bool
    activated: bool
    downgraded_rules: tuple


def _fault(point: str, fault_at) -> None:
    if point == fault_at:
        raise ImportFault(f"injected fault at {point}")


def _read_release(staging: Path) -> dict:
    try:
        return json.loads((staging / RELEASE_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise KnowledgeReleaseError("staged release manifest is unreadable") from None


def _strip_package_files(staging: Path) -> None:
    """The staged tree becomes the release tree: package.json and integrity/ are not part of the release."""
    (staging / PACKAGE_MANIFEST).unlink(missing_ok=True)
    shutil.rmtree(staging / "integrity", ignore_errors=True)


def _cap_rules(knowledge_root: Path, rule_ids: set) -> None:
    """Cap the named FIX_ENABLED rules to DETECT_ONLY in the staged rule files (P10 downgrade)."""
    for path in sorted((knowledge_root / "compatibility").glob("*.rules.json")):
        rules = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for rule in rules:
            if isinstance(rule, dict) and rule.get("id") in rule_ids and rule.get("maturity") == FIX_ENABLED:
                rule["maturity"] = DOWNGRADED_MATURITY
                changed = True
        if changed:
            write_json_file(path, rules)


def _restore_pointer(home: Path, previous) -> None:
    if previous is None:
        (home / ACTIVE_NAME).unlink(missing_ok=True)
    else:
        write_active(home, previous)


def _refuse_internal_archive(archive) -> None:
    """P12 before anything is staged. The package is read by the safe reader into a scratch directory outside kb-home
    (its P01 to P08 checks apply) and refused when its release is internal or Enterprise-derived."""
    with tempfile.TemporaryDirectory() as scratch:
        staged = read_package_archive(archive, scratch)
        try:
            check_internal(staged.staging_dir, staged.manifest)
        finally:
            staged.discard()


def import_package(archive, kb_home, *, activate: bool = False, downgrade_unverified: bool = False,
                   expect_digest: str = None, running_version: str = None, fault_at: str = None) -> ImportResult:
    """Import a package into kb-home atomically. Raises PackageError (P-code) on rejection, KbLockedError if another
    process holds kb-home, ImportFault only when `fault_at` is set. kb-home is unchanged on any raise."""
    if fault_at is not None and fault_at not in FAULT_POINTS:
        raise ValueError(f"unknown fault point {fault_at!r}")
    _refuse_internal_archive(archive)
    home = ensure_layout(kb_home)
    with KbLock(home):
        _fault("extract", fault_at)
        validated = validate_package(archive, home / "staging", running_version=running_version,
                                     expect_digest=expect_digest)
        staging = validated.staging_dir
        moved = False
        pointer_changed = False
        current = None
        dest = None
        try:
            _fault("verify", fault_at)
            _strip_package_files(staging)
            downgraded = ()
            _fault("gates", fault_at)
            findings, inherited, baseline = package_fix_findings(staging / "knowledge")
            if findings:
                rule_ids = sorted({f["rule_id"] for f in findings})
                if not downgrade_unverified:
                    raise PackageError("P10", "unverified FIX_ENABLED rule(s) refused: " + ", ".join(rule_ids))
                _cap_rules(staging / "knowledge", set(rule_ids))
                meta = {key: validated.release[key] for key in sorted(META_FIELDS)}
                write_release_manifest(staging, meta)
                if package_fix_findings(staging / "knowledge")[0]:
                    raise PackageError("P10", "FIX_ENABLED rules still fail gates after downgrade")
                downgraded = tuple(rule_ids)
            require_intact(staging)
            release = _read_release(staging)
            release_id, digest = release["release_id"], release["release_digest"]

            _fault("state", fault_at)
            atomic_write_text(staging / STATE_NAME, json.dumps({"state": ReleaseState.INSTALLED.value},
                                                               sort_keys=True) + "\n")
            dest = home / "releases" / release_id
            already = dest.exists()
            if already:
                require_intact(dest)
                if _read_release(dest)["release_digest"] != digest:
                    raise KnowledgeReleaseError(f"installed {release_id} differs from the package")
                shutil.rmtree(staging, ignore_errors=True)
            else:
                _fault("move", fault_at)
                os.replace(staging, dest)
                moved = True

            activated = False
            current = read_active(home)
            if activate and not (current and current["release_id"] == release_id):
                _fault("activate", fault_at)
                write_active(home, build_pointer(current, release_id, digest, utc_now()))
                pointer_changed = True
                activated = True

            _fault("audit", fault_at)
            audit = KbAudit(home, uuid.uuid4().hex)
            if not already:
                details = {"downgraded_rules": list(downgraded)} if downgraded else {}
                if inherited:  # D3: shipped rows accepted by byte identity with the verified baseline (never by id)
                    details["inherited_trust"] = {"rule_ids": list(inherited), "baseline_digest": baseline}
                audit.record("release_installed", target=release_id, details=details or None)
            if activated:
                audit.record("release_activated", target=release_id)
        except BaseException:
            if pointer_changed:
                _restore_pointer(home, current)
            if moved and dest is not None:
                shutil.rmtree(dest, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return ImportResult(release_id=release_id, release_digest=digest, installed=not already,
                        activated=activated, downgraded_rules=downgraded)
