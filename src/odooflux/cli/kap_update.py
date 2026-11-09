"""`odooflux knowledge check` (feature 012, T04; plan Addendum B4/B6).

A read-only update check. It asks the official remotes which branch heads exist (`git ls-remote`, nothing is downloaded),
compares them with the installed release, and reports per-source statuses, new upstream versions (never supported
automatically), affected transitions and Enterprise freshness. It writes nothing to the kb-home.

Usage: `odooflux knowledge check [--json] [--offline] [--kb-home PATH]`. An online check is the explicit network
authorization (decision D1); `--offline` or ODOOFLUX_OFFLINE=1 disables it. Enterprise sources use the token from
ODOOFLUX_ENTERPRISE_TOKEN or ODOOFLUX_ENTERPRISE_TOKEN_FILE. Without one they are skipped, and a bad configuration is
reported without echoing its contents. The output never contains the token.

Exit codes (cli/kap_common.py): 0 check completed (updates may be available); 1 local knowledge state invalid;
2 usage error; 4 CHECK_UNAVAILABLE (no Community source could be read, or the catalog could not be loaded).

`knowledge update`, `knowledge status` and `knowledge history` (feature 012, Wave 3c; plan Addendum E). All three are
non-interactive. `update` runs the orchestrator (`knowledge/update/orchestrator.py`, reached through the `_run_update`
seam, imported on first use) with the attached extract toolkit; it is the only verb that can activate a release. `status`
and `history` read the kb-home and never use the network or write to it. Human and JSON output come from
`knowledge/update/report.py`.

`update` exit codes: 0 ACTIVE, NOOP or DRY_RUN; 1 BLOCKED; 2 usage error (--from and --to not given together, or no
extract toolkit attached); 3 ROLLED_BACK; 4 FAILED, or ACTIVE/NOOP/DRY_RUN when the run reports CHECK_UNAVAILABLE (the
comparison did not run, so the run cannot count as a success).
`status` and `history` exit codes: 0 read; 1 local state invalid (broken update-history chain, unusable active release or
installed state): the problem goes to stderr and nothing is printed to stdout; 2 usage error (--limit must be a positive
integer).
A dummy or real token is never printed. A bad Enterprise token configuration gives one stderr warning that names its
closed code only, and the run continues without a token.

Verbs are declared in `_VERBS`. A later verb is one entry there plus its handler; `register` needs no change.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from odooflux.cli.kap_common import EXIT_OK, EXIT_SOURCE_UNAVAILABLE, EXIT_USAGE, EXIT_VALIDATION, attached
from odooflux.knowledge.loader import RELEASE_TREE, load_active_knowledge
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.model import KnowledgeReleaseError
from odooflux.knowledge.release.resolver import HOME_ENV, default_kb_home, resolve_knowledge
from odooflux.knowledge.release.safety import certification_path
from odooflux.knowledge.update import credentials as cred
from odooflux.knowledge.update import discovery
from odooflux.knowledge.update import remote_git as rg
from odooflux.knowledge.update import report
from odooflux.knowledge.update.catalog import CatalogError, load_catalog
from odooflux.knowledge.update.history import HistoryError, UpdateHistory
from odooflux.utils.redaction import redact_text

__all__ = ["register", "cmd_check"]


def _common_args(parser) -> None:
    parser.add_argument("--kb-home", default=None, metavar="PATH", help="kb-home directory (read only)")
    parser.add_argument("--json", action="store_true", help="canonical JSON report (CheckReport)")


def _check_args(parser) -> None:
    _common_args(parser)
    parser.add_argument("--offline", action="store_true",
                        help="contact no remote; every source is reported SKIPPED_OFFLINE")


def _resolve_token():
    """(token or None, credential problem code or None). The message of a bad configuration is never shown."""
    try:
        return cred.resolve_enterprise_token(), None
    except cred.CredentialError as exc:
        return None, exc.code


def _exit_code(report) -> int:
    if "LOCAL_STATE_INVALID" in report.statuses:
        return EXIT_VALIDATION
    if "CHECK_UNAVAILABLE" in report.statuses:
        return EXIT_SOURCE_UNAVAILABLE
    return EXIT_OK


def _family_lines(report) -> list:
    lines = []
    editions = []
    for source in report.sources:
        if source.edition not in editions:
            editions.append(source.edition)
    for edition in editions:
        rows = [s for s in report.sources if s.edition == edition]
        counts = Counter(s.status for s in rows)
        summary = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
        changed = [s.version for s in rows if s.changed()]
        if changed:
            verdict = f"changed: {', '.join(changed)}"
        elif counts["OK"]:
            verdict = "no change"
        else:
            verdict = "not compared"
        lines.append(f"{edition}: {summary}; {verdict}")
        for status in sorted({s.status for s in rows if s.status != "OK"}):
            failing = [s for s in rows if s.status == status]
            detail = next((s.detail for s in failing if s.detail), "")
            versions = ", ".join(s.version for s in failing)
            lines.append(f"  {status}: {versions}" + (f" ({detail})" if detail else ""))
    return lines


def _human_lines(report, problem=None) -> list:
    lines = []
    if "LOCAL_STATE_INVALID" in report.statuses:
        lines.append("status: LOCAL_STATE_INVALID")
        lines.append(f"installed release state is invalid: {problem or 'unknown problem'}")
        lines.append("no remote was contacted")
        return lines
    installed = report.installed_release or "none (built-in knowledge only)"
    lines.append(f"installed release: {installed}")
    lines.append("mode: offline, no remote contacted" if report.offline else "mode: online, ls-remote only")
    lines.append("status: " + (", ".join(report.statuses) if report.statuses else "no conclusive status"))
    lines.extend(_family_lines(report))
    for nv in report.new_versions:
        lines.append(f"new upstream version: {nv.edition} {nv.version} (branch {nv.branch}, "
                     f"sha {nv.remote_sha[:12]})")
    if report.new_versions:
        lines.append("Migration support: not established")
    lines.append("affected transitions: " + (", ".join(report.affected_transitions)
                                            if report.affected_transitions else "none"))
    lines.append(f"enterprise freshness: {report.enterprise_freshness}")
    if "KNOWLEDGE_UPDATE_AVAILABLE" in report.statuses and report.installed_release is None:
        lines.append("note: no release is installed yet; the changed sources would be a fresh install")
    if "CHECK_UNAVAILABLE" in report.statuses:
        lines.append("nothing could be read from the community remote")
    elif "NO_UPDATE" in report.statuses:
        lines.append("no update detected")
    return lines


def cmd_check(args) -> int:
    try:
        installed = discovery.read_installed_state(args.kb_home or None)
        catalog = load_catalog()
    except CatalogError:
        print("ERROR: the official source catalog could not be loaded", file=sys.stderr)
        return EXIT_SOURCE_UNAVAILABLE
    token, credential_problem = None, None
    if installed.valid and rg.network_allowed(args.offline):
        token, credential_problem = _resolve_token()
    report = discovery.check(catalog, installed, offline=args.offline, token=token,
                             credential_problem=credential_problem)
    if args.json:
        text = canonical_bytes(report.to_dict()).decode("utf-8") + "\n"
    else:
        text = "\n".join(_human_lines(report, installed.problem)) + "\n"
    secrets = (token,) if token is not None else ()
    sys.stdout.write(redact_text(text, secrets=secrets))
    return _exit_code(report)


EXIT_BLOCKED = 1
EXIT_ROLLED_BACK = 3  # same number as kap_common.EXIT_PACKAGE_REJECTED; these verbs never package anything
_UPDATE_EXIT = {"NOOP": EXIT_OK, "ACTIVE": EXIT_OK, "DRY_RUN": EXIT_OK, "BLOCKED": EXIT_BLOCKED,
                "ROLLED_BACK": EXIT_ROLLED_BACK, "FAILED": EXIT_SOURCE_UNAVAILABLE}


class _InvalidState(Exception):
    """The local knowledge state cannot be trusted. The message is safe to print (no secret or raw file content)."""


def _run_update_default(*args, **kwargs):
    """Delegate to the orchestrator. Imported when first used because the orchestrator is written as a separate module."""
    from odooflux.knowledge.update.orchestrator import run_update  # lazy import (see the module docstring)
    return run_update(*args, **kwargs)


_run_update = _run_update_default  # seam: tests replace this module attribute with a fake


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}")
    return value


def _kb_home_arg(parser, help_text: str) -> None:
    parser.add_argument("--kb-home", default=None, metavar="PATH", help=help_text)


def _kb_home(args) -> Path:
    """The kb-home: --kb-home, else ODOOFLUX_KB_HOME, else the XDG data directory (the order resolve_knowledge uses)."""
    if args.kb_home:
        return Path(args.kb_home)
    return Path(os.environ.get(HOME_ENV) or default_kb_home())


def _update_args(parser) -> None:
    parser.add_argument("--dry-run", action="store_true",
                        help="plan only: reads remote metadata like check (none with --offline); nothing is downloaded, "
                             "built, installed, activated or recorded")
    parser.add_argument("--offline", action="store_true", help="contact no remote (same as ODOOFLUX_OFFLINE=1)")
    parser.add_argument("--from", dest="from_major", type=_positive_int, default=None, metavar="N",
                        help="update only the transition starting at this numeric major (requires --to)")
    parser.add_argument("--to", dest="to_major", type=_positive_int, default=None, metavar="M",
                        help="end major of the transition (requires --from)")
    parser.add_argument("--require-enterprise", action="store_true",
                        help="block the update unless the Enterprise sources can be refreshed")
    parser.add_argument("--json", action="store_true", help="print the UpdateResult as canonical JSON")
    _kb_home_arg(parser, "kb-home directory (default: ODOOFLUX_KB_HOME, else the XDG data directory)")


def _status_args(parser) -> None:
    parser.add_argument("--json", action="store_true", help="print the status as canonical JSON")
    _kb_home_arg(parser, "kb-home directory (read only; no network)")


def _history_args(parser) -> None:
    parser.add_argument("--json", action="store_true", help="print the history as canonical JSON")
    parser.add_argument("--limit", type=_positive_int, default=None, metavar="N",
                        help="show only the newest N entries")
    _kb_home_arg(parser, "kb-home directory (read only)")


def _update_token():
    """The Enterprise token for an online run, or None. A bad configuration is reported by its closed code only."""
    try:
        return cred.resolve_enterprise_token()
    except cred.CredentialError as exc:
        print(f"WARNING: Enterprise token configuration is unusable ({exc.code}); continuing without an Enterprise "
              "token (check ODOOFLUX_ENTERPRISE_TOKEN and ODOOFLUX_ENTERPRISE_TOKEN_FILE)", file=sys.stderr)
        return None


def _update_exit_code(result) -> int:
    statuses = (result.check or {}).get("statuses") or ()
    if result.outcome in ("NOOP", "ACTIVE", "DRY_RUN") and report.CHECK_UNAVAILABLE in statuses:
        return EXIT_SOURCE_UNAVAILABLE
    return _UPDATE_EXIT.get(result.outcome, EXIT_SOURCE_UNAVAILABLE)


def cmd_update(args) -> int:
    if (args.from_major is None) != (args.to_major is None):
        print("ERROR: --from and --to must be given together", file=sys.stderr)
        return EXIT_USAGE
    toolkit = attached(args, "extract_toolkit")
    if toolkit is None:
        print("ERROR: knowledge update needs the extract toolkit, which this run was started without", file=sys.stderr)
        return EXIT_USAGE
    offline = not rg.network_allowed(args.offline)
    token = None if offline else _update_token()
    only_pair = None if args.from_major is None else (args.from_major, args.to_major)
    result = _run_update(_kb_home(args), toolkit=toolkit, offline=offline, dry_run=args.dry_run,
                         require_enterprise=args.require_enterprise, only_pair=only_pair, token=token)
    if args.json:
        text = canonical_bytes(result.to_dict()).decode("utf-8") + "\n"
    else:
        text = report.render_update(result)
    secrets = (token,) if token is not None else ()
    sys.stdout.write(redact_text(text, secrets=secrets))
    return _update_exit_code(result)


def _has_certification(tree, rule_id) -> bool:
    if not isinstance(rule_id, str):
        return False
    path = certification_path(tree, rule_id)
    return path is not None and path.is_file()


def _verified_history(home: Path) -> UpdateHistory:
    """The update history with a verified chain. Raises _InvalidState when the chain is broken or unreadable."""
    try:
        history = UpdateHistory(home)
        ok, problems = history.verify()
    except HistoryError as exc:
        raise _InvalidState(f"update history is not valid: {exc}") from None
    if not ok:
        raise _InvalidState(f"update history is not valid: {problems[0]}")
    return history


def _status_payload(home: Path) -> dict:
    """Facts for `knowledge status`. Reads only: no network, no directory creation, no write."""
    try:
        handle = resolve_knowledge(home)
        kb = load_active_knowledge(handle)
    except (KnowledgeReleaseError, OSError, ValueError) as exc:
        raise _InvalidState(f"active release cannot be used: {exc}") from None
    installed = discovery.read_installed_state(home)
    if not installed.valid:
        raise _InvalidState(installed.problem or "installed release state is invalid")
    tree = Path(handle.root) if handle.builtin else Path(handle.root) / RELEASE_TREE
    rules = [rule for rule in kb.rules if isinstance(rule, dict)]
    by_maturity = Counter(str(rule.get("maturity") or "UNSPECIFIED") for rule in rules)  # effective maturity
    governed = sum(1 for rule in rules if _has_certification(tree, rule.get("id")))
    history = _verified_history(home)
    try:
        last = history.last_successful()
    except HistoryError as exc:
        raise _InvalidState(f"update history is not valid: {exc}") from None
    last_payload = None
    if last is not None:
        last_payload = {"seq": last["seq"], "timestamp": last["ts"], "new_release": last["new_release"]}
    return report.status_payload(
        release_id=None if handle.builtin else handle.release_id, digest=handle.digest,
        completeness=handle.completeness, steps=dict(handle.steps or {}), revisions=dict(installed.revisions),
        rules_by_maturity=dict(by_maturity), certification_governed=governed, last_successful=last_payload)


def cmd_status(args) -> int:
    try:
        payload = _status_payload(_kb_home(args))
    except _InvalidState as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    if args.json:
        text = canonical_bytes(payload).decode("utf-8") + "\n"
    else:
        text = report.render_status(payload)
    sys.stdout.write(text)
    return EXIT_OK


def cmd_history(args) -> int:
    try:
        entries = _verified_history(_kb_home(args)).read(limit=args.limit)
    except _InvalidState as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    except HistoryError as exc:
        print(f"ERROR: update history is not valid: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    rows = report.history_rows(entries)
    if args.json:
        text = canonical_bytes(report.history_payload(rows)).decode("utf-8") + "\n"
    else:
        text = report.render_history(rows)
    sys.stdout.write(text)
    return EXIT_OK


_VERBS = {
    "check": ("check for knowledge and source updates (read only; ls-remote only)", _check_args, cmd_check),
    "update": ("apply a knowledge update: discover, acquire, build, verify, activate (network unless --offline)",
               _update_args, cmd_update),
    "status": ("show the installed knowledge release and its known limitations (read only; no network)",
               _status_args, cmd_status),
    "history": ("show the verified update history, newest first (read only)", _history_args, cmd_history),
}


def register(subparsers) -> None:
    """Add every verb in `_VERBS` as a top-level `knowledge` subcommand (dispatched via `kap_handler`)."""
    for name, (help_text, configure, handler) in _VERBS.items():
        leaf = subparsers.add_parser(name, help=help_text, description=help_text)
        configure(leaf)
        leaf.set_defaults(kap_handler=handler)
