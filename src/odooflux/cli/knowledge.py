"""`odooflux knowledge {validate,refresh,matrix}` (contracts/knowledge-cli.md).

Exit codes: 0 success, 1 validation findings (or matrix drift with --check), 2 usage error, 3 tool error.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from odooflux.cli.kap_common import register_all
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge
from odooflux.knowledge.matrix import OverclaimError, generate
from odooflux.knowledge.release.confidentiality_view import (
    view_enterprise_source_ids, redact_kb_findings, redact_refresh_report)
from odooflux.knowledge.release.safety import load_provenance_index
from odooflux.knowledge.refresh import apply_report, refresh

REPO_ROOT = KNOWLEDGE_ROOT.parents[2]
DEFAULT_MATRIX = REPO_ROOT / "docs" / "planning" / "VERSION_COMPATIBILITY_MATRIX.md"


def _kv(text: str, flag: str) -> tuple:
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"{flag} expects NAME=VALUE, got {text!r}")
    key, value = text.split("=", 1)
    return key, value


def build_parser():
    parser = argparse.ArgumentParser(prog="odooflux knowledge", description="Official source knowledge base")
    sub = parser.add_subparsers(dest="action", required=True)
    v = sub.add_parser("validate", help="validate the knowledge tree")
    v.add_argument("--path", default=str(KNOWLEDGE_ROOT))
    r = sub.add_parser("refresh", help="re-verify evidence locations against local clones")
    r.add_argument("--repo", action="append", default=[], type=lambda t: _kv(t, "--repo"), metavar="NAME=PATH")
    r.add_argument("--revision", action="append", default=[], type=lambda t: _kv(t, "--revision"),
                   metavar="BRANCH=SHA")
    r.add_argument("--apply", action="store_true", help="write moved lines and demote missing records")
    r.add_argument("--report", default=None, metavar="FILE")
    r.add_argument("--search-candidates", action="store_true",
                   help="for missing matches, search the revision for candidate paths (slow on partial clones)")
    r.add_argument("--path", default=str(KNOWLEDGE_ROOT))
    m = sub.add_parser("matrix", help="generate the compatibility matrix")
    m.add_argument("--check", action="store_true", help="fail if the committed file differs")
    m.add_argument("--output", default=str(DEFAULT_MATRIX))
    m.add_argument("--path", default=str(KNOWLEDGE_ROOT))
    register_all(sub)
    return parser


def cmd_validate(args) -> int:
    kb = load_knowledge(Path(args.path))
    findings = redact_kb_findings(kb, validate_knowledge(kb), load_provenance_index(kb.root))
    for f in findings:
        print(f.line())
    errors = sum(1 for f in findings if f.severity == "ERROR")
    warnings = sum(1 for f in findings if f.severity == "WARNING")
    print(f"records={len(kb.evidence)} rules={len(kb.rules)} errors={errors} warnings={warnings}")
    return 1 if errors else 0


def cmd_refresh(args) -> int:
    kb = load_knowledge(Path(args.path))
    repos = {name: Path(path) for name, path in args.repo}
    report = refresh(kb, repos, dict(args.revision), search_candidates=args.search_candidates)
    shown = redact_refresh_report(report, kb.evidence, view_enterprise_source_ids(kb.root))
    text = json.dumps(shown, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if args.apply:
        written = apply_report(kb, report, today=date.today().isoformat())
        print(f"applied: {len(written)} file(s) updated", file=sys.stderr)
    return 0


def cmd_matrix(args) -> int:
    kb = load_knowledge(Path(args.path))
    text = generate(kb)
    output = Path(args.output)
    if args.check:
        committed = output.read_text(encoding="utf-8") if output.exists() else ""
        if committed != text:
            print(f"matrix drift: {output} differs from the generated content")
            return 1
        print(f"matrix up to date: {output}")
        return 0
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")
    return 0


def main(argv, registries=None) -> int:
    """`registries` is the composition root's registries (or None). Only the KAP groups read it."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        handler = getattr(args, "kap_handler", None)
        if handler is not None:
            args.registries = registries
            return handler(args)
        if args.action == "validate":
            return cmd_validate(args)
        if args.action == "refresh":
            return cmd_refresh(args)
        return cmd_matrix(args)
    except OverclaimError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
