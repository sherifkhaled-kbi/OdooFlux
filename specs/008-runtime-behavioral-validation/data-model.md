# Data Model: Runtime and Behavioral Validation

| Entity | Fields | Notes |
|---|---|---|
| ValidationResult (extension) | + `coverage ∈ {full, partial, null}` (L5 only), + `reason` (for UNAVAILABLE/SKIPPED) | Proposed extension of CONTRACTS.md (contract version unchanged if optional; flagged for P2 owner) |
| RuntimeRun | see [contracts/runtime-environment.md](contracts/runtime-environment.md) | Stored under `<state-dir>/runs/<run-id>/runtime/` |
| ErrorClassification | `class`, `pattern_id`, `version_range`, `evidence?` | Patterns are data in `knowledge/compatibility/runtime_log_patterns.json`; research gap G-R-22 |
| TestOutcome | `test_id` (module.class.method), `version`, `outcome ∈ {pass, fail, error, skip}`, `duration_ms` | Parsed from test run logs (G-R-23) |
| TestComparison | `test_id`, `source`, `target`, `classification` | Classifications per spec Key Entities |
| StatusDecision | `inputs`, `row`, `status`, `status_reasons[]` | Embedded in ModuleResult |
| VerificationScope | `layers_run[]`, `layers_unavailable[]` (with reasons), `layers_skipped[]`, `limits[]` (human-readable statements) | ReportModel `verification_scope` |
