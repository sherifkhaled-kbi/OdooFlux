# Contract: Module Result Status Decision

Single source for status logic. It mirrors [VALIDATION_AND_TEST_STRATEGY.md § Result statuses](../../../docs/planning/VALIDATION_AND_TEST_STRATEGY.md#result-statuses).

## Inputs

| Input | Values |
|---|---|
| `plan_state` | `ok`, `refused` (unsupported or unresearched path without `--allow-unverified`), `unverified_allowed` |
| `tool_state` | `ok`, `backup_failed`, `workspace_failed`, `promotion_failed`, `tool_error` |
| `L1`…`L5` | `PASS`, `FAIL`, `UNAVAILABLE`, `SKIPPED` (L5 also has `coverage ∈ {full, partial}`) |
| `required_layers` | Always includes L1, L2, L3; plus any `--require` layers |
| `open_critical` | count of open CRITICAL findings after fixes and re-scan |
| `open_warning` | count of open WARNING findings |
| `open_review` | count of open findings from `review_required` rules, or AI-accepted edits on `review_required` rules |
| `rejected_edits` | count (informational; their findings stay open and are counted above) |

## Decision (first matching row wins)

| # | Status | Condition |
|---|---|---|
| 1 | `BLOCKED` | `plan_state = refused` **or** `tool_state ≠ ok` **or** any layer in `required_layers` is `UNAVAILABLE` or `SKIPPED` |
| 2 | `FAILED` | any layer that ran is `FAIL` **or** `open_critical > 0` |
| 3 | `NEEDS_REVIEW` | `open_review > 0` **or** `open_warning > 0` **or** `plan_state = unverified_allowed` **or** any L1/L2 sub-validator for a present file kind is `UNAVAILABLE` (e.g., JS adapter missing with JS files, REQ-JS-001) |
| 4 | `VERIFIED_SUCCESS` | L1–L4 `PASS` **and** L5 `PASS` with `coverage = full` |
| 5 | `INSTALL_VERIFIED` | L1–L4 `PASS` (L5 `SKIPPED`, `UNAVAILABLE`, or `PASS` with `coverage = partial`) |
| 6 | `STATIC_VALIDATED` | L1–L3 `PASS` (L4 `SKIPPED` or `UNAVAILABLE`) |
| 7 | `NEEDS_REVIEW` | fallback: any combination not matched above (must be reported as `status_reason = unmatched_combination`; tests assert it never occurs for valid inputs) |

Notes:
- INFO findings never affect status.
- Row 1 implements the CLARIFICATION "required layer unavailable → BLOCKED". Optional layers that are unavailable fall through to rows 5/6.
- Every decision emits `status_reasons[]` listing the matched row and the inputs that triggered it.
