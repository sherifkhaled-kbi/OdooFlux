# Data Model: Reporting and UX

| Entity | Fields | Notes |
|---|---|---|
| ReportModel v1 | see [contracts/report-schema-v1.md](contracts/report-schema-v1.md) | Produced by orchestrator (P2), extended by P6/P7 |
| RendererOptions | `color: auto|always|never`, `width: int|auto`, `max_findings_per_file: int`, `show_fixed: bool`, `min_severity` | `NO_COLOR` env honoured |
| ExitPolicy | `fail_on: none|critical|warning|info`, `fail_on_status: [FAILED, NEEDS_REVIEW]` (default `[FAILED]`) | Codes: 0/1/2/3/4, precedence 4>3>1>0 |
| Renderer registry entry | `format_id` (`terminal`, `html`, `json`, `sarif`, `diff`, `legacy-json`), `contract_version` | REQ-ARC-006 |

## Exit-code table

| Code | Meaning | Condition |
|---|---|---|
| 0 | OK | No condition below applies |
| 1 | Threshold exceeded | Open finding with severity ≥ `fail_on`, or a module status in `fail_on_status` |
| 2 | Usage/configuration error | Invalid arguments or config; emitted before any processing |
| 3 | Rejected edits | Write mode and ≥1 edit `REJECTED` |
| 4 | Blocked / tool error | Any module `BLOCKED` or an internal error |
