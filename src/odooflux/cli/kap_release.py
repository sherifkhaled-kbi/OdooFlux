"""`odooflux knowledge release ...` (contracts/cli-surface.md, contracts/release-lifecycle.md; REQ-KAP-025, 026, 045).

Verbs: list, show ID, activate ID, deactivate, rollback, remove ID, diff A B, audit-verify, and `build` (runs the
release pipeline, `knowledge/pipeline.py`, from a plan file; a built release is INSTALLED, never ACTIVE).

Activation is one atomic `active.json` write under the kb-home lock. Every failure after the write restores the previous
pointer, so a fault at any boundary leaves the previous active release in place (`FAULT_POINTS`, tests only).
Exit codes come from `cli/kap_common.py`: 0 ok, 1 refused or unknown release, 2 usage or unavailable, 5 integrity.
"""

import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from odooflux import __version__
from odooflux.cli.kap_common import (EXIT_INTEGRITY, EXIT_OK, EXIT_PACKAGE_REJECTED, EXIT_SOURCE_UNAVAILABLE,
                                     EXIT_USAGE, EXIT_VALIDATION, attached)
from odooflux.cli.kap_extract import full_registry
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.sources import load_allow_list
from odooflux.knowledge.extract import driver
from odooflux.knowledge.release.audit import KbAudit, verify_audit
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.diff import diff_releases
from odooflux.knowledge.release.manifest import MANIFEST_NAME, require_intact
from odooflux.knowledge.release.model import LOADABLE_STATES, KnowledgeReleaseError, ReleaseState, builtin_handle
from odooflux.knowledge.release.resolver import HOME_ENV, default_kb_home
from odooflux.knowledge.release.store import (ACTIVE_FORMAT, ACTIVE_NAME, KbLock, KbLockedError, build_pointer,
                                              ensure_layout, list_installed, read_active, read_release_state,
                                              utc_now, write_active)
from odooflux.utils.redaction import redact_text

FAULT_POINTS = ("verify", "lock", "pointer", "audit")
_RELEASE_ID = re.compile(r"^kr-[0-9a-f]{12}$")
GIT_KINDS = ("GIT_COMMUNITY",)  # adapters the build constructs; any other kind fails its source as IO_ERROR
STOP_EXIT = {"SOURCE_REQUIRED_FAILED": EXIT_SOURCE_UNAVAILABLE, "SOURCE_REQUIRED_NOT_VERIFIED": EXIT_SOURCE_UNAVAILABLE,
             "CHECKSUM_MISMATCH": EXIT_INTEGRITY, "MANIFEST_INCONSISTENT": EXIT_INTEGRITY,
             "PROVENANCE_INVALID": EXIT_INTEGRITY, "RELEASE_INTEGRITY": EXIT_INTEGRITY}


class ReleaseFault(RuntimeError):
    """Injected failure at a named activation boundary (tests only)."""


class ReleaseCommandError(Exception):
    """A refused or unknown operation. `code` is the exit code to return."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _fault(point: str, fault_at) -> None:
    if point == fault_at:
        raise ReleaseFault(f"injected fault at {point}")


def _home(args) -> Path:
    return Path(args.kb_home or os.environ.get(HOME_ENV) or default_kb_home())


def _release_dir(home: Path, release_id: str) -> Path:
    if not _RELEASE_ID.match(release_id or ""):
        # The argument is not echoed: it may be a mistyped secret (REQ-KAP-046).
        raise ReleaseCommandError(EXIT_VALIDATION, "not a release id (expected kr- followed by 12 hex digits)")
    path = home / "releases" / release_id
    if not path.is_dir():
        raise ReleaseCommandError(EXIT_VALIDATION, f"no installed release {release_id}")
    return path


def _digest_of(release_dir: Path) -> str:
    try:
        return json.loads((release_dir / MANIFEST_NAME).read_text(encoding="utf-8"))["release_digest"]
    except (OSError, ValueError, KeyError, TypeError):
        raise KnowledgeReleaseError(f"{release_dir}: unreadable release manifest") from None


def _require_loadable(release_dir: Path, release_id: str) -> str:
    state = read_release_state(release_dir)
    if state not in LOADABLE_STATES:
        raise ReleaseCommandError(EXIT_VALIDATION, f"release {release_id} is {state.value}, not installed")
    return _digest_of(release_dir)


def _restore(home: Path, previous) -> None:
    if previous is None:
        (home / ACTIVE_NAME).unlink(missing_ok=True)
    else:
        write_active(home, previous)


def activate(home, release_id: str, *, fault_at: str = None, now: str = None) -> dict:
    """Make `release_id` the active release atomically. Returns the pointer now in effect.

    Raises ReleaseCommandError (refused), KnowledgeReleaseError (integrity), KbLockedError, or ReleaseFault (tests).
    The previous pointer is restored on any failure after the lock is taken."""
    home = Path(home)
    if fault_at is not None and fault_at not in FAULT_POINTS:
        raise ValueError(f"unknown fault point {fault_at!r}")
    home = ensure_layout(home)
    release_dir = _release_dir(home, release_id)
    _fault("verify", fault_at)
    require_intact(release_dir)
    digest = _require_loadable(release_dir, release_id)
    with KbLock(home):
        _fault("lock", fault_at)
        current = read_active(home)
        if current is not None and current["release_id"] == release_id:
            return current
        pointer = build_pointer(current, release_id, digest, now or utc_now())
        pointer["previous"] = [p for p in pointer["previous"] if p["release_id"] != release_id]
        written = False
        try:
            _fault("pointer", fault_at)
            write_active(home, pointer)
            written = True
            _fault("audit", fault_at)
            KbAudit(home, uuid.uuid4().hex).record("release_activated", target=release_id)
        except BaseException:
            if written:
                _restore(home, current)
            raise
    return pointer


def rollback(home, *, now: str = None) -> dict:
    """Activate `previous[0]` of the active pointer. Refused (current stays) if that release is missing or fails
    verification. The release rolled away from moves to the front of `previous`."""
    home = Path(home)
    with KbLock(home):
        current = read_active(home)
        if current is None:
            raise ReleaseCommandError(EXIT_VALIDATION, "no active release; nothing to roll back")
        if not current["previous"]:
            raise ReleaseCommandError(EXIT_VALIDATION, "no previous release recorded; nothing to roll back to")
        target = current["previous"][0]
        release_dir = home / "releases" / target["release_id"]
        if not release_dir.is_dir():
            raise KnowledgeReleaseError(f"previous release {target['release_id']} is missing")
        require_intact(release_dir)
        digest = _require_loadable(release_dir, target["release_id"])
        if digest != target["digest"]:
            raise KnowledgeReleaseError(f"previous release {target['release_id']} digest differs from the pointer")
        stamp = now or utc_now()
        away = {"release_id": current["release_id"], "digest": current["digest"], "deactivated_at": stamp}
        pointer = {"format": ACTIVE_FORMAT, "release_id": target["release_id"], "digest": digest,
                   "activated_at": stamp, "previous": [away] + current["previous"][1:]}
        write_active(home, pointer)
        KbAudit(home, uuid.uuid4().hex).record("release_rolled_back", target=target["release_id"],
                                               details={"from": current["release_id"]})
    return pointer


def deactivate(home):
    """Remove the active pointer: the built-in release becomes the active one. Returns the release that was active."""
    home = Path(home)
    with KbLock(home):
        current = read_active(home)
        if current is None:
            return None
        (home / ACTIVE_NAME).unlink()
        KbAudit(home, uuid.uuid4().hex).record("release_deactivated", target=current["release_id"])
    return current


def remove(home, release_id: str, *, force_previous: bool = False) -> None:
    """Delete an installed release. ACTIVE is always refused; a `previous` entry needs `force_previous`, and is then
    dropped from the pointer. The directory goes to `staging/trash/` before it is deleted."""
    home = Path(home)
    release_dir = _release_dir(home, release_id)
    with KbLock(home):
        current = read_active(home)
        if current is not None and current["release_id"] == release_id:
            raise ReleaseCommandError(EXIT_VALIDATION, f"release {release_id} is ACTIVE; deactivate or activate another")
        listed = [p for p in (current["previous"] if current else []) if p["release_id"] == release_id]
        if listed and not force_previous:
            raise ReleaseCommandError(EXIT_VALIDATION,
                                      f"release {release_id} is in the previous stack; use --force-previous")
        if listed:
            pruned = dict(current, previous=[p for p in current["previous"] if p["release_id"] != release_id])
            write_active(home, pruned)
        trash = home / "staging" / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        moved = trash / f"{release_id}-{uuid.uuid4().hex}"
        os.replace(release_dir, moved)
        shutil.rmtree(moved, ignore_errors=True)
        KbAudit(home, uuid.uuid4().hex).record("release_removed", target=release_id)


def _emit(args, payload, text_lines) -> None:
    if args.json:
        sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")
    elif not args.quiet:
        for line in text_lines:
            print(line)


def _manifest(release_dir: Path) -> dict:
    return json.loads((release_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def cmd_list(args) -> int:
    home = _home(args)
    rows = [{"release_id": r.release_id, "digest": r.digest, "state": r.state.value, "active": r.active}
            for r in list_installed(home)]
    lines = [f"{r['release_id']}  {r['state']:<9}  {r['digest']}" for r in rows] or ["no installed releases"]
    _emit(args, {"releases": rows}, lines)
    return EXIT_OK


def cmd_show(args) -> int:
    home = _home(args)
    release_dir = _release_dir(home, args.release_id)
    manifest = _manifest(release_dir)
    active = read_active(home)
    state = read_release_state(release_dir)
    if active and active["release_id"] == args.release_id:
        state = ReleaseState.ACTIVE
    payload = {"release_id": manifest["release_id"], "release_digest": manifest["release_digest"],
               "state": state.value, "active": state is ReleaseState.ACTIVE,
               "label": manifest.get("label"), "completeness": manifest.get("completeness"),
               "parent_release": manifest.get("parent_release"), "file_count": len(manifest.get("files", []))}
    lines = [f"{key}: {value}" for key, value in payload.items()]
    _emit(args, payload, lines)
    return EXIT_OK


def cmd_activate(args) -> int:
    pointer = activate(_home(args), args.release_id)
    _emit(args, {"active": pointer["release_id"], "digest": pointer["digest"]},
          [f"active: {pointer['release_id']} {pointer['digest']}"])
    return EXIT_OK


def cmd_deactivate(args) -> int:
    previous = deactivate(_home(args))
    if previous is None:
        _emit(args, {"deactivated": None}, ["no active release; built-in knowledge is in use"])
    else:
        _emit(args, {"deactivated": previous["release_id"]},
              [f"deactivated: {previous['release_id']}; built-in knowledge is now in use"])
    return EXIT_OK


def cmd_rollback(args) -> int:
    pointer = rollback(_home(args))
    _emit(args, {"active": pointer["release_id"], "digest": pointer["digest"]},
          [f"rolled back; active: {pointer['release_id']} {pointer['digest']}"])
    return EXIT_OK


def cmd_remove(args) -> int:
    remove(_home(args), args.release_id, force_previous=args.force_previous)
    _emit(args, {"removed": args.release_id}, [f"removed: {args.release_id}"])
    return EXIT_OK


def cmd_diff(args) -> int:
    home = _home(args)
    result = diff_releases(_release_dir(home, args.a), _release_dir(home, args.b))
    rows = [{"kind": e["kind"], "family": e["family"], "id": e["id"], "change": e["change"],
             "destructive": e["destructive"]} for e in result.entries]
    lines = [f"{'DESTRUCTIVE ' if e['destructive'] else ''}{e['change']} {e['kind']} {e['family']} {e['id']}"
             for e in rows]
    lines.append(f"counts={canonical_bytes(result.counts).decode('utf-8')} unchanged={result.unchanged}")
    _emit(args, {"entries": rows, "counts": result.counts, "unchanged": result.unchanged}, lines)
    return EXIT_OK


def cmd_audit_verify(args) -> int:
    ok, reason = verify_audit(_home(args))
    _emit(args, {"ok": ok, "reason": reason}, ["audit chain intact" if ok else f"audit chain broken: {reason}"])
    return EXIT_OK if ok else EXIT_INTEGRITY


def _read_plan(path) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseCommandError(EXIT_USAGE, f"cannot read the build plan: {type(exc).__name__}") from None
    if not isinstance(document, dict) or not all(key in document for key in ("label", "sources", "pairs")):
        raise ReleaseCommandError(EXIT_USAGE, "the build plan needs label, sources and pairs")
    return document


def _extractor(toolkit):
    registry = full_registry()

    def extract(from_snap, to_snap, step, store):
        result = driver.extract_pair(from_snap, to_snap, None, registry, store=store, step=step, toolkit=toolkit)
        return result.drafts, result.accounting
    return extract


def _exit_code(result) -> int:
    if result.outcome in ("PLAN", "OK"):
        return EXIT_OK
    if result.outcome == "FAILED":
        return EXIT_VALIDATION
    code = result.code or ""
    if code in STOP_EXIT:
        return STOP_EXIT[code]
    return EXIT_PACKAGE_REJECTED if re.match(r"^P\d\d$", code) else EXIT_VALIDATION


def cmd_build(args) -> int:
    home = _home(args)
    toolkit = attached(args, "extract_toolkit")
    if toolkit is None:
        raise ReleaseCommandError(EXIT_USAGE, "build needs the bindable detector table (extract_toolkit)")
    document = _read_plan(args.plan)
    parent = None
    if args.parent:
        parent = _release_dir(home, args.parent)
        if not parent.is_dir():
            raise ReleaseCommandError(EXIT_VALIDATION, f"no installed parent release {args.parent}")
    created_at = document.get("created_at") or utc_now()
    plan = pl.BuildPlan(
        label=document["label"], specs=document["sources"], pairs=document["pairs"],
        base_tree=builtin_handle().root, adapters={kind: GitLocalAdapter(kind) for kind in GIT_KINDS},
        extract=_extractor(toolkit), known_detectors=toolkit.detectors, created_at=created_at,
        checked_on=document.get("checked_on") or created_at[:10], author=document.get("author") or "cli",
        tool_version=__version__, parent_dir=parent, supersede=tuple(args.supersede or ()),
        source_meta=document.get("source_meta") or {}, allow_list=load_allow_list())
    result = pl.run_build(home, plan, dry_run=args.dry_run, from_step=args.from_step,
                          allow_failed=args.allow_failed)
    payload = {"outcome": result.outcome, "stopped_at": result.stopped_at, "code": result.code,
               "message": result.message, "release_id": result.release_id, "completeness": result.completeness,
               "steps": result.rows}
    lines = [f"{row['number']:02d} {row['name']:<16} {row.get('status', '-'):<8} {row['action']}"
             for row in result.rows]
    lines.append(f"outcome {result.outcome}" + (f" completeness {result.completeness}" if result.completeness else ""))
    if result.code:
        lines.append(f"stopped at step {result.stopped_at}: {result.code} {result.message or ''}".rstrip())
    if result.release_id:
        lines.append(f"release {result.release_id}" + (" (development only, not exportable)" if result.dev_only
                                                       else ""))
    _emit(args, payload, lines)
    return _exit_code(result)


_HANDLERS = {
    "list": cmd_list, "show": cmd_show, "activate": cmd_activate, "deactivate": cmd_deactivate,
    "rollback": cmd_rollback, "remove": cmd_remove, "diff": cmd_diff, "audit-verify": cmd_audit_verify,
    "build": cmd_build,
}


def _guarded(handler):
    def run(args) -> int:
        try:
            return handler(args)
        except ReleaseCommandError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return exc.code
        except KbLockedError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return EXIT_VALIDATION
        except KnowledgeReleaseError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return EXIT_INTEGRITY
    return run


def _common(parser) -> None:
    parser.add_argument("--kb-home", default=None, metavar="PATH", help="kb-home directory")
    parser.add_argument("--json", action="store_true", help="canonical JSON output")
    parser.add_argument("--quiet", action="store_true", help="no human output")


def register(subparsers) -> None:
    group = subparsers.add_parser("release", help="knowledge release lifecycle in kb-home")
    verbs = group.add_subparsers(dest="release_action", required=True)

    specs = [
        ("list", "list installed releases", []),
        ("show", "show one installed release", [("release_id", {})]),
        ("activate", "make an installed release active (atomic)", [("release_id", {})]),
        ("deactivate", "return to the built-in knowledge", []),
        ("rollback", "activate the previous release", []),
        ("remove", "delete an installed, inactive release", [("release_id", {})]),
        ("diff", "compare two installed releases", [("a", {}), ("b", {})]),
        ("audit-verify", "verify the kb-home audit hash chain", []),
        ("build", "build a release from a plan file (pipeline)", []),
    ]
    for name, help_text, positionals in specs:
        leaf = verbs.add_parser(name, help=help_text)
        for dest, extra in positionals:
            leaf.add_argument(dest, **extra)
        if name == "remove":
            leaf.add_argument("--force-previous", action="store_true",
                              help="also remove a release listed in the previous stack")
        if name == "build":
            leaf.add_argument("--plan", required=True, metavar="FILE", help="build plan (JSON)")
            leaf.add_argument("--parent", default=None, metavar="ID", help="installed parent release")
            leaf.add_argument("--supersede", action="append", default=[], metavar="ID",
                              help="approve a destructive removal (recorded flag, repeatable)")
            leaf.add_argument("--dry-run", action="store_true")
            leaf.add_argument("--from-step", type=int, default=None, metavar="N")
            leaf.add_argument("--allow-failed", action="store_true", help="development only; never exportable")
        _common(leaf)
        leaf.set_defaults(kap_handler=_guarded(_HANDLERS[name]))
