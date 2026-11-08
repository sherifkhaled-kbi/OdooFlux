# Contract: Release Lifecycle

Modules: `knowledge/pipeline.py` (build), `knowledge/release/` (store, activate) (REQ-KAP-025, 026, 029, 030, 031, 045).

## Build steps (ordered, each re-runnable, each writes `build/<run-id>/steps/<NN>-<name>.json`)

| # | Step | Input | Output | Stops pipeline on |
|---|---|---|---|---|
| 1 | acquire | source registry | snapshots | required source FAILED |
| 2 | verify | snapshots | verified statuses | checksum/blob mismatch |
| 3 | extract | snapshot pairs | changes, file accounting | none (failures are recorded) |
| 4 | classify | drafts | classified changes | none |
| 5 | evidence | ledger | evidence records | none |
| 6 | candidates | ledger, templates | candidate rules | template error |
| 7 | schema-validate | staging tree | findings | any ERROR |
| 8 | dup-conflict | staging tree | A-code findings, `conflicts.json` | ERROR |
| 9 | rule-tests | rules + fixtures | pass/fail per rule | none (failures counted, M6) |
| 10 | coverage | all above | coverage manifest | none |
| 11 | gates | coverage | gate results, completeness | none (records result) |
| 12 | build-package | staging tree | `release.json`, release dir (STAGED) | `FAILED` completeness unless `--allow-failed` (dev only, never exportable) |
| 13 | validate-package | export to temp and re-read | pass | any P-code |
| 14 | publish-local | release dir | state INSTALLED in kb-home | |
| 15 | export | release | `.ofkp` file | |
| 16 | import-activate | package (consumer machine) | state ACTIVE, `active.json` | any rejection |
| 17 | provenance | everything | audit entries, sources.json | |

`--dry-run` prints plan only. `--from-step N` resumes using recorded step results; step results carry input digests, a changed input invalidates later steps.

## Release states

`STAGED -> INSTALLED -> ACTIVE <-> INSTALLED -> REMOVED`. Transitions only via the commands below; `state.json` is outside the digest.

## Activation (atomic)

1. Verify release dir files against `release.json` (digest recomputed) and framework compatibility.
2. Acquire kb-home lock.
3. Write new `active.json` to a temp file in kb-home, fsync, `os.replace`.
4. Append audit entries `activate_started`, `activate_completed` (AuditLog).
Crash between 3 and 4 leaves a valid active pointer; audit is repaired on next command (`audit_recover` note). Crash before 3 leaves old pointer. Import stage dirs older than the lock holder are removed on next run.

## Rollback

`release rollback` reads `previous[0]` from `active.json`, verifies that release is `INSTALLED` and intact, then activates it using the same atomic path. If it fails verification: refuse, current stays. Rollback of KB release never touches run state or migration rollbacks (existing contracts unchanged, REQ-KAP-042).

## Removal

`release remove <id>` refuses ACTIVE and any release listed in `previous[]` unless `--force-previous`. Removal moves the directory to `staging/trash/` then deletes; audit entry written.

## Incremental update rules (REQ-KAP-030, 031)

- New build sets `parent_release`. Records unchanged vs parent are copied byte for byte.
- `release diff <a> <b>` lists added, removed, changed records per family. Removal of a rule or VERIFIED evidence record is flagged `DESTRUCTIVE` and requires `--supersede <id>` listing; otherwise build step 12 fails.
- MANUAL beats DETERMINISTIC (ledger contract rule 6, manual-rule-cli).
- Validated knowledge is never rewritten in place: a changed record yields a new revision in history.

## Audit actions

`source_acquired`, `source_failed`, `build_started`, `build_completed`, `release_installed`, `release_activated`, `release_deactivated`, `release_rolled_back`, `release_removed`, `package_exported`, `package_rejected`, `ai_proposal` (no prompt text). Hash-chain verified by `knowledge release audit-verify`.

## Tests

`test_step_order_and_stop`, `test_dry_run_plan`, `test_resume_invalidates_changed_input`, `test_activation_atomic_fault_injection` (fault at each boundary), `test_rollback`, `test_remove_active_refused`, `test_incremental_preserves_bytes`, `test_destructive_needs_supersede`, `test_audit_chain`, `test_concurrent_lock`.
