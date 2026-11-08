# P2 cut-over: core architecture

Spec: [specs/003-core-architecture](../../specs/003-core-architecture/spec.md). Conformance evidence:
[verification.md](../../specs/003-core-architecture/verification.md).

This record lists every behaviour that differs from the P0 script. The cut-over test
(`tests/integration/test_cutover_differences.py`) reads the table below and checks that each row is
actually observed, so a stale entry fails the suite.

## Intended differences

Each row is machine-read: `id`, `description`, `check` (name of a check in the test).

<!-- differences:start -->
| id | description | check |
|---|---|---|
| D1 | Analyze and dry-run now create `runs/<id>/{state.json,log}` in the state dir (contract TST-003-030). P0 created nothing. No source file is touched. | analyze_creates_state |
| D2 | A promotion or workspace failure marks the module `BLOCKED` (status table row 1). Spec 003 US3 said `FAILED`; the normative decision table wins, so P0 exit code 4 is kept. | tool_failure_is_blocked |
| D3 | Layer L3 (dependency integrity) is implemented in P7 and runs for every module with a manifest. Its result is `PASS` for a clean module, `FAIL` for a broken reference, and references it cannot decide are listed as verification-scope limits. A directory without a manifest is `BLOCKED`. The legacy exit code is unchanged: exit 1 still depends only on open findings at `--fail-on`. | l3_clean_passes |
| D4 | The console script is `odooflux.builtins:main` (the composition root), not `odooflux.cli.main:main`. The CLI cannot import adapters without breaking the core import rule. | console_entry_point |
| D5 | Tool errors (missing module path, no addon directories) exit 4. P0 exited 1. | tool_error_exit_4 |
| D6 | `--to-version` no longer has a fixed choice list; any registry version above the source is accepted. | to_version_not_fixed |
| D7 | `--from-version` not below `--to-version` is a usage error (exit 2). P0 exited 1. | usage_error_exit_2 |
| D8 | `--api-key` prints a deprecation warning (D-10). The key still works. | api_key_warning |
<!-- differences:end -->

## Deprecated options (D-10)

- `--api-key`: works, prints a warning. Use `ANTHROPIC_API_KEY`.
- `--backup`: accepted; backups are on by default with `--fix`.

## Legacy rule waivers

- The `legacy-*` rules have no full evidence (Principle VI). Each run lists the waiver through
  `verification_scope`. The evidence requirement is waived until P5 replaces the rules.
- `legacy-*` rules run as one table per file kind, not per rule. Per-rule granularity arrives with P5.
- Validation layer L3 (dependency integrity) runs (P7). L4 and L5 are not requested in a static run and are listed under `verification_scope.layers_unavailable` with reason `runtime_not_requested`.

## Other interpretations

- "Unresearched" means `NOT_ASSESSED`. Every shipped step from 12.0 to 19.0 is `RESEARCH_SEEDED`,
  so the default 14→19 migration is not blocked. Only 19.0→20.0 is unresearched.
- Plugin rules run for every file alongside the legacy rules; plugin validators run as L1 gates.
- The AI pass goes through the `ai_providers` registry (`legacy-anthropic`). Its writes use the same
  workspace and promotion path as regex fixes.
