"""`odooflux knowledge coverage show|gates` (contracts/cli-surface.md, coverage-and-gates.md; REQ-KAP-032, REQ-KAP-034,
REQ-KAP-035).

- `coverage show --path DIR [--json]`: the eight metrics, one line each, numerator/denominator first. A zero denominator
  prints `n/a`. There is no combined score. Percentages are display only.
- `coverage gates --path DIR [--json]`: each gate with its status and reason codes, then the completeness decision and
  the limits of a PARTIAL release.

`DIR` holds two files: `coverage/coverage-manifest.json` (the stored CoverageManifest, the path is
`coverage.manifest.COVERAGE_FILE`) and `coverage/inputs.json` (the recompute bundle: `declared_scope`, `inventory`,
`accounting`, `changes` (ledger entries), `sources`, and the optional gate inputs `evidence_index`, `release_rules`,
`rule_findings`, `safety_findings`, `redaction_findings`, `declared_transitions`).

Both commands call `coverage.manifest.check_consistency(manifest, inputs)`. Any finding is printed and makes the command
fail, because a manifest that disagrees with its own ledger and accounting cannot back a COMPLETE claim. The command
also fails (exit 1) when the recomputed completeness is FAILED, as the contract requires.

`--release ID` reads the same two files from an installed release in kb-home (`releases/<ID>/`), as built by
`knowledge release build`. Give exactly one of `--path` and `--release`. `--kb-home` and `--quiet` are accepted for
consistency with the other groups.

Exit codes (cli/kap_common): 0 ok (PARTIAL prints its limits), 1 FAILED or inconsistent, 2 usage (missing or unreadable
input).
"""

import json
import os
import re
import sys
from pathlib import Path

from odooflux.cli.kap_common import EXIT_OK, EXIT_USAGE, EXIT_VALIDATION
from odooflux.knowledge.coverage import manifest as cm
from odooflux.knowledge.coverage.gates import decide
from odooflux.knowledge.release.canonical import canonical_bytes
from odooflux.knowledge.release.resolver import HOME_ENV, default_kb_home

__all__ = ["register", "cmd_show", "cmd_gates", "INPUTS_NAME"]

INPUTS_NAME = "inputs.json"
NOT_APPLICABLE = "NOT_APPLICABLE"


class _Usage(Exception):
    """A missing or unreadable input (exit 2)."""


def _read_json(path: Path, label: str):
    if not path.is_file():
        raise _Usage(f"{label} not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Usage(f"{label} is not readable JSON: {type(exc).__name__}") from None


_RELEASE_ID = re.compile(r"^kr-[0-9a-f]{12}$")


def _root(args) -> Path:
    if args.release is not None:
        if args.path is not None:
            raise _Usage("give --path or --release, not both")
        if not _RELEASE_ID.match(args.release):
            raise _Usage("a release id looks like kr-<12 hex digits>")
        home = Path(args.kb_home or os.environ.get(HOME_ENV) or default_kb_home())
        return home / "releases" / args.release
    if args.path is None:
        raise _Usage("give --path DIR or --release ID")
    return Path(args.path)


def _load(args):
    root = _root(args)
    manifest = _read_json(root.joinpath(*cm.COVERAGE_FILE), "coverage manifest")
    inputs = _read_json(root / cm.COVERAGE_FILE[0] / INPUTS_NAME, "coverage inputs")
    return manifest, inputs


def _emit(args, payload, lines) -> None:
    if args.quiet:
        return
    if args.json:
        print(canonical_bytes(payload).decode("utf-8"))
    else:
        for line in lines:
            print(line)


def _metric_line(item: dict) -> str:
    """One line per metric: fraction first, percentage second (display only), definition last."""
    head = f"{item['id']} {item['name']}"
    definition = item["denominator_definition"]
    if item["status"] == NOT_APPLICABLE or not item["denominator"]:
        return f"{head}  n/a  (denominator 0: {definition})"
    per_mille = item["per_mille"]
    line = (f"{head}  {item['numerator']}/{item['denominator']}  ({per_mille // 10}.{per_mille % 10}%)  "
            f"[{definition}]")
    if item.get("breakdown"):
        line += "  " + " ".join(f"{key}={value}" for key, value in item["breakdown"].items())
    return line


def _gate_line(gate: dict) -> str:
    kind = "blocking" if gate["blocking"] else "warning"
    line = f"{gate['gate_id']:<10} {gate['status']:<8} {kind:<8} {gate['name']}"
    if gate["reason_codes"]:
        line += f"  reasons={','.join(gate['reason_codes'])} offenders={gate['offenders_total']}"
    return line


def _findings_lines(findings: list) -> list:
    return [f"INCONSISTENT {finding}" for finding in findings]


def cmd_show(args) -> int:
    manifest, inputs = _load(args)
    findings = cm.check_consistency(manifest, inputs)
    decision = decide(manifest.get("gates") or [], manifest.get("limits") or [])
    metrics = manifest.get("metrics") or []
    failed = bool(findings) or decision["completeness"] == "FAILED"
    payload = {"metrics": metrics, "completeness": decision["completeness"], "consistency_findings": findings}
    lines = [_metric_line(item) for item in metrics] + _findings_lines(findings)
    lines.append(f"completeness {decision['completeness']}")
    _emit(args, payload, lines)
    return EXIT_VALIDATION if failed else EXIT_OK


def cmd_gates(args) -> int:
    manifest, inputs = _load(args)
    findings = cm.check_consistency(manifest, inputs)
    gates = manifest.get("gates") or []
    limits = list(manifest.get("limits") or [])
    decision = decide(gates, limits) if gates else {"completeness": "FAILED", "reasons": ["NO_GATES"],
                                                       "partial_gates": []}
    claimed = manifest.get("completeness")
    failed = bool(findings) or decision["completeness"] == "FAILED"
    payload = {"gates": gates, "completeness": decision["completeness"], "claimed": claimed,
               "reasons": decision["reasons"], "limits": limits, "consistency_findings": findings}
    lines = [_gate_line(gate) for gate in gates] + _findings_lines(findings)
    lines.append(f"completeness {decision['completeness']} (claimed {claimed})")
    if decision["reasons"]:
        lines.append("reasons " + "; ".join(decision["reasons"]))
    lines += [f"limit {text}" for text in limits]
    _emit(args, payload, lines)
    return EXIT_VALIDATION if failed else EXIT_OK


def _guarded(handler):
    def run(args) -> int:
        try:
            return handler(args)
        except _Usage as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_USAGE
        except (KeyError, TypeError, IndexError) as exc:
            print(f"ERROR: malformed coverage input ({type(exc).__name__})", file=sys.stderr)
            return EXIT_VALIDATION
        except (ValueError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return EXIT_VALIDATION
    return run


def _common(parser) -> None:
    parser.add_argument("--kb-home", default=None, metavar="PATH", help="kb-home directory (accepted, unused here)")
    parser.add_argument("--json", action="store_true", help="canonical JSON output")
    parser.add_argument("--quiet", action="store_true", help="no human output")


def register(subparsers) -> None:
    group = subparsers.add_parser("coverage", help="coverage metrics and release gates")
    verbs = group.add_subparsers(dest="coverage_action", required=True)
    for name, handler, text in (
            ("show", cmd_show, "print the eight metrics, each with its own fraction"),
            ("gates", cmd_gates, "print each gate and the completeness decision")):
        parser = verbs.add_parser(name, help=text)
        parser.add_argument("--path", default=None, metavar="DIR",
                            help="directory holding coverage/coverage-manifest.json and coverage/inputs.json")
        parser.add_argument("--release", default=None, metavar="ID",
                            help="an installed release in kb-home (instead of --path)")
        _common(parser)
        parser.set_defaults(kap_handler=_guarded(handler))
