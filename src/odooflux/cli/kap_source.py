"""`odooflux knowledge source ...` (contracts/cli-surface.md, contracts/source-adapter.md; REQ-KAP-006, 001, 009).

Verbs: add --file SPEC, list, show ID, remove ID, acquire [ID...] [--i-am-entitled], verify [ID...], fetch ID
--allow-network [--sha256 HEX]. Every verb takes `--registry FILE` (default `./sources.json`), `--kb-home PATH`,
`--json`, `--quiet`.

The registry file is persisted here (`acquisition/sources.py` is in-memory and only enforces the rules). Each source
record is stored with its status; on load the record is replayed through the public status machine, so an invalid
file is refused. Snapshots and blobs live under `<kb-home>/snapshots/`. Adapters are registered by kind through
`sources.register_adapter`. `fetch` is the only verb that can reach the network, and it refuses without
`--allow-network` (exit 2). After each adapter or fetch call this module applies the status transition; the adapters
and `fetch` return results and never touch the registry.

Exit codes come from `cli/kap_common.py`: 0 ok, 1 validation or unknown source, 2 usage or network not allowed,
4 required source unavailable or pinned revision missing (FAILED), 5 integrity failure in `verify`.
A source without entitlement is SKIPPED_UNAUTHORIZED, which is not a failure.
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

from odooflux.cli.kap_common import EXIT_INTEGRITY, EXIT_OK, EXIT_SOURCE_UNAVAILABLE, EXIT_USAGE, EXIT_VALIDATION
from odooflux.knowledge.acquisition.adapters.directory import DirectoryAdapter
from odooflux.knowledge.acquisition.adapters.enterprise_local import EnterpriseLocalAdapter, community_limit_entry
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.adapters.snapshot_pack import SnapshotPackAdapter
from odooflux.knowledge.acquisition.adapters.supplementary import SupplementaryAdapter
from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.fetch import fetch
from odooflux.knowledge.acquisition.sources import FAILURE_CODES, RegistryError, SourceRegistry, register_adapter
from odooflux.knowledge.release.audit import KbAudit
from odooflux.knowledge.release.canonical import canonical_bytes, digest_obj, write_json_file
from odooflux.knowledge.release.resolver import HOME_ENV, default_kb_home
from odooflux.knowledge.release.store import ensure_layout, utc_now
from odooflux.utils.atomic import atomic_write_bytes
from odooflux.utils.redaction import redact_text

REGISTRY_FORMAT = "odooflux.sources/1"
REGISTRY_NAME = "sources.json"
SNAPSHOT_DIR = "snapshots"
DOCS_SCOPE = ["*.rst"]
_STATUS_PATH = {
    "DECLARED": (),
    "RETRIEVED": ("RETRIEVED",),
    "VERIFIED": ("RETRIEVED", "VERIFIED"),
    "FAILED": ("FAILED",),
    "UNAVAILABLE": ("UNAVAILABLE",),
    "SKIPPED_UNAUTHORIZED": ("SKIPPED_UNAUTHORIZED",),
}
_RETRYABLE = ("FAILED", "UNAVAILABLE")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
UNKNOWN_SOURCE = "unknown source (not in the registry)"  # the argument is never echoed (REQ-KAP-046)


class SourceCommandError(Exception):
    """A refused command. `code` is the exit code to return."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _home(args) -> Path:
    return Path(args.kb_home or os.environ.get(HOME_ENV) or default_kb_home())


def _registry_path(args) -> Path:
    return Path(args.registry) if args.registry else Path.cwd() / REGISTRY_NAME


def build_adapters(entitled: bool = False) -> dict:
    """One adapter per kind, registered through `sources.register_adapter`. The entitlement flag is per run."""
    adapters = {
        "GIT_COMMUNITY": GitLocalAdapter("GIT_COMMUNITY"),
        "DOCS": GitLocalAdapter("DOCS"),
        "UPGRADE_SCRIPTS": GitLocalAdapter("UPGRADE_SCRIPTS"),
        "OCA": SupplementaryAdapter("OCA"),
        "OPENUPGRADE": SupplementaryAdapter("OPENUPGRADE"),
        "DIRECTORY": DirectoryAdapter(),
        "SNAPSHOT_PACK": SnapshotPackAdapter(),
        "ENTERPRISE_LOCAL": EnterpriseLocalAdapter(entitled=entitled),
    }
    for kind, adapter in adapters.items():
        register_adapter(kind, adapter)
    return adapters


def _restore(registry: SourceRegistry, rec: dict) -> None:
    """Re-add a stored record: register it as DECLARED, then replay the status machine up to its stored status."""
    sid = rec["source_id"]
    registry.add(dict(rec, status="DECLARED", retrieved_at=None, checksum=None, failure_reason=None))
    for step in _STATUS_PATH[rec["status"]]:
        registry.transition(sid, step, failure_reason=rec["failure_reason"], checksum=rec["checksum"],
                            retrieved_at=rec["retrieved_at"])


def _load(path: Path):
    """(registry, extras). `extras[source_id]` holds snapshot_id, label, limits, provenance."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SourceCommandError(EXIT_VALIDATION, f"registry {path} is unreadable: {exc}") from None
        if not isinstance(data, dict) or data.get("format") != REGISTRY_FORMAT:
            raise SourceCommandError(EXIT_VALIDATION, f"registry {path} is not an {REGISTRY_FORMAT} file")
    else:
        data = {"format": REGISTRY_FORMAT, "sources": {}}
    registry = SourceRegistry()
    extras = {}
    try:
        for sid in sorted(data["sources"]):
            entry = data["sources"][sid]
            rec = entry["record"]
            _restore(registry, rec)
            extras[sid] = dict(entry.get("extra") or {})
    except (RegistryError, KeyError, TypeError) as exc:
        raise SourceCommandError(EXIT_VALIDATION, f"registry {path} is invalid: {exc}") from None
    return registry, extras


def _save(path: Path, registry: SourceRegistry, extras: dict) -> None:
    sources = {rec["source_id"]: {"record": rec, "extra": extras.get(rec["source_id"], {})}
               for rec in registry.sources()}
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, {"format": REGISTRY_FORMAT, "sources": sources})


def _ids(registry: SourceRegistry, requested) -> list:
    known = [rec["source_id"] for rec in registry.sources()]
    for sid in requested or []:
        if sid not in known:
            raise SourceCommandError(EXIT_VALIDATION, UNKNOWN_SOURCE)
    return list(requested) if requested else known


def _effective_spec(rec: dict) -> dict:
    """The spec the adapter sees. DOCS reads `.rst` files only unless the spec narrows the scope further."""
    spec = json.loads(json.dumps(rec))
    if rec["kind"] == "DOCS" and not spec["scope"]["include"]:
        spec["scope"]["include"] = list(DOCS_SCOPE)
    return spec


def _failure_transition(kind: str, exc: SourceError):
    """(new_status, failure_reason) for an adapter or fetch error. Reasons start with a closed code. The message is
    masked before it is stored in the registry or printed (REQ-KAP-046)."""
    message = redact_text(str(exc.message))
    if kind == "ENTERPRISE_LOCAL" and exc.code == "AUTH_REQUIRED":
        return "SKIPPED_UNAUTHORIZED", f"AUTH_REQUIRED: {message}"
    if exc.code == "NETWORK_DISABLED":
        return "UNAVAILABLE", f"IO_ERROR: NETWORK_DISABLED: {message}"
    if exc.code in FAILURE_CODES:
        return "FAILED", f"{exc.code}: {message}"
    return "FAILED", f"IO_ERROR: {exc.code}: {message}"


def _audit(home: Path, action: str, sid: str, **details) -> None:
    KbAudit(home, uuid.uuid4().hex).record(action, target=sid, outcome="ok" if action == "source_acquired" else "failed",
                                           details=details or None)


def _prepare_retry(registry: SourceRegistry, sid: str) -> str:
    """FAILED and UNAVAILABLE sources go back to DECLARED for a new attempt. Returns the status to act on."""
    status = registry.get(sid)["status"]
    if status in _RETRYABLE:
        registry.transition(sid, "DECLARED")
        status = "DECLARED"
    return status


def _acquire_one(home: Path, registry: SourceRegistry, extras: dict, sid: str, store: BlobStore,
                 adapters: dict) -> dict:
    status = _prepare_retry(registry, sid)
    rec = registry.get(sid)
    row = {"source_id": sid, "kind": rec["kind"], "status": status, "reason": None, "snapshot_id": None}
    if status != "DECLARED":
        row["reason"] = "already final; not re-acquired"
        return row
    adapter = adapters[rec["kind"]]
    extra = extras.setdefault(sid, {})
    if rec["kind"] == "OCA" or rec["kind"] == "OPENUPGRADE":
        extra["label"] = adapter.label(rec)
    if rec["kind"] == "ENTERPRISE_LOCAL":
        extra["provenance"] = adapter.provenance(rec)
    try:
        snap = adapter.snapshot(_effective_spec(rec), store, created_at=utc_now())
    except SourceError as exc:
        if rec["kind"] == "ENTERPRISE_LOCAL" and exc.code == "AUTH_REQUIRED":
            extra["limits"] = [community_limit_entry(rec)]
        new_status, reason = _failure_transition(rec["kind"], exc)
        registry.transition(sid, new_status, failure_reason=reason)
        if new_status == "SKIPPED_UNAUTHORIZED":
            row.update(status=new_status, reason=reason)
            return row
        _audit(home, "source_failed", sid, code=exc.code)
        row.update(status=new_status, reason=reason)
        return row
    atomic_write_bytes(home / SNAPSHOT_DIR / f"{snap['snapshot_id']}.json", canonical_bytes(snap) + b"\n")
    registry.transition(sid, "RETRIEVED", checksum=snap["snapshot_digest"], retrieved_at=snap["created_at"])
    extra["snapshot_id"] = snap["snapshot_id"]
    _audit(home, "source_acquired", sid, snapshot_id=snap["snapshot_id"], revision=snap["revision"])
    row.update(status="RETRIEVED", snapshot_id=snap["snapshot_id"])
    return row


def _verify_one(home: Path, registry: SourceRegistry, extras: dict, sid: str, store: BlobStore) -> dict:
    rec = registry.get(sid)
    row = {"source_id": sid, "kind": rec["kind"], "status": rec["status"], "reason": None, "snapshot_id": None}
    if rec["status"] == "VERIFIED":
        row["reason"] = "already verified"
        return row
    if rec["status"] != "RETRIEVED":
        row["reason"] = "nothing to verify (status is not RETRIEVED)"
        return row
    snapshot_id = extras.get(sid, {}).get("snapshot_id")
    try:
        if snapshot_id is None:  # fetched bytes without a snapshot: the checksum is the blob digest
            store.get(rec["checksum"])
        else:
            snap = json.loads((home / SNAPSHOT_DIR / f"{snapshot_id}.json").read_text(encoding="utf-8"))
            for entry in snap["entries"]:
                store.get(entry["sha256"])
            recomputed = digest_obj({"source_id": sid, "revision": snap["revision"], "entries": snap["entries"]})
            if recomputed != snap["snapshot_digest"] or snap["snapshot_digest"] != rec["checksum"]:
                raise SourceError("CHECKSUM_MISMATCH", sid, "snapshot digest does not match its entries")
        registry.transition(sid, "VERIFIED")
        row.update(status="VERIFIED", snapshot_id=snapshot_id)
    except (SourceError, OSError, ValueError, KeyError, TypeError) as exc:
        message = exc.message if isinstance(exc, SourceError) else type(exc).__name__
        reason = f"CHECKSUM_MISMATCH: {message}"
        registry.transition(sid, "FAILED", failure_reason=reason)
        _audit(home, "source_failed", sid, code="CHECKSUM_MISMATCH")
        row.update(status="FAILED", reason=reason)
    return row


def _emit(args, payload, lines) -> None:
    if args.json:
        sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")
    elif not args.quiet:
        for line in lines:
            print(line)


def _row_lines(rows) -> list:
    return [f"{r['source_id']}  {r['status']}" + (f"  {r['reason']}" if r.get("reason") else "") for r in rows]


def cmd_add(args) -> int:
    path = _registry_path(args)
    registry, extras = _load(path)
    try:
        spec = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceCommandError(EXIT_VALIDATION, f"spec file unreadable: {exc}") from None
    if not isinstance(spec, dict):
        raise SourceCommandError(EXIT_VALIDATION, "spec file must hold one JSON object")
    try:
        registry.add(spec)
    except RegistryError as exc:
        raise SourceCommandError(EXIT_VALIDATION, f"spec refused: {exc}") from None
    sid = spec["source_id"]
    extras[sid] = {}
    _save(path, registry, extras)
    _emit(args, {"added": sid}, [f"added: {sid}"])
    return EXIT_OK


def cmd_list(args) -> int:
    registry, extras = _load(_registry_path(args))
    rows = [{"source_id": r["source_id"], "kind": r["kind"], "official": r["official"], "status": r["status"],
             "revision": r["revision"], "required": r["required"],
             "label": (extras.get(r["source_id"], {}).get("label") or {}).get("label")}
            for r in registry.sources()]
    lines = [f"{r['source_id']}  {r['kind']:<17} {r['status']:<21} official={str(r['official']).lower()}"
             + (f"  {r['label']}" if r["label"] else "") for r in rows] or ["no sources registered"]
    _emit(args, {"sources": rows}, lines)
    return EXIT_OK


def cmd_show(args) -> int:
    registry, extras = _load(_registry_path(args))
    if args.source_id not in [r["source_id"] for r in registry.sources()]:
        raise SourceCommandError(EXIT_VALIDATION, UNKNOWN_SOURCE)
    payload = {**registry.get(args.source_id), **extras.get(args.source_id, {})}
    _emit(args, payload, [f"{key}: {value}" for key, value in payload.items()])
    return EXIT_OK


def cmd_remove(args) -> int:
    path = _registry_path(args)
    registry, extras = _load(path)
    if args.source_id not in [r["source_id"] for r in registry.sources()]:
        raise SourceCommandError(EXIT_VALIDATION, UNKNOWN_SOURCE)
    remaining = SourceRegistry()
    for rec in registry.sources():
        if rec["source_id"] != args.source_id:
            _restore(remaining, rec)
    extras.pop(args.source_id, None)
    _save(path, remaining, extras)
    _emit(args, {"removed": args.source_id}, [f"removed: {args.source_id}"])
    return EXIT_OK


def cmd_acquire(args) -> int:
    home = ensure_layout(_home(args))
    path = _registry_path(args)
    registry, extras = _load(path)
    adapters = build_adapters(entitled=args.i_am_entitled)
    store = BlobStore(home / SNAPSHOT_DIR)
    rows = [_acquire_one(home, registry, extras, sid, store, adapters) for sid in _ids(registry, args.source_ids)]
    _save(path, registry, extras)
    required_down = any(r["status"] in ("FAILED", "UNAVAILABLE") and registry.get(r["source_id"])["required"]
                        for r in rows)
    _emit(args, {"results": rows}, _row_lines(rows))
    return EXIT_SOURCE_UNAVAILABLE if required_down else EXIT_OK


def cmd_verify(args) -> int:
    home = ensure_layout(_home(args))
    path = _registry_path(args)
    registry, extras = _load(path)
    store = BlobStore(home / SNAPSHOT_DIR)
    rows = [_verify_one(home, registry, extras, sid, store) for sid in _ids(registry, args.source_ids)]
    _save(path, registry, extras)
    failed = any(r["status"] == "FAILED" for r in rows)
    _emit(args, {"results": rows}, _row_lines(rows))
    return EXIT_INTEGRITY if failed else EXIT_OK


def cmd_fetch(args) -> int:
    if not args.allow_network:
        raise SourceCommandError(EXIT_USAGE, "source fetch needs the explicit --allow-network flag")
    if args.sha256 is not None and not _SHA256_HEX.match(args.sha256):
        # not echoed: a mistyped secret must not reach the terminal or the registry (REQ-KAP-046)
        raise SourceCommandError(EXIT_USAGE, "--sha256 must be 64 lowercase hex characters")
    home = ensure_layout(_home(args))
    path = _registry_path(args)
    registry, extras = _load(path)
    sid = args.source_id
    if sid not in [r["source_id"] for r in registry.sources()]:
        raise SourceCommandError(EXIT_VALIDATION, UNKNOWN_SOURCE)
    status = _prepare_retry(registry, sid)
    rec = registry.get(sid)
    row = {"source_id": sid, "kind": rec["kind"], "status": status, "reason": None, "snapshot_id": None}
    if status != "DECLARED":
        row["reason"] = "already final; not fetched"
        _emit(args, {"results": [row]}, _row_lines([row]))
        return EXIT_OK
    store = BlobStore(home / SNAPSHOT_DIR)
    try:
        result = fetch(rec, store, allow_network=True, expected_sha256=args.sha256)
    except SourceError as exc:
        new_status, reason = _failure_transition(rec["kind"], exc)
        registry.transition(sid, new_status, failure_reason=reason)
        _audit(home, "source_failed", sid, code=exc.code)
        row.update(status=new_status, reason=reason)
    else:
        registry.transition(sid, "RETRIEVED", checksum=result["sha256"], retrieved_at=result["retrieved_at"])
        _audit(home, "source_acquired", sid, sha256=result["sha256"])
        row.update(status="RETRIEVED")
    _save(path, registry, extras)
    _emit(args, {"results": [row]}, _row_lines([row]))
    return EXIT_SOURCE_UNAVAILABLE if row["status"] in ("FAILED", "UNAVAILABLE") else EXIT_OK


_HANDLERS = {
    "add": cmd_add, "list": cmd_list, "show": cmd_show, "remove": cmd_remove,
    "acquire": cmd_acquire, "verify": cmd_verify, "fetch": cmd_fetch,
}


def _guarded(handler):
    def run(args) -> int:
        try:
            return handler(args)
        except SourceCommandError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return exc.code
        except RegistryError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return EXIT_VALIDATION
        except SourceError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return EXIT_SOURCE_UNAVAILABLE
    return run


def _common(parser) -> None:
    parser.add_argument("--registry", default=None, metavar="FILE", help="source registry file (default ./sources.json)")
    parser.add_argument("--kb-home", default=None, metavar="PATH", help="kb-home directory")
    parser.add_argument("--json", action="store_true", help="canonical JSON output")
    parser.add_argument("--quiet", action="store_true", help="no human output")


def register(subparsers) -> None:
    group = subparsers.add_parser("source", help="knowledge sources: registry, acquisition, verification, fetch")
    verbs = group.add_subparsers(dest="source_action", required=True)

    add = verbs.add_parser("add", help="register a source from a spec file")
    add.add_argument("--file", required=True, metavar="SPEC")
    show = verbs.add_parser("show", help="show one source")
    show.add_argument("source_id")
    remove = verbs.add_parser("remove", help="remove a source from the registry")
    remove.add_argument("source_id")
    verbs.add_parser("list", help="list registered sources")
    acquire = verbs.add_parser("acquire", help="snapshot sources from local inputs (offline)")
    acquire.add_argument("source_ids", nargs="*", metavar="ID")
    acquire.add_argument("--i-am-entitled", action="store_true",
                         help="declare an Enterprise entitlement for ENTERPRISE_LOCAL sources")
    verify = verbs.add_parser("verify", help="re-hash the blobs of retrieved sources")
    verify.add_argument("source_ids", nargs="*", metavar="ID")
    fetch_p = verbs.add_parser("fetch", help="retrieve a remote allow-listed source (network)")
    fetch_p.add_argument("source_id")
    fetch_p.add_argument("--allow-network", action="store_true", help="required: permit this one network retrieval")
    fetch_p.add_argument("--sha256", default=None, metavar="HEX", help="expected sha256 of the retrieved bytes")

    for name, leaf in verbs.choices.items():
        _common(leaf)
        leaf.set_defaults(kap_handler=_guarded(_HANDLERS[name]))
