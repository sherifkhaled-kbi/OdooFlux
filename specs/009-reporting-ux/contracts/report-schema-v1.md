# Contract: Report Schema v1

Refines [CONTRACTS.md § ReportModel](../../../docs/planning/architecture/CONTRACTS.md#reportmodel). Published as `src/odooflux/reporting/model/report.schema.json` (JSON Schema draft 2020-12, validated by a stdlib subset validator in tests).

```text
Run
  schema_version: 1
  run_id, tool_version, started_at, finished_at, duration_ms, config_digest
  request: { source, target, mode: analyze|dry-run|write, options{} }
  plan: { steps[{from,to,research_status}], blocked_steps[], modules_order[] }
  summary: { modules_by_status{}, findings{critical,warning,info}, findings_by_status{open,fixed,rejected,needs_review,ai_proposed}, edits{applied,rejected}, files_written }
  modules[]: ModuleResult
  ai_usage: { enabled, consent, providers[{name, model, requests, input_tokens, output_tokens, cached_tokens, estimated, cost|null}], budget_events[], totals }
  verification_scope: { layers_run[], layers_unavailable[{layer,reason}], layers_skipped[{layer,reason}], limits[] }
  recovery: { state_dir, run_log, backup_dir|null, rollback_cmd|null, resume_cmd|null }
  warnings[]: tool warnings (non-findings)

ModuleResult
  name, path, source_version, target_version, status, status_reasons[], duration_ms
  files[]: { path, kind, sha256_before, sha256_after|null, findings[ids], edits[ids] }
  findings[]: Finding (CONTRACTS.md) + evidence[{id, url}]
  edits[]: Edit (CONTRACTS.md) incl. rejection_reason
  validation[]: ValidationResult (CONTRACTS.md + coverage, reason)
  runtime: { image, digest, logs_path, errors[] } | null
  behavior: { comparisons[], summary{pass_both,regression,fixed,fail_both,target_only,source_only} } | null
```

Rules:
- Excluding `started_at`, `finished_at`, `duration_ms`, `run_id`, and paths under `state_dir`, the model is deterministic for identical inputs (REQ-ARC-005). Lists are sorted by (path, span start, rule_id).
- Additive changes keep `schema_version`; removals or renames increment it.
- Every `Finding.evidence[].url` points to an allow-listed official URL (REQ-EVD-004).
