"""`odooflux knowledge extract` and `odooflux knowledge ledger ...` (contracts/cli-surface.md, change-ledger.md;
REQ-KAP-014, REQ-KAP-012, REQ-KAP-013).

- `extract --from SNAP --to SNAP --step NN-NN --blobs DIR --out DIR [--scope GLOB]...`: diff one snapshot pair (snapshot
  JSON files, blobs read from DIR), write `NN-NN.ledger.json` and `NN-NN.accounting.json`. An existing ledger for the same
  pair is merged (dispositions kept); a ledger for another pair or one that fails `verify` is refused. The ledger clock is
  the target snapshot's `created_at`, so a rerun writes identical bytes.
- `ledger list|show|set-disposition|confirm|verify --ledger FILE`: act on one ledger file.
  `confirm` is the only way a RENAMED_CANDIDATE or REPLACEMENT_CANDIDATE becomes confirmed. It runs as MANUAL, needs a
  `--reviewer` name (AI names are refused), and records that reviewer in the history. Nothing here confirms automatically.

Exit codes (cli/kap_common): 0 ok, 1 refused or invalid (rationale missing, unknown rule, invariant broken), 2 usage.
"""

import json
import sys
from pathlib import Path

from odooflux.cli.kap_common import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, attached
from odooflux.knowledge.acquisition.blobstore import BlobStore
from odooflux.knowledge.extract import driver
from odooflux.knowledge.extract.accounting import AccountingError
from odooflux.knowledge.ledger import dispositions as disp
from odooflux.knowledge.ledger.dispositions import DISPOSITIONS, DispositionError
from odooflux.knowledge.ledger.ledger import Ledger, LedgerError
from odooflux.knowledge.release.canonical import canonical_bytes, write_json_file
from odooflux.knowledge.release.confidentiality_view import (
    WITHHELD_PATH, active_enterprise_snapshot_ids, redact_change_record)
from odooflux.knowledge.release.model import KnowledgeReleaseError

__all__ = ["register", "full_registry", "cmd_extract"]

SNAPSHOT_KEYS = ("snapshot_id", "snapshot_digest", "entries", "created_at")


class _Usage(Exception):
    """A missing or malformed input the user must fix (exit 2)."""


def full_registry() -> list:
    """Alias kept for callers: every extractor is `driver.default_registry()`."""
    return driver.default_registry()


def _load_snapshot(path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage(f"cannot read snapshot {path}: {exc}") from exc
    if not isinstance(doc, dict) or any(k not in doc for k in SNAPSHOT_KEYS):
        raise _Usage(f"{path} is not a snapshot document (needs {', '.join(SNAPSHOT_KEYS)})")
    return doc


def _open_ledger(path) -> Ledger:
    ledger = Ledger.load(path)
    findings = ledger.verify()
    if findings:
        raise LedgerError(f"ledger {Path(path).name} does not verify: {findings[0]['code']}")
    return ledger


def _emit(args, payload, lines) -> None:
    if args.quiet:
        return
    if args.json:
        sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")
    else:
        for line in lines:
            print(line)


def cmd_extract(args) -> int:
    toolkit = attached(args, "extract_toolkit")
    if toolkit is None:
        raise _Usage("extract needs the document adapters, which this run was started without")
    from_snap, to_snap = _load_snapshot(args.from_snapshot), _load_snapshot(args.to_snapshot)
    if not args.blobs:
        raise _Usage("--blobs DIR is required")
    store = BlobStore(Path(args.blobs))
    result = driver.extract_pair(from_snap, to_snap, args.scope, full_registry(), store=store, step=args.step,
                                 toolkit=toolkit)
    ledger = Ledger.create(args.step, from_snap, to_snap, result.drafts, clock=lambda: to_snap["created_at"])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / f"{args.step}.ledger.json"
    merged = None
    if ledger_path.exists():
        previous = _open_ledger(ledger_path)
        if (previous.from_id, previous.to_id) != (ledger.from_id, ledger.to_id):
            raise LedgerError("the existing ledger is for another snapshot pair; refusing to merge")
        ledger, merged = disp.merge(ledger, previous)
    ledger.save(ledger_path)
    write_json_file(out / f"{args.step}.accounting.json", result.accounting)
    classes = {}
    for record in ledger.records():
        classes[record["class"]] = classes.get(record["class"], 0) + 1
    payload = {"ledger": str(ledger_path), "records": len(ledger.records()), "classes": classes,
               "totals": result.accounting["totals"], "merge": None if merged is None else {
                   k: merged[k] for k in ("added", "kept", "stale", "conflicts")}}
    _emit(args, payload, [f"ledger: {ledger_path}", f"records: {payload['records']}",
                          f"classes: {canonical_bytes(classes).decode('utf-8')}",
                          f"files: {canonical_bytes(result.accounting['totals']).decode('utf-8')}"])
    return EXIT_OK


def cmd_list(args) -> int:
    ledger = _open_ledger(args.ledger)
    try:  # Enterprise symbol names of the active release are withheld; an unresolvable release refuses
        enterprise = active_enterprise_snapshot_ids(args.kb_home)
    except KnowledgeReleaseError as exc:
        raise LedgerError(f"active knowledge release cannot be verified, so ledger list is refused: {exc}") from exc
    rows = [redact_change_record(r, enterprise) for r in ledger.records()
            if (args.class_name is None or r["class"] == args.class_name)
            and (args.disposition is None or r["disposition"] == args.disposition)]
    lines = [f"{r['change_id']} {r['class']} {r['disposition']} {r['domain']} {r['subject_key']}" for r in rows]
    _emit(args, {"changes": [{"change_id": r["change_id"], "class": r["class"], "disposition": r["disposition"],
                              "domain": r["domain"], "subject_key": r["subject_key"]} for r in rows]},
          lines or ["no changes"])
    return EXIT_OK


def cmd_show(args) -> int:
    ledger = _open_ledger(args.ledger)
    try:  # Enterprise locations and detail of the active release are withheld; an unresolvable release refuses
        enterprise = active_enterprise_snapshot_ids(args.kb_home)
    except KnowledgeReleaseError as exc:
        raise LedgerError(f"active knowledge release cannot be verified, so ledger show is refused: {exc}") from exc
    record = redact_change_record(ledger.get(args.change_id), enterprise)
    if args.json:
        sys.stdout.write(canonical_bytes(record).decode("utf-8") + "\n")
    else:
        for key in ("change_id", "class", "domain", "subject_key", "disposition", "confirmed", "proposed_by"):
            print(f"{key}: {record[key]}")
        for loc in record["locations"]:
            if loc["path"] == WITHHELD_PATH:
                print(f"location: {loc['snapshot_id']} {WITHHELD_PATH}")
            else:
                print(f"location: {loc['snapshot_id']} {loc['path']}:{loc['line']}")
    return EXIT_OK


def _known_rules(path):
    if not path:
        return {}
    try:
        rules = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage(f"cannot read --known-rules {path}: {exc}") from exc
    if not isinstance(rules, dict):
        raise _Usage("--known-rules must be a JSON object mapping rule id to maturity")
    return rules


def cmd_set_disposition(args) -> int:
    ledger = _open_ledger(args.ledger)
    record = disp.set_disposition(ledger, args.change_id, args.disposition, actor=args.actor,
                                  rationale=args.rationale, rule_ids=args.rule_id, evidence_ids=args.evidence_id,
                                  known_rules=_known_rules(args.known_rules), reviewer=args.reviewer)
    ledger.save(args.ledger)
    _emit(args, {"change_id": record["change_id"], "disposition": record["disposition"]},
          [f"{record['change_id']}: {record['disposition']}"])
    return EXIT_OK


def cmd_confirm(args) -> int:
    reviewer = (args.reviewer or "").strip()
    if not reviewer or reviewer in disp.AI_ACTORS or reviewer == disp.MANUAL:
        raise DispositionError("confirm needs the name of a human reviewer (not an AI actor or MANUAL)")
    ledger = _open_ledger(args.ledger)
    before = ledger.get(args.change_id)
    disp.confirm(ledger, args.change_id, actor=disp.MANUAL)
    ledger.append_history(args.change_id, actor=reviewer, action="confirm_reviewer", from_value=before["class"],
                          to_value=reviewer)
    ledger.save(args.ledger)
    _emit(args, {"change_id": args.change_id, "confirmed": True, "reviewer": reviewer},
          [f"{args.change_id} confirmed by {reviewer}"])
    return EXIT_OK


def cmd_verify(args) -> int:
    ledger = Ledger.load(args.ledger)
    findings = ledger.verify()
    lines = [f"{f['code']} {f['change_id'] or '-'} {f['detail']}" for f in findings] or ["ledger verifies"]
    _emit(args, {"findings": findings}, lines)
    return EXIT_OK if not findings else EXIT_VALIDATION


_HANDLERS = {"list": cmd_list, "show": cmd_show, "set-disposition": cmd_set_disposition,
             "confirm": cmd_confirm, "verify": cmd_verify}


def _guarded(handler):
    def run(args) -> int:
        try:
            return handler(args)
        except _Usage as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except (LedgerError, AccountingError, DispositionError, ValueError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_VALIDATION
    return run


def _common(parser) -> None:
    parser.add_argument("--kb-home", default=None, metavar="PATH", help="kb-home directory")
    parser.add_argument("--json", action="store_true", help="canonical JSON output")
    parser.add_argument("--quiet", action="store_true", help="no human output")


def register(subparsers) -> None:
    extract = subparsers.add_parser("extract", help="diff one snapshot pair into a change ledger")
    extract.add_argument("--from", dest="from_snapshot", required=True, metavar="SNAP")
    extract.add_argument("--to", dest="to_snapshot", required=True, metavar="SNAP")
    extract.add_argument("--step", required=True, metavar="NN-NN")
    extract.add_argument("--blobs", required=True, metavar="DIR", help="blob store holding the snapshot files")
    extract.add_argument("--out", required=True, metavar="DIR", help="where the ledger and accounting are written")
    extract.add_argument("--scope", action="append", default=None, metavar="GLOB")
    _common(extract)
    extract.set_defaults(kap_handler=_guarded(cmd_extract))

    group = subparsers.add_parser("ledger", help="inspect and decide on a change ledger")
    verbs = group.add_subparsers(dest="ledger_action", required=True)

    listing = verbs.add_parser("list", help="list changes")
    listing.add_argument("--ledger", required=True, metavar="FILE")
    listing.add_argument("--class", dest="class_name", default=None)
    listing.add_argument("--disposition", default=None, choices=DISPOSITIONS)

    show = verbs.add_parser("show", help="show one change")
    show.add_argument("change_id")
    show.add_argument("--ledger", required=True, metavar="FILE")

    setter = verbs.add_parser("set-disposition", help="set the disposition of one change")
    setter.add_argument("change_id")
    setter.add_argument("disposition", choices=DISPOSITIONS)
    setter.add_argument("--actor", required=True)
    setter.add_argument("--reviewer", default=None)
    setter.add_argument("--rationale", default=None)
    setter.add_argument("--rule-id", action="append", default=[])
    setter.add_argument("--evidence-id", action="append", default=[])
    setter.add_argument("--known-rules", default=None, metavar="FILE", help="JSON map of rule id to maturity")
    setter.add_argument("--ledger", required=True, metavar="FILE")

    confirm = verbs.add_parser("confirm", help="confirm a rename or replacement candidate (manual only)")
    confirm.add_argument("change_id")
    confirm.add_argument("--reviewer", required=True, help="the human confirming the candidate")
    confirm.add_argument("--ledger", required=True, metavar="FILE")

    verify = verbs.add_parser("verify", help="check the ledger invariants and history chain")
    verify.add_argument("--ledger", required=True, metavar="FILE")

    for name, leaf in verbs.choices.items():
        _common(leaf)
        leaf.set_defaults(kap_handler=_guarded(_HANDLERS[name]))
