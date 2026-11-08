"""`odooflux knowledge candidates ...` and `odooflux knowledge ai propose` (feature 011, T061; contracts/cli-surface.md,
candidate-rule-generation.md; REQ-KAP-016, REQ-KAP-017).

Verbs: candidates generate | list | accept | reject | resolve, and ai propose. Every verb takes `--path TREE`.

Store, inside the working tree (the loader never reads `candidates/`, so nothing here is verified knowledge):
- `candidates/CR-*.json`: candidate rules (status PROPOSED, CONFLICT, ACCEPTED or REJECTED);
- `candidates/evidence/EV-*.json`: evidence of pending candidates; accept moves it into `evidence/` through ops;
- `candidates/ai/CR-*.json`: AI proposals (origin AI_PROPOSED), never acted on by any verb here;
- `candidates/conflicts.json`: conflicts recorded by generate (written by authoring/conflicts).

Rules of this module:
- the shipped knowledge tree is refused for every write verb (exit 2);
- generate needs the bindable detector table (`registries.extract_toolkit`); without it, exit 2;
- accept goes only through `knowledge/candidates/accept.py` (its detectors_verified and evidence checks apply);
- AI is off unless `--ai` is given (cli/ai_options.py rules: consent, provider, model, job budget, grants, kill
  switch). The gateway factory is attached by the composition root as `registries.ai_gateway_factory`; this module
  never imports `odooflux.ai`. Without that attachment `ai propose` exits 2.

Exit codes (cli/kap_common.py): 0 ok, 1 refused or validation failure, 2 usage.
"""

import json
import os
import re
import sys
from pathlib import Path

from odooflux.cli import ai_options
from odooflux.cli.kap_common import EXIT_OK, EXIT_USAGE, attached
from odooflux.knowledge.authoring import conflicts
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates import ai_proposer as ap
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.candidates.templates import load_templates
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import is_builtin_path
from odooflux.knowledge.release.canonical import write_json_file

PENDING = ("PROPOSED", "CONFLICT")
CANDIDATE_ID = re.compile(r"^CR-[0-9a-f]{16}$")
SOURCE_KEYS = ("source_id", "official", "url", "branch", "revision")
KEEP = ("manual", "candidate", "both-renamed")


class _Usage(Exception):
    """A usage error: refused before any work (exit 2)."""


def _guard(handler):
    """Usage errors exit 2; refused or invalid operations (ValueError subclasses) exit 1."""
    def run(args) -> int:
        try:
            return handler(args) or EXIT_OK
        except _Usage as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return run


def _is_builtin(path: Path) -> bool:
    return is_builtin_path(path)


def _tree(args, *, write: bool) -> Path:
    tree = Path(args.path)
    if write and _is_builtin(tree):
        raise _Usage("refusing to write the shipped knowledge tree; use a staging tree (--path)")
    if not tree.is_dir():
        raise _Usage(f"no knowledge tree at {tree}")
    return tree


def _store(tree: Path) -> Path:
    return tree / "candidates"


def _toolkit(args):
    toolkit = attached(args, "extract_toolkit")
    if toolkit is None:
        raise _Usage("candidates need the bindable detector table (extract_toolkit), which this run was started without")
    return toolkit


def _read_json(path: Path, what: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage(f"cannot read {what} {path.name}: {exc}") from None


def _ledger(path, at=None) -> Ledger:
    """The ledger at `path`, verified. With `at`, history entries written by this run carry that time (pinned runs
    are byte-identical); without it the ledger uses its own clock."""
    loaded = Ledger.load(path)
    findings = loaded.verify()
    if findings:
        raise ValueError(f"ledger {Path(path).name} does not verify: {findings[0]['code']}")
    if not at:
        return loaded
    body = loaded.to_dict()
    entries = {entry["change_id"]: entry for entry in body["entries"]}
    return Ledger(body["step"], body["from"], body["to"], entries, clock=lambda: at)


def _source(path) -> dict:
    spec = _read_json(Path(path), "source spec")
    if not isinstance(spec, dict) or any(k not in spec for k in SOURCE_KEYS):
        raise _Usage(f"source spec needs {', '.join(SOURCE_KEYS)}")
    try:
        return eb.resolve_source(spec)
    except eb.SourceIdentityError as exc:
        raise _Usage(str(exc)) from None


def _candidates(tree: Path) -> list:
    store = _store(tree)
    return [_read_json(p, "candidate") for p in sorted(store.glob("CR-*.json"))] if store.is_dir() else []


def _candidate(tree: Path, cid: str) -> dict:
    if not CANDIDATE_ID.match(cid or ""):
        raise ValueError(f"no candidate {cid!r}")
    path = _store(tree) / f"{cid}.json"
    if not path.is_file():
        raise ValueError(f"no candidate {cid} in {_store(tree)}")
    return _read_json(path, "candidate")


def _write_candidate(tree: Path, cand: dict, *, update: bool = False) -> None:
    """Write one candidate record. An existing record is refused unless `update` is set, and only the status
    transition verbs (accept, reject, resolve) pass update=True. Generation never overwrites a record."""
    path = _store(tree) / f"{cand['candidate_id']}.json"
    if path.is_file() and not update:
        raise ValueError(f"candidate {cand['candidate_id']} already exists in {_store(tree)}; refusing to overwrite "
                         "it (nothing was written)")
    write_json_file(path, cand)


def _pending_evidence(tree: Path, ids=None) -> list:
    folder = _store(tree) / "evidence"
    if not folder.is_dir():
        return []
    records = [_read_json(p, "evidence") for p in sorted(folder.glob("EV-*.json"))]
    return [r for r in records if ids is None or r.get("id") in ids]


def _emit(args, payload, lines) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        for line in lines:
            print(line)


def _generate(args) -> int:
    toolkit = _toolkit(args)
    tree = _tree(args, write=True)
    pending = [c for c in _candidates(tree) if c.get("status") in PENDING]
    if pending:
        raise ValueError(f"{len(pending)} pending candidate(s) in {_store(tree)}: accept or reject them before "
                         "generating again")
    ledger_path = Path(args.ledger)
    ledger = _ledger(ledger_path, args.at)
    source = _source(args.source)
    templates = load_templates(known_detectors=toolkit.detectors)
    result = gen.generate(ledger, tree_root=tree, source=source, checked_on=args.checked_on, templates=templates,
                          known_detectors=toolkit.detectors)
    reserved = {r["id"] for r in _pending_evidence(tree)}
    clash = sorted({e["id"] for e in result["evidence"]} & reserved)
    if clash:
        raise ValueError(f"evidence ids {clash} are held by earlier candidates; ids are never reused, so nothing "
                         "was written")
    gen.apply_dispositions(ledger, result, tree_root=tree)
    store = _store(tree)
    (store / "evidence").mkdir(parents=True, exist_ok=True)
    for record in result["evidence"]:
        write_json_file(store / "evidence" / f"{record['id']}.json", record)
    for cand in result["candidates"]:
        _write_candidate(tree, cand)
    if result["conflicts"]:
        conflicts.write_conflicts(store, result["conflicts"])
    ledger.save(ledger_path)
    summary = {"candidates": len(result["candidates"]), "evidence": len(result["evidence"]),
               "linked": len(result["linked"]), "skipped": len(result["skipped"]),
               "existing": len(result["existing"]), "conflicts": len(result["conflicts"]),
               "detectors_verified": result["detectors_verified"],
               "candidate_ids": [c["candidate_id"] for c in result["candidates"]]}
    _emit(args, summary, [f"generated {summary['candidates']} candidate(s), {summary['evidence']} evidence "
                          f"record(s), {summary['linked']} linked, {summary['skipped']} skipped, "
                          f"{summary['existing']} existing, {summary['conflicts']} conflict(s)"]
          + [f"  {c['candidate_id']} {c['change_id']}" for c in result["candidates"]])
    return EXIT_OK


def _list(args) -> int:
    tree = _tree(args, write=False)
    rows = [{"candidate_id": c["candidate_id"], "status": c["status"], "change_id": c["change_id"],
             "template_id": c.get("template_id"), "rule_id": c["rule"]["id"]} for c in _candidates(tree)]
    _emit(args, rows, [f"{r['candidate_id']} {r['status']} {r['rule_id']}" for r in rows])
    return EXIT_OK


def _accept(args) -> int:
    tree = _tree(args, write=True)
    cand = _candidate(tree, args.candidate_id)
    ledger_path = Path(args.ledger)
    ledger = _ledger(ledger_path, args.at)
    evidence = _pending_evidence(tree, set(cand.get("rule", {}).get("evidence") or []))
    try:
        summary = acc.accept(tree, cand, ledger=ledger, evidence=evidence, author=args.author, at=args.at)
    except acc.AcceptError:
        if cand.get("status") == "CONFLICT":
            _write_candidate(tree, cand, update=True)
        raise
    ledger.save(ledger_path)
    _write_candidate(tree, cand, update=True)
    for record in evidence:
        (_store(tree) / "evidence" / f"{record['id']}.json").unlink(missing_ok=True)
    _emit(args, summary, [f"accepted {summary['candidate_id']} as rule {summary['rule_id']} "
                          f"(evidence {', '.join(summary['evidence_ids'])})"])
    return EXIT_OK


def _reject(args) -> int:
    tree = _tree(args, write=True)
    cand = _candidate(tree, args.candidate_id)
    if cand.get("status") not in PENDING:
        raise ValueError(f"candidate is {cand.get('status')}; only PROPOSED or CONFLICT candidates are rejected")
    cand["status"] = "REJECTED"
    cand["rejected_reason"] = args.reason
    _write_candidate(tree, cand, update=True)
    _emit(args, {"candidate_id": cand["candidate_id"], "status": "REJECTED"},
          [f"rejected {cand['candidate_id']}"])
    return EXIT_OK


def _resolve(args) -> int:
    tree = _tree(args, write=True)
    cand = _candidate(tree, args.candidate_id)
    if not (_store(tree) / conflicts.CONFLICTS_FILE).is_file():
        raise ValueError(f"no conflict recorded for {cand['candidate_id']}")
    record = conflicts.resolve(_store(tree), tree=tree, candidate_id=cand["candidate_id"], keep=args.keep,
                               author=args.author, at=args.at)
    if args.keep == "manual":
        cand["status"] = "REJECTED"
        cand["rejected_reason"] = "manual rule wins (conflict resolved)"
    elif cand.get("status") == "CONFLICT":
        cand["status"] = "PROPOSED"  # accept re-checks the collision and refuses while it still exists
    _write_candidate(tree, cand, update=True)
    _emit(args, record, [f"resolved {cand['candidate_id']}: keep {args.keep}"])
    return EXIT_OK


def _ai_propose(args) -> int:
    tree = _tree(args, write=True)
    cfg, error = ai_options.resolve_ai(args, os.environ)
    if error:
        raise _Usage(error)
    if not cfg.enabled:
        raise _Usage("ai propose needs --ai (AI is off by default)")
    toolkit = _toolkit(args)
    if cfg.kill_switch:
        raise ValueError("the AI kill switch is on (--ai-disable-external or ODOOFLUX_AI_DISABLE_EXTERNAL): no "
                         "transmission, no proposals")
    factory = attached(args, "ai_gateway_factory")
    if factory is None:
        raise _Usage("AI gateway is not attached to this run (the composition root attaches ai_gateway_factory); "
                     "AI proposals are unavailable")
    gateway, authorizer = factory(cfg.to_dict())
    ledger = _ledger(Path(args.ledger))
    templates = load_templates(known_detectors=toolkit.detectors)
    result = ap.propose(_candidates(tree), evidence=_pending_evidence(tree), changes=ledger.records(),
                        gateway=gateway, authorizer=authorizer, config=cfg.to_dict(),
                        template_ids=[t["template_id"] for t in templates])
    if result["status"] == "denied":
        raise ValueError("AI denied: no grant for " + ", ".join(result["missing"]) + "; authorize it with "
                         "--ai-authorize PROVIDER=evidence_excerpt")
    if result["proposals"]:
        (_store(tree) / "ai").mkdir(parents=True, exist_ok=True)
    for item in result["proposals"]:
        write_json_file(_store(tree) / "ai" / f"{item['candidate_id']}.json", item)
    summary = {"status": result["status"], "proposals": len(result["proposals"]),
               "discarded": result["discarded"], "denied": result["denied"], "skipped": result["skipped"]}
    _emit(args, summary, [f"AI proposals: {summary['proposals']} stored under candidates/ai, "
                          f"{len(result['discarded'])} discarded, {len(result['denied'])} denied"])
    return EXIT_OK


def _verb(parent, name, handler, help_text, *, writes=False):
    parser = parent.add_parser(name, help=help_text)
    parser.add_argument("--path", required=True, metavar="TREE", help="knowledge working tree")
    parser.add_argument("--json", action="store_true", help="canonical JSON output")
    if writes:
        parser.add_argument("--author", default=None, help="actor name (default: git config user.name)")
    parser.set_defaults(kap_handler=_guard(handler))
    return parser


def register(sub) -> None:
    group = sub.add_parser("candidates", help="candidate rules from a change ledger (contracts/candidate-rule-generation.md)")
    verbs = group.add_subparsers(dest="candidates_verb", required=True)

    p = _verb(verbs, "generate", _generate, "turn a ledger into candidate rules (DETECT_ONLY or DRAFT)", writes=True)
    p.add_argument("--ledger", required=True, metavar="FILE")
    p.add_argument("--source", required=True, metavar="FILE", help="source spec JSON of the ledger's source")
    p.add_argument("--checked-on", dest="checked_on", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--at", default=None, metavar="ISO-TIME", help="timestamp for ledger history (default: ledger clock)")

    _verb(verbs, "list", _list, "list candidates and their status")

    p = _verb(verbs, "accept", _accept, "accept one PROPOSED candidate (validator, checks, rule and history)",
              writes=True)
    p.add_argument("candidate_id", metavar="CR-ID")
    p.add_argument("--ledger", required=True, metavar="FILE")
    p.add_argument("--at", default=None, metavar="ISO-TIME", help="timestamp for the rule history (default: now)")

    p = _verb(verbs, "reject", _reject, "reject a PROPOSED or CONFLICT candidate with a reason", writes=True)
    p.add_argument("candidate_id", metavar="CR-ID")
    p.add_argument("--reason", required=True)

    p = _verb(verbs, "resolve", _resolve, "record the decision for a candidate in conflict", writes=True)
    p.add_argument("candidate_id", metavar="CR-ID")
    p.add_argument("--keep", required=True, choices=KEEP)
    p.add_argument("--at", default=None, metavar="ISO-TIME")

    ai = sub.add_parser("ai", help="optional AI proposals (off unless --ai; D-08 grants)")
    ai_verbs = ai.add_subparsers(dest="ai_verb", required=True)
    p = _verb(ai_verbs, "propose", _ai_propose, "propose candidate rationales and template hints (AI_PROPOSED)")
    p.add_argument("--ledger", required=True, metavar="FILE")
    ai_options.add_ai_arguments(p)
