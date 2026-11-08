# Data Model: Safety Stabilization (P0)

Stored as JSON Lines in the state directory. These records are a subset of the P2 run log and
report model ([CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md)). Field names are
kept forward-compatible.

## RunLogEntry (`<state-dir>/runs/<run-id>/log/run_log.jsonl`)

| Field | Type | Rule |
|---|---|---|
| `schema` | string | `"odooflux.runlog/0"` |
| `run_id` | string | `YYYYMMDDTHHMMSSZ-xxxxxx` |
| `event` | enum | `backup_created`, `backup_verified`, `backup_failed`, `file_written`, `edit_rejected`, `module_blocked` |
| `module` | string | Module directory name |
| `path` | string | Absolute path of the target file (for file events) |
| `sha256_before` / `sha256_after` | string | Required for `file_written` |
| `rules` | list[string] | Legacy rule categories applied to the file |
| `backup_path` | string | For backup and file events |
| `reason` | string | Required for `edit_rejected`, `backup_failed`, `module_blocked` |
| `timestamp` | string | ISO-8601 UTC |

Validation: every `file_written` entry for a module is preceded by `backup_verified` for that
module when `--backup` is set.

## Issue (legacy dataclass, extended)

The existing fields stay. These are added:

| Field | Type | Rule |
|---|---|---|
| `status` | enum | `OPEN`, `FIXED`, `REJECTED`, `NEEDS_REVIEW` |
| `evidence` | list[string] | `EV-…` IDs where applicable |
| `rejection_reason` | string | When `REJECTED` |

`fix_applied` stays for JSON-report backward compatibility and equals `status == "FIXED"`.

## BackupManifest (`<state-dir>/runs/<run-id>/backup/<module>.manifest.json`)

`{ module, source_path, backup_path, files: [{rel_path, sha256}], verified: bool }`

## State transitions (Issue.status)

`OPEN → FIXED` (re-scan absent) | `OPEN → REJECTED` (validation failed) |
`OPEN → NEEDS_REVIEW` (detect-only, review rule). No transition goes back to `FIXED` without a
re-scan.
