# Contract: Command-Line Interface (P2)

A single entry point: `odooflux` (console script) or `python odooflux.py` (launcher).

## Subcommands

| Command | Purpose | Writes customer files? |
|---|---|---|
| `odooflux migrate [options]` (default when no subcommand) | Plan, analyze, optionally fix | Only with `--fix` and without `--dry-run` |
| `odooflux plan --from X --to Y [sources]` | Print plan (steps, module order, blocked steps) | No |
| `odooflux rollback <run-id> [--state-dir D]` | Restore a run from its run log | Yes (restore only) |
| `odooflux resume <run-id> [--state-dir D]` | Continue an interrupted run | As the original run |
| `odooflux versions` | List registry versions and research/support status | No |

## Options (migrate)

Legacy options are kept with their meaning: `--module`, `--modules`, `--addons-path`,
`--from-version`, `--to-version`, `--fix`, `--backup`, `--dry-run`, `--report`, `--no-color`,
`--skip`, `--show-fixed`, `--filter-severity`, `--ai-fix`, `--api-key` (deprecated, D-10),
`--ai-verbose`, `--fail-on`, `--state-dir`.

Changes:
- `--to-version` accepts any registry version greater than the source (no hardcoded `choices`;
  REQ-ARC-003).
- `--from-version`/`--to-version` accept `14` or `14.0`.
- New: `--allow-unverified`, `--plugin MODULE:ATTR` (repeatable), `--report-format json`
  (more formats in P8).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success; no open findings at or above `--fail-on` |
| 1 | Open findings at or above `--fail-on` (or any module `NEEDS_REVIEW`/`FAILED` when `--fail-on` ≠ `none`) |
| 2 | Usage error (argparse) |
| 3 | At least one edit rejected in write mode |
| 4 | Tool error, or any module `BLOCKED` |

Precedence: 4 > 3 > 1 > 0 (same table as [REPORTING_AND_UX.md](../../../docs/planning/REPORTING_AND_UX.md)).

## Compatibility rule

Every behaviour difference from the P1 characterisation expectations is listed in
`docs/changes/P2_CUTOVER.md` with the reason. The characterisation suite reads that file to accept
listed differences.
