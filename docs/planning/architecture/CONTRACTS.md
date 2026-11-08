# Interface Contracts (planning level)

These are the stable contracts between OdooFlux components. They are described as data shapes and
behavioural obligations, **not code**. Phase P2 turns them into Python types under
`src/odooflux/core/contracts/`. Field names are normative; Python naming (dataclasses,
`snake_case`) applies.

Contract version: **1** (`CONTRACT_VERSION = 1`). Any breaking change increments it
(REQ-ARC-006).

---

## OdooVersion

| Field | Type | Notes |
|---|---|---|
| `id` | string | `"17.0"`; ordering is numeric on major, then minor |
| `major` | int | 17 |
| `python_min` / `python_max` | string | From evidence (EV-125); `null` if unresearched |
| `online_releases` | list[string] | e.g. `["16.1","16.2","16.3","16.4"]` folded into this major (ADR-007) |
| `research_status` | enum | Matrix coverage vocabulary |
| `support_status` | enum | `UNSUPPORTED`, `EXPERIMENTAL`, `SUPPORTED` |
| `evidence` | list[EV id] | Pinned revisions used |

## MigrationStep

`{ "from": "16.0", "to": "17.0", "rules": [RuleId…], "research_status": …, "notes": … }`

## MigrationPlan

| Field | Type | Notes |
|---|---|---|
| `request` | `{source, target}` | As requested by the user |
| `steps` | list[MigrationStep] | Consecutive; computed by the Version Graph |
| `blocked_steps` | list | Steps without sufficient research; non-empty → plan `BLOCKED` unless `--allow-unverified` |
| `modules` | list[ModuleRef] | Dependency-ordered (REQ-DEP-002) |

## Rule

| Field | Type | Notes |
|---|---|---|
| `id` | string | `<step>.<area>.<slug>`, e.g. `16-17.xml.attrs-removed` |
| `step` | string | `"16-17"`; `"*"` only for version-independent hygiene rules |
| `file_kinds` | list | `python`, `xml_view`, `xml_data`, `qweb`, `manifest`, `js`, `css`, `csv_acl` |
| `severity` | enum | `CRITICAL`, `WARNING`, `INFO` |
| `maturity` | enum | `DRAFT`, `DETECT_ONLY`, `FIX_ENABLED`, `RETIRED` (ADR-008) |
| `evidence` | list[EV id] | ≥1 required (REQ-EVD-001) |
| `depends_on` / `conflicts_with` | list[RuleId] | Ordering and exclusivity |
| `detect` | callable ref | `(Document, Context) → list[Finding]`; pure, no I/O |
| `fix` | callable ref or null | `(Document, Finding, Context) → list[Edit]`; pure, no I/O |
| `ai_eligible` | bool | May be escalated to AI when no fix exists (REQ-AI-002) |
| `review_required` | bool | Semantics-changing; result capped at `NEEDS_REVIEW` (REQ-PY-003) |
| `validation` | list | Validator IDs that must pass after its edits |
| `docs` | string | Human explanation and suggested manual action |

Obligations: `detect` and `fix` are deterministic and side-effect free; `fix` is idempotent
(applying the rule to its own output yields no new edits).

## Document

Immutable view of one file: `path`, `kind`, `text` (decoded), `encoding`, `newline_style`,
`sha256`, and lazily computed `parse` (Python AST + token map, XML span tree, JS tree via adapter).
`line_col(offset)` and `offset(line, col)` conversions are exact.

## Finding

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable hash of rule ID + path + span + matched text |
| `rule_id` | string | |
| `path`, `span` | string, `[start, end)` byte offsets | Plus derived `line`, `column`, `end_line` |
| `severity`, `message`, `suggestion` | | |
| `evidence` | list[EV id] | Copied from the rule |
| `status` | enum | `OPEN`, `FIXED`, `REJECTED`, `NEEDS_REVIEW`, `AI_PROPOSED` |

`FIXED` is set **only** by the re-scan comparison (REQ-TRF-005).

## Edit

| Field | Type | Notes |
|---|---|---|
| `id` | string | Unique within a run |
| `rule_id` | string | Or `ai:<provider>/<model>` for AI edits |
| `finding_ids` | list | Findings this edit intends to resolve |
| `path` | string | |
| `span` | `[start, end)` | In the **current** document text for its step |
| `before` / `after` | string | `before` must equal `text[start:end]` at apply time, else rejected |
| `step` | string | Migration step it belongs to |
| `validation` | list | Validators to run |
| `status` | enum | `PLANNED`, `APPLIED`, `REJECTED`, `ROLLED_BACK` |
| `rejection_reason` | string | Required when `REJECTED` |

Obligations: overlapping spans in one apply batch are conflicts (REQ-TRF-002). Precedence order:
1. higher severity;
2. rule declared in `depends_on` order;
3. otherwise, both are rejected and reported.

## Validator

`id`, `layer` (1–5), `file_kinds`, `requires` (adapter names), and
`validate(Document | ModuleWorkspace, Context) → ValidationResult`.

`ValidationResult`: `validator_id`, `layer`, `outcome` (`PASS`, `FAIL`, `UNAVAILABLE`, `SKIPPED`),
`coverage` (`full`, `partial`, or `null` when not applicable; used by layer 5), `reason`
(required when `outcome` is not `PASS`), `messages[]` (with location), `duration_ms`. `UNAVAILABLE` is not `PASS`, and it caps the status
(REQ-VAL-006).

## ParserAdapter

`language`, `available() → bool`, `parse(text) → ParseTree | ParseError`,
`spans(ParseTree, query) → list[span]`. A missing adapter means `available() == false`; callers
must handle it.

## RuntimeEnvironment (Layer 4/5)

`prepare(version, modules_ro_path) → EnvHandle`, `install(EnvHandle, module_names) → RunLog`,
`upgrade(...)`, `run_tests(...)`, `teardown()`. Limits: CPU, memory, wall time, network
(default: off). All logs are captured and attached.

## AIProvider

| Member | Notes |
|---|---|
| `name`, `models()` | Provider ID and available model descriptors (context window, pricing if configured) |
| `complete(AIRequest) → AIResponse` | Synchronous; transport-level retries inside, bounded |
| `count_tokens(text, model)` | Estimate when the provider offers no counter (documented heuristic) |

`AIRequest`: `model`, `system`, `messages`, `response_schema`, `max_output_tokens`,
`budget_ref`, `cache_key`.

`AIResponse`: `text`, `parsed`, `usage{input, output, cached}`, `stop_reason`
(`complete`/`max_tokens`/`error`), `cost` (optional). A truncated response
(`stop_reason == max_tokens`) MUST be rejected (REQ-AI-005).

## ReportModel

Versioned (`schema_version`), presentation-independent:

```
Run{ run_id, tool_version, schema_version, started_at, finished_at, config_digest,
     plan: MigrationPlan, modules: [ModuleResult], ai_usage: AIUsageSummary,
     verification_scope: {layers_run, layers_unavailable, limits[]}, recovery: {run_log, rollback_cmd} }
ModuleResult{ name, path, source_version, target_version, status, status_reasons[],
              files: [FileResult], findings: [Finding], edits: [Edit],
              validation: [ValidationResult], durations }
```

## Renderer

`format_id`, `render(ReportModel, options) → bytes | files`. Renderers never compute results;
they only present the model (REQ-REP-001).

## Plugin registration

Each registry (versions, rules, parsers, validators, runtimes, AI providers, renderers) accepts
entries that declare `contract_version`. Loading checks the version and rejects mismatches with
a specific error (REQ-ARC-006). Built-ins and plugins use the same path; external plugins are
discovered from an explicit `--plugin` list or configuration, never automatically.
