# Contract: Result (Report) Model v1 (P2)

Normative structure: [CONTRACTS.md § ReportModel](../../../docs/planning/architecture/CONTRACTS.md#reportmodel).
P2 publishes `src/odooflux/reporting/model/report.schema.json` (JSON Schema draft 2020-12, used as
documentation). A stdlib validator checks required keys, types, and enums.

## Obligations

- `schema_version: "1.0.0"`; additive changes bump the minor version, removals bump the major version.
- `modules[].status` ∈ {`VERIFIED_SUCCESS`, `INSTALL_VERIFIED`, `STATIC_VALIDATED`, `NEEDS_REVIEW`,
  `FAILED`, `BLOCKED`}; `status_reasons` is non-empty unless the status is `VERIFIED_SUCCESS`.
- `verification_scope.layers_run` and `layers_unavailable` are always present (may be empty).
- Each finding carries `rule_id`, `path`, `line`, `column`, `severity`, `message`, `suggestion`,
  `evidence[]`, and `status`.
- Each edit carries the CONTRACTS.md Edit fields; `REJECTED` edits include `rejection_reason`.
- `recovery.run_log` and `recovery.rollback_cmd` are present for fix runs.
- Legacy JSON compatibility: `--report` without `--report-format` keeps writing the legacy shape
  (characterisation parity). `--report-format json` writes v1. The legacy shape is removed only
  by a D-10 decision.
- Determinism: see [research.md R-08](../research.md).
