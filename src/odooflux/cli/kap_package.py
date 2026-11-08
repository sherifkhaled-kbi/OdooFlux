"""`odooflux knowledge package ...` (contracts/cli-surface.md, contracts/knowledge-package-format.md; REQ-KAP-022, 024,
027).

Verbs: export ID -o FILE, validate FILE [--expect-digest], import FILE [--activate] [--downgrade-unverified]
[--expect-digest], list FILE, inspect FILE.

`validate`, `list` and `inspect` install nothing: they stream into a scratch directory that is removed afterwards.
`import` goes through `knowledge/package/importer.py`, which is atomic and leaves kb-home unchanged on any refusal.
Exit codes come from `cli/kap_common.py`: 0 ok, 1 unknown release or lock held, 3 package rejected, 5 integrity.
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

from odooflux.cli.kap_common import EXIT_INTEGRITY, EXIT_OK, EXIT_PACKAGE_REJECTED, EXIT_VALIDATION
from odooflux.cli.kap_release import ReleaseCommandError, _release_dir
from odooflux.knowledge.package.archive import PackageError, read_package_archive
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.importer import import_package
from odooflux.knowledge.package.validate import validate_package
from odooflux.knowledge.release.audit import KbAudit
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.resolver import HOME_ENV, default_kb_home
from odooflux.knowledge.release.store import KbLockedError
from odooflux.utils.redaction import redact_text


def _home(args) -> Path:
    return Path(args.kb_home or os.environ.get(HOME_ENV) or default_kb_home())


def _emit(args, payload, lines) -> None:
    if args.json:
        sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")
    elif not args.quiet:
        for line in lines:
            print(line)


def cmd_export(args) -> int:
    home = _home(args)
    release_dir = _release_dir(home, args.release_id)
    info = export_package(release_dir, args.output, include_enterprise_derived=args.include_enterprise_derived)
    KbAudit(home, uuid.uuid4().hex).record("package_exported", target=info.release_id, details={"sha256": info.sha256})
    payload = {"release_id": info.release_id, "release_digest": info.release_digest, "sha256": info.sha256,
               "entry_count": info.entry_count, "total_size": info.total_size,
               "contains_enterprise_derived": info.contains_enterprise_derived}
    _emit(args, payload, [f"exported {info.release_id} sha256={info.sha256} entries={info.entry_count}"])
    return EXIT_OK


def cmd_validate(args) -> int:
    with tempfile.TemporaryDirectory() as scratch:
        validated = validate_package(args.file, scratch, expect_digest=args.expect_digest)
        payload = {"valid": True, "release_id": validated.release_id, "release_digest": validated.release_digest,
                   "entry_count": len(validated.manifest["entries"])}
    _emit(args, payload, [f"valid {validated.release_id} {validated.release_digest}"])
    return EXIT_OK


def cmd_import(args) -> int:
    result = import_package(args.file, _home(args), activate=args.activate,
                            downgrade_unverified=args.downgrade_unverified, expect_digest=args.expect_digest)
    payload = {"release_id": result.release_id, "release_digest": result.release_digest,
               "installed": result.installed, "activated": result.activated,
               "downgraded_rules": list(result.downgraded_rules)}
    lines = [f"imported {result.release_id} installed={result.installed} activated={result.activated}"]
    if result.downgraded_rules:
        lines.append("downgraded to DETECT_ONLY: " + ", ".join(result.downgraded_rules))
    _emit(args, payload, lines)
    return EXIT_OK


def _read_package(file):
    with tempfile.TemporaryDirectory() as scratch:
        staged = read_package_archive(file, scratch)
        return dict(staged.manifest), list(staged.entries)


def cmd_list(args) -> int:
    _, entries = _read_package(args.file)
    rows = [{"path": e.path, "size": e.size, "sha256": e.sha256} for e in entries]
    _emit(args, {"entries": rows}, [f"{r['sha256']}  {r['size']:>10}  {r['path']}" for r in rows])
    return EXIT_OK


def cmd_inspect(args) -> int:
    manifest, _ = _read_package(args.file)
    payload = {"verified": False, "format": manifest.get("format"), "release_id": manifest.get("release_id"),
               "release_digest": manifest.get("release_digest"), "created_with": manifest.get("created_with"),
               "compat": manifest.get("compat"), "entry_count": manifest.get("entry_count"),
               "total_size": manifest.get("total_size"),
               "contains_enterprise_derived": manifest.get("contains_enterprise_derived"),
               "redaction_scan": manifest.get("redaction_scan")}
    lines = ["declared by package.json (not verified; run `package validate`)"]
    lines += [f"{key}: {value}" for key, value in payload.items() if key != "verified"]
    _emit(args, payload, lines)
    return EXIT_OK


def _guarded(handler):
    def run(args) -> int:
        try:
            return handler(args)
        except PackageError as exc:
            print(f"ERROR: {redact_text(str(exc))}", file=sys.stderr)
            return EXIT_PACKAGE_REJECTED
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
    group = subparsers.add_parser("package", help="knowledge release packages (.ofkp)")
    verbs = group.add_subparsers(dest="package_action", required=True)

    export = verbs.add_parser("export", help="write a deterministic package for an installed release")
    export.add_argument("release_id")
    export.add_argument("-o", "--output", required=True, metavar="FILE")
    export.add_argument("--include-enterprise-derived", action="store_true")
    export.set_defaults(kap_handler=_guarded(cmd_export))
    _common(export)

    validate = verbs.add_parser("validate", help="check a package without installing it")
    validate.add_argument("file")
    validate.add_argument("--expect-digest", default=None, metavar="SHA")
    validate.set_defaults(kap_handler=_guarded(cmd_validate))
    _common(validate)

    imp = verbs.add_parser("import", help="verify, gate and install a package (atomic)")
    imp.add_argument("file")
    imp.add_argument("--activate", action="store_true")
    imp.add_argument("--downgrade-unverified", action="store_true",
                     help="cap unverified FIX_ENABLED rules to DETECT_ONLY instead of refusing")
    imp.add_argument("--expect-digest", default=None, metavar="SHA")
    imp.set_defaults(kap_handler=_guarded(cmd_import))
    _common(imp)

    lst = verbs.add_parser("list", help="list the entries of a package")
    lst.add_argument("file")
    lst.set_defaults(kap_handler=_guarded(cmd_list))
    _common(lst)

    insp = verbs.add_parser("inspect", help="show the package.json summary (declared, not verified)")
    insp.add_argument("file")
    insp.set_defaults(kap_handler=_guarded(cmd_inspect))
    _common(insp)
