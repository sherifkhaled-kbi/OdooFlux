# Data Model: Hardening and Release Readiness

| Entity | Fields | Notes |
|---|---|---|
| BenchmarkResult | `corpus_id`, `seed`, `machine_profile`, `mode`, `runs[]`, `median_wall_s`, `peak_rss_mib`, `files_parsed`, `report_digest` | [contracts/benchmark-protocol.md](contracts/benchmark-protocol.md) |
| Budget | `metric`, `mode`, `value`, `baseline_ref`, `headroom_factor`, `approved_by`, `date` | Values set from baseline, never assumed |
| AuditEntry | see [contracts/audit-log.md](contracts/audit-log.md) | Hash-chained |
| IncrementalIndex | `path`, `sha256`, `ruleset_digest`, `tool_version`, `findings_ref` | Under state dir; invalidated by any digest change |
| ReleaseChecklistItem | `id`, `description`, `evidence_link`, `status`, `signed_by` | `docs/planning/RELEASE_CHECKLIST.md` (created in P9) |
| SupportStatementRow | `source`, `target`, `status ∈ {supported, experimental, unsupported}`, `reasons[]`, `evidence[]` | Generated from matrix data |
