"""Argument parsing and subcommand dispatch. Keeps every legacy flag (D-10 default)."""

import argparse
import sys
from pathlib import Path

from odooflux import __version__
from odooflux.cli import deprecations
from odooflux.cli.ai_options import add_ai_arguments
from odooflux.cli.plugins import load_plugins
from odooflux.core.contracts import UnsupportedVersionError
from odooflux.core.jobs.state_dir import default_state_dir

SUBCOMMANDS = ("migrate", "plan", "rollback", "resume", "versions")
DEPRECATED_API_KEY = ("WARNING: --api-key is deprecated (D-10): it can leak through shell history. "
                      "Set ANTHROPIC_API_KEY instead.")

# Official attribution. The single source for `--help` and `--version`; the docs repeat these facts verbatim.
ATTRIBUTION_LINES = (
    "Company: KnowledgeBI | Website: https://www.knowledgebi.net",
    "Developer: Sherif Khaled",
    "Copyright: © 2026 KnowledgeBI. All rights reserved.",
)


def version_text() -> str:
    """Output of ``odooflux --version``: the version, then the attribution lines."""
    return "\n".join((f"odooflux {__version__}", *ATTRIBUTION_LINES))


class SafeParser(argparse.ArgumentParser):
    """Argparse errors can quote argument text; never let them quote the value of ``--api-key`` (D-10)."""

    secrets: list = []

    def error(self, message):
        for value in SafeParser.secrets:
            message = message.replace(value, "***")
        super().error(message)


def _common_sources(parser):
    src = parser.add_argument_group("Module sources (use one or more)")
    src.add_argument("--module", default=None, metavar="PATH")
    src.add_argument("--modules", nargs="+", default=None, metavar="PATH")
    src.add_argument("--addons-path", default=None, metavar="DIR")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeParser(
        prog="odooflux", description="Analyze and auto-fix Odoo module(s) for migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(("Subcommands: migrate (default), plan, rollback, resume, versions, knowledge.", "",
                          *ATTRIBUTION_LINES)))
    parser.add_argument("--version", action="version", version=version_text(),
                        help="print the version and attribution, then exit")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    mig = sub.add_parser("migrate", help="analyze, optionally fix (default)",
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    _common_sources(mig)
    mig.add_argument("--from-version", required=True, metavar="VERSION")
    mig.add_argument("--to-version", default="19", metavar="VERSION")
    mig.add_argument("--fix", action="store_true")
    mig.add_argument("--backup", action="store_true",
                     help="accepted for compatibility; --fix backs up by default")
    mig.add_argument("--no-backup", action="store_true",
                     help="skip the pre-write backup; the run is marked non-reversible")
    mig.add_argument("--dry-run", action="store_true")
    mig.add_argument("--report", default=None, metavar="FILE")
    mig.add_argument("--report-format", default="legacy", metavar="FORMAT",
                     help="legacy (default), json (report model v1), or a registered renderer")
    mig.add_argument("--no-color", action="store_true")
    mig.add_argument("--skip", nargs="+", default=[], metavar="NAME")
    mig.add_argument("--show-fixed", action="store_true")
    mig.add_argument("--filter-severity", default=None, choices=["CRITICAL", "WARNING", "INFO"])
    mig.add_argument("--ai-fix", action="store_true")
    mig.add_argument("--api-key", default=None, metavar="KEY",
                     help=argparse.SUPPRESS if deprecations.api_key_removed() else "deprecated; use ANTHROPIC_API_KEY")
    mig.add_argument("--ai-verbose", action="store_true")
    add_ai_arguments(mig)
    mig.add_argument("--fail-on", default="critical", choices=["critical", "warning", "info", "none"])
    mig.add_argument("--fail-on-status", default=None, metavar="STATUSES",
                     help="comma list of FAILED,NEEDS_REVIEW (or none) that fail the run with exit 1; "
                          "default FAILED unless --fail-on none")
    mig.add_argument("--exit-codes", default=None, choices=["legacy", "v1"],
                     help="v1 = documented table (BLOCKED=4, rejected=3, threshold=1); legacy (default for one "
                          "minor release, D-10) keeps the characterised mapping; --fail-on-status implies v1")
    mig.add_argument("--sarif", default=None, metavar="FILE", help="write a SARIF 2.1.0 report")
    mig.add_argument("--sarif-include-fixed", action="store_true", help="include fixed findings as kind pass")
    mig.add_argument("--html", default=None, metavar="FILE", help="write a self-contained offline HTML report")
    mig.add_argument("--diff", default=None, metavar="FILE",
                     help="write the kept edits as a unified diff (patch -p1) plus FILE.index.json")
    mig.add_argument("--ui", default=None, choices=["auto", "ansi", "rich"],
                     help="print the report-model terminal summary (rich only if installed)")
    mig.add_argument("--max-findings-per-file", type=int, default=20, metavar="N",
                     help="cap findings listed per file in --ui output (totals stay exact)")
    mig.add_argument("--provisional-corpus", action="store_true",
                     help="label the run PROVISIONAL (ADR-019): it relies on a provisional validation corpus; also "
                          "automatic when a module sits under a directory with a PROVISIONAL.md marker")
    mig.add_argument("--state-dir", default=None, metavar="DIR")
    mig.add_argument("--jobs", type=int, default=1, metavar="N",
                     help="worker processes for analysis and dry-run (default 1; 0 = one per CPU); the report is "
                          "identical to a serial run; fix mode always runs serially")
    mig.add_argument("--incremental", action="store_true",
                     help="skip modules whose files, rule set and tool version are unchanged since the last "
                          "incremental analysis (index under the state directory; analysis and dry-run only)")
    mig.add_argument("--allow-unverified", action="store_true",
                     help="run unresearched steps; every module is capped at NEEDS_REVIEW")
    mig.add_argument("--plugin", action="append", default=[], metavar="MODULE:ATTR")
    mig.add_argument("--enable-rule", action="append", default=[], metavar="RULE_ID",
                     help="opt in to a DETECT_ONLY rule that needs run inputs, e.g. *.manifest.version-prefix")
    mig.add_argument("--experimental-fixes", action="store_true", default=False,
                     help="with --fix: also apply implemented but NOT certified fixers to DETECT_ONLY rules "
                          "(attrs/states to modifier expressions); reported as fix_class experimental")
    mig.add_argument("--kb-home", default=None, metavar="PATH",
                     help="knowledge release home (default: $ODOOFLUX_KB_HOME, else the user data directory); "
                          "resolved once per run; no active release means the built-in knowledge")
    mig.add_argument("--require-complete-kb", action="store_true",
                     help="refuse an active knowledge release that is not COMPLETE (exit 4)")

    plan = sub.add_parser("plan", help="print the migration plan (writes nothing)")
    _common_sources(plan)
    plan.add_argument("--from", dest="source", required=True, metavar="VERSION")
    plan.add_argument("--to", dest="target", required=True, metavar="VERSION")
    plan.add_argument("--allow-unverified", action="store_true")
    plan.add_argument("--plugin", action="append", default=[], metavar="MODULE:ATTR")

    for name, text in (("rollback", "restore a run to its pre-run bytes"),
                       ("resume", "continue an interrupted run")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("run_id")
        cmd.add_argument("--state-dir", default=None, metavar="DIR")
        if name == "resume":
            cmd.add_argument("--api-key", default=None, metavar="KEY", help=argparse.SUPPRESS)
            cmd.add_argument("--plugin", action="append", default=[], metavar="MODULE:ATTR")

    ver = sub.add_parser("versions", help="list registry versions and research status")
    ver.add_argument("--plugin", action="append", default=[], metavar="MODULE:ATTR")
    # listed for discovery only: run() hands `knowledge ...` to cli.knowledge before this parser ever sees it
    sub.add_parser("knowledge", help="inspect and update the knowledge base (status, update, check, ...)", add_help=False)
    return parser


def run(argv, ctx) -> int:
    """Dispatch *argv*. *ctx* is the composition root's Context (registries and transitions)."""
    argv = list(argv)
    SafeParser.secrets = deprecations.secret_values(argv)
    if deprecations.api_key_removed() and any(deprecations.names_api_key(t) for t in argv):
        print(deprecations.API_KEY_REMOVED_MESSAGE.format(removed=deprecations.API_KEY_REMOVED_IN), file=sys.stderr)
        return 2  # D-10: before any parsing, so no error text can quote the value
    if argv[:1] == ["--version"]:  # before the legacy "migrate" prefix below would capture it
        print(version_text())
        return 0
    if argv and argv[0] == "knowledge":
        from odooflux.cli.knowledge import main as knowledge_main
        return knowledge_main(argv[1:], registries=ctx.registries)
    if argv and argv[0] == "support-statement":
        from odooflux.cli.support_statement import main as support_main
        return support_main(argv[1:])
    if not argv or argv[0] not in SUBCOMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["migrate", *argv]  # legacy flag interface = migrate
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "migrate":  # one knowledge resolution per run, before plugins extend the registries
        from odooflux.cli.migrate import resolve_migrate_knowledge
        handle, problem = resolve_migrate_knowledge(args)
        if problem:
            print(problem, file=sys.stderr)
            return 4
        ctx = ctx.for_knowledge(handle)
    failures = load_plugins(getattr(args, "plugin", []), ctx.registries)
    if args.command == "migrate" and args.api_key:
        print(DEPRECATED_API_KEY, file=sys.stderr)
    try:
        graph = ctx.graph()
    except UnsupportedVersionError as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.command == "versions":
        from odooflux.cli.commands import cmd_versions
        return cmd_versions(graph, ctx)
    if args.command == "plan":
        from odooflux.cli.commands import cmd_plan
        return cmd_plan(args, graph)
    if args.command == "rollback":
        from odooflux.cli.commands import cmd_rollback
        return cmd_rollback(args)
    if args.command == "resume":
        from odooflux.cli.commands import cmd_resume
        return cmd_resume(args, ctx)
    from odooflux.cli.migrate import run_migrate
    return run_migrate(args, ctx, graph, failures)


def default_state(args) -> Path:
    return Path(args.state_dir).expanduser().resolve() if args.state_dir else default_state_dir()
