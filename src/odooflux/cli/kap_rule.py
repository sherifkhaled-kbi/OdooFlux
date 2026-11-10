"""`odooflux knowledge rule ...` (contracts/manual-rule-cli.md, contracts/cli-surface.md; REQ-KAP-019, 018, 021).

Verbs: create, edit, disable, enable, retire, inspect, validate, history, link-evidence, add-test, promote, resolve.
Every verb takes `--path TREE` (required). Writes go through `knowledge/authoring/ops.py`, which validates the whole
tree and rolls back on a new error. This module adds three rules of its own:

- the shipped knowledge tree (and anything inside it) is refused for every write verb (exit 2);
- a created rule is MANUAL and DETECT_ONLY (or DRAFT), never carries a fixer, and its detector must resolve to a bindable
  generic detector with the parameters it accepts (`candidates/templates.py`);
- FIX_ENABLED is reachable only through `promote`, which needs an approval reference that is not the promoter's identity.

`--strict-builtin` makes the read-only verbs (`validate`, `inspect`) run the authoring checks on any tree, including the
shipped one. Exit codes come from `cli/kap_common.py`: 0 ok, 1 refused or validation failure, 2 usage.
"""

import argparse
import json
import sys
from pathlib import Path

from odooflux.cli.kap_common import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, attached
from odooflux.knowledge.authoring import conflicts, ops
from odooflux.knowledge.authoring import promote as promote_mod
from odooflux.knowledge.authoring.ops import TEST_KINDS
from odooflux.knowledge.candidates.templates import detector_params_problem
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.release.confidentiality_view import redact_kb_findings, redact_rule_rows
from odooflux.knowledge.release.safety import load_provenance_index

CREATE_CHOICES = ("DRAFT", "DETECT_ONLY")
RISKS = ("LOW", "MEDIUM", "HIGH")
SEVERITIES = ("CRITICAL", "WARNING", "INFO")
FIX_ENABLED = "FIX_ENABLED"


class _Usage(Exception):
    """A usage error: refused before any work (exit 2)."""


def _is_builtin(path: Path) -> bool:
    resolved = path.resolve()
    root = KNOWLEDGE_ROOT.resolve()
    return resolved == root or root in resolved.parents


def _tree(args, *, write: bool) -> Path:
    tree = Path(args.path)
    if write and _is_builtin(tree):
        raise _Usage("refusing to write the shipped knowledge tree; use a staging tree (--path)")
    if not tree.is_dir():
        raise _Usage(f"no knowledge tree at {tree}")
    return tree


def _json_object(text, what: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        raise _Usage(f"{what} must be a JSON object") from None
    if not isinstance(value, dict):
        raise _Usage(f"{what} must be a JSON object")
    return value


def _read_object(path: str, what: str) -> dict:
    try:
        return _json_object(Path(path).read_text(encoding="utf-8"), what)
    except OSError as exc:
        raise _Usage(f"cannot read {what}: {exc}") from None


def _parse_set(items) -> dict:
    changes = {}
    for item in items or []:
        if "=" not in item:
            raise _Usage(f"--set expects KEY=VALUE, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            changes[key] = json.loads(raw)
        except ValueError:
            changes[key] = raw
    return changes


def _emit(payload) -> None:
    print(json.dumps(payload, sort_keys=True, indent=2))


def _guard(handler):
    """Map usage errors to exit 2 and refused or invalid operations (ValueError subclasses) to exit 1."""
    def run(args) -> int:
        try:
            return handler(args) or EXIT_OK
        except _Usage as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_VALIDATION
    return run


def _create(args) -> int:
    toolkit = attached(args, "extract_toolkit")
    if toolkit is None:
        raise _Usage("rule create needs the bindable detector table, which this run was started without")
    tree = _tree(args, write=True)
    if args.from_file:
        row = _read_object(args.from_file, "rule file")
    else:
        missing = [flag for flag, value in (("--id", args.id), ("--step", args.step), ("--category", args.category),
                                            ("--detector-ref", args.detector_ref)) if not value]
        if missing:
            raise _Usage(f"create needs {', '.join(missing)} (or --from-file)")
        row = {"id": args.id, "step": args.step, "category": args.category, "detector_ref": args.detector_ref,
               "params": _json_object(args.params, "--params"), "risk": args.risk, "severity": args.severity,
               "maturity": args.maturity}
        if args.file_kinds:
            row["file_kinds"] = [k for k in args.file_kinds.split(",") if k]
        if args.message:
            row["message"] = args.message
        if args.suggestion:
            row["suggestion"] = args.suggestion
    if args.fixer_ref or row.get("fixer_ref") is not None:
        raise _Usage("a rule created through the CLI never carries a fixer_ref (promote is the only path)")
    row.setdefault("fixer_ref", None)
    row.setdefault("risk", "LOW")
    row.setdefault("severity", "WARNING")
    row.setdefault("maturity", "DETECT_ONLY")
    if row["maturity"] not in CREATE_CHOICES:
        raise ValueError(f"a new rule starts as one of {CREATE_CHOICES}, not {row['maturity']}")
    problem = detector_params_problem(row.get("detector_ref"), (row.get("params") or {}).keys(), toolkit.detectors)
    if problem:
        raise ValueError(problem)
    created = ops.create_rule(tree, row, evidence=args.evidence or (), author=args.author)
    print(f"created {created['id']} (origin MANUAL, maturity {created['maturity']})")
    return EXIT_OK


def _edit(args) -> int:
    tree = _tree(args, write=True)
    changes = _read_object(args.from_file, "edit file") if args.from_file else {}
    changes.update(_parse_set(args.set))
    row = ops.edit_rule(tree, args.id, changes, author=args.author)
    print(f"edited {args.id} (rev {row['rev']})")
    return EXIT_OK


def _disable(args) -> int:
    row = ops.disable_rule(_tree(args, write=True), args.id, reason=args.reason, author=args.author)
    print(f"disabled {args.id} (rev {row['rev']})")
    return EXIT_OK


def _enable(args) -> int:
    row = ops.enable_rule(_tree(args, write=True), args.id, author=args.author)
    print(f"enabled {args.id} (rev {row['rev']}, maturity {row['maturity']})")
    return EXIT_OK


def _retire(args) -> int:
    row = ops.retire_rule(_tree(args, write=True), args.id, reason=args.reason, author=args.author,
                          superseded_by=args.superseded_by)
    print(f"retired {args.id} (rev {row['rev']})")
    return EXIT_OK


def _inspect(args) -> int:
    tree = _tree(args, write=False)
    report = ops.inspect_rule(tree, args.id)
    report["rule"] = redact_rule_rows(load_knowledge(tree), [report["rule"]])[0]  # Enterprise-derived text withheld
    if args.json:
        _emit(report)
        return EXIT_OK
    print(f"id: {args.id}")
    print(f"file: {report['file']}")
    print(f"maturity: {report['rule'].get('maturity')}")
    for ref, status in sorted(report["evidence"].items()):
        print(f"evidence: {ref} {status}")
    head = report["history_head"]
    print(f"history: {head['rev']} {head['action']} by {head['actor']}" if head
          else f"history: {report['history_problem']}")
    for line in report["validation"]:
        print(f"validation: {line}")
    return EXIT_OK


def _validate(args) -> int:
    tree = _tree(args, write=False)
    kb = load_knowledge(tree)
    findings = redact_kb_findings(kb, validate_knowledge(kb, strict_builtin=args.strict_builtin),
                                  load_provenance_index(tree))
    if args.id:
        findings = [f for f in findings if f.pointer == args.id]
    for finding in findings:
        print(finding.line())
    errors = sum(1 for f in findings if f.severity == "ERROR")
    warnings = sum(1 for f in findings if f.severity == "WARNING")
    print(f"records={len(kb.evidence)} rules={len(kb.rules)} errors={errors} warnings={warnings}")
    return EXIT_VALIDATION if errors else EXIT_OK


def _history(args) -> int:
    doc = ops.history_rule(_tree(args, write=False), args.id)
    if args.json:
        _emit(doc)
        return EXIT_OK
    for entry in doc["entries"]:
        print(f"rev={entry['rev']} action={entry['action']} at={entry['at']} actor={entry['actor']} "
              f"summary={entry['summary']}")
    print("chain: verified")
    return EXIT_OK


def _link_evidence(args) -> int:
    row = ops.link_evidence(_tree(args, write=True), args.id, args.evidence, author=args.author)
    print(f"linked {args.evidence} to {args.id} (rev {row['rev']})")
    return EXIT_OK


def _add_test(args) -> int:
    row = ops.add_test(_tree(args, write=True), args.id, kind=args.kind, fixture=args.fixture, author=args.author)
    print(f"added {args.kind} test to {args.id} (rev {row['rev']})")
    return EXIT_OK


def _promote(args) -> int:
    row = promote_mod.promote(_tree(args, write=True), args.id, approval=args.approval, author=args.author)
    print(f"promoted {args.id} to {row['maturity']} (approval recorded)")
    return EXIT_OK


def _resolve(args) -> int:
    result = conflicts.resolve(Path(args.build_dir), tree=_tree(args, write=True), candidate_id=args.candidate,
                               keep=args.keep, author=args.author)
    print(f"resolved {args.candidate}: keep {args.keep} ({', '.join(result['manual_rules'])})")
    return EXIT_OK


def register(sub) -> None:
    rule = sub.add_parser("rule", help="manual rule authoring (contracts/manual-rule-cli.md)")
    verbs = rule.add_subparsers(dest="rule_verb", required=True)

    def verb(name, handler, help_text, *, writes=False):
        parser = verbs.add_parser(name, help=help_text)
        parser.add_argument("--path", required=True, metavar="TREE", help="knowledge working tree")
        if writes:
            parser.add_argument("--author", default=None, help="actor name (default: git config user.name)")
        parser.set_defaults(kap_handler=_guard(handler))
        return parser

    p = verb("create", _create, "create a MANUAL rule (DETECT_ONLY by default)", writes=True)
    p.add_argument("--from-file", metavar="RULE.json")
    p.add_argument("--id")
    p.add_argument("--step")
    p.add_argument("--category")
    p.add_argument("--detector-ref", dest="detector_ref")
    p.add_argument("--params", default="{}", help="detector parameters as a JSON object")
    p.add_argument("--evidence", action="append", default=[], metavar="EV-ID")
    p.add_argument("--file-kinds", dest="file_kinds", default="")
    p.add_argument("--severity", choices=SEVERITIES, default="WARNING")
    p.add_argument("--risk", choices=RISKS, default="LOW")
    p.add_argument("--maturity", choices=CREATE_CHOICES, default="DETECT_ONLY")
    p.add_argument("--message")
    p.add_argument("--suggestion")
    p.add_argument("--fixer-ref", dest="fixer_ref", default=None, help=argparse.SUPPRESS)

    p = verb("edit", _edit, "change fields of a rule (new revision)", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--from-file", metavar="CHANGES.json")

    p = verb("disable", _disable, "park a rule as DRAFT with a recorded reason", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True)

    p = verb("enable", _enable, "restore a disabled rule", writes=True)
    p.add_argument("--id", required=True)

    p = verb("retire", _retire, "retire a rule with a reason", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--superseded-by", dest="superseded_by", default=None)

    p = verb("inspect", _inspect, "show a rule, its evidence, history head and validation")
    p.add_argument("--id", required=True)
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict-builtin", dest="strict_builtin", action="store_true")

    p = verb("validate", _validate, "validate the tree (optionally one rule)")
    p.add_argument("--id", default=None)
    p.add_argument("--strict-builtin", dest="strict_builtin", action="store_true")

    p = verb("history", _history, "list revisions and verify the hash chain")
    p.add_argument("--id", required=True)
    p.add_argument("--json", action="store_true")

    p = verb("link-evidence", _link_evidence, "link an existing evidence record", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--evidence", required=True, metavar="EV-ID")

    p = verb("add-test", _add_test, "register a positive, negative or idempotence fixture", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True, choices=TEST_KINDS)
    p.add_argument("--fixture", required=True, metavar="FILE")

    p = verb("promote", _promote, "the only path to FIX_ENABLED (gates 1 to 5, approval required)", writes=True)
    p.add_argument("--id", required=True)
    p.add_argument("--to", required=True, choices=(FIX_ENABLED,))
    p.add_argument("--approval", required=True, metavar="REF", help="owner approval reference (not the promoter)")

    p = verb("resolve", _resolve, "record a generated-versus-manual conflict decision", writes=True)
    p.add_argument("--candidate", required=True, metavar="CR-ID")
    p.add_argument("--keep", required=True, choices=conflicts.KEEP_CHOICES)
    p.add_argument("--build-dir", dest="build_dir", required=True, metavar="DIR",
                   help="build directory holding conflicts.json")
