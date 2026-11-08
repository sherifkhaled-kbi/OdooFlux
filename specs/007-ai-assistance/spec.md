# Feature Specification: Optional, Provider-Neutral AI Assistance

**Feature Branch**: `007-ai-assistance`
**Created**: 2026-11-06
**Status**: Implemented offline (T001-T028, T032-T050 verified with the fake provider and recorded responses); live provider runs NOT RUN (T029-T031 open, WSC-AI-1). Amended 2026-11-07 for D-08 (ADR-017). **Must not start before**: P3 research complete, spec 006 done, spec 008 T029 done.
**Input**: Roadmap phase P6 ([IMPLEMENTATION_ROADMAP.md](../../docs/planning/IMPLEMENTATION_ROADMAP.md)): "Implement provider abstraction, AI-assisted transformations, caching, and token optimization."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI stays off unless explicitly enabled (Priority: P1)

A migration engineer runs OdooFlux on customer modules. No customer code may leave the machine unless they explicitly enable AI and consent to sending code to a named provider.

**Why this priority**: Data exposure is irreversible (Principle III, D-08).

**Independent Test**: Run the full pipeline on golden fixtures with no AI flags and a network-blocking fake transport; assert zero provider calls.

**Acceptance Scenarios**:
1. **Given** no AI options, **When** a run completes, **Then** the report shows `ai_usage.requests = 0` and no transport was opened.
2. **Given** `--ai` without `--ai-consent-send-code`, **When** the run starts, **Then** it stops before discovery with a message naming the missing consent flag.
3. **Given** AI is enabled with a configured provider, **When** a finding is deterministically fixable, **Then** it is never sent to the provider.

---

### User Story 2 - AI proposes validated edits for eligible findings (Priority: P1)

For findings that are AI-eligible and have no deterministic fixer, the engine sends a minimal region (one function, class body, or XML element), receives replacement text, and accepts it only if it passes every validation layer and the protected-identifier check.

**Why this priority**: This is the value of the feature; validation makes it safe.

**Independent Test**: With the fake provider scripted to return (a) a correct patch, (b) a patch renaming a field, (c) a syntax-broken patch, (d) a truncated response, assert accepted/rejected outcomes and reasons.

**Acceptance Scenarios**:
1. **Given** an eligible finding and a valid patch, **When** applied, **Then** an `Edit` with `rule_id = ai:<provider>/<model>` is applied and the finding is `FIXED` only after re-scan.
2. **Given** a patch that renames a field, `_name`, `_inherit`, or removes an import, **When** checked, **Then** it is `REJECTED` with reason `protected_identifier_changed`.
3. **Given** `stop_reason = max_tokens`, **When** received, **Then** the response is rejected with reason `truncated` and no edit is planned.

---

### User Story 3 - Budgets, caching, and usage reporting (Priority: P2)

A team lead caps token spend per file, module, and job, and sees token usage and (when pricing is configured) cost in the report. Re-running on unchanged input costs nothing.

**Why this priority**: Cost control is required by OBJ-005 but builds on US1/US2.

**Independent Test**: Configure budgets on the fake provider; run twice; assert the over-budget request is skipped, usage totals match the provider-reported usage, and the second run makes zero calls.

**Acceptance Scenarios**:
1. **Given** a per-file budget smaller than the estimated request, **When** planning, **Then** the request is not sent and the finding records `ai_skipped: budget_file`.
2. **Given** an unchanged module and a populated verified-result cache, **When** re-run, **Then** zero provider calls occur and cached edits are re-validated.
3. **Given** pricing configured for a model, **When** the run ends, **Then** the report shows cost per request and total; without pricing, cost is `null` and labelled "not configured".

---

### User Story 4 - Pluggable providers (Priority: P3)

A developer adds a provider (Anthropic, OpenAI-compatible, or local endpoint) by implementing the provider contract, without editing the core engine.

**Independent Test**: Contract test suite runs against the fake provider and every shipped adapter (network tests opt-in via `ODOOFLUX_AI_TESTS=1`).

**Acceptance Scenarios**:
1. **Given** a provider declaring a mismatched contract version, **When** loaded, **Then** loading fails with a specific error and the run continues without AI.

---

### User Story 5 - External-default providers with explicit data authorization (Priority: P1, D-08 / ADR-017)

An engineer enables AI and picks a provider (Claude, OpenAI, DeepSeek, Z.ai GLM, or optional local Ollama/vLLM/OpenAI-compatible). External is the default provider type, but nothing is sent until they authorize that provider and named data categories.

**Why this priority**: Source transmission to a third party is irreversible; D-08 requires explicit, provider-specific authorization.

**Independent Test**: Fake transport with scripted external and local providers; assert blocked, authorized, kill-switch, and no-fallback outcomes.

**Acceptance Scenarios**:
1. **Given** AI enabled with an external provider but no authorization naming that provider and data categories, **When** a request is planned, **Then** it is blocked with `authorization_missing` and no transport opens.
2. **Given** authorization for provider A only, **When** provider B is selected, **Then** transmission is blocked with `authorization_provider_mismatch`.
3. **Given** the kill switch is on, **When** any external request is planned, **Then** it is blocked (`transmission_disabled`); local providers are unaffected.
4. **Given** the selected provider fails or is blocked, **When** the request ends, **Then** no other provider is tried; the finding stays `OPEN` with `ai_error`.
5. **Given** a region containing credentials, secrets, or DB-dump content, **When** minimising, **Then** it is not sent (`sensitive_content_excluded`).
6. **Given** a model name absent from the provider catalog, **When** selected, **Then** configuration fails with `model_not_in_catalog`.

### Edge Cases

- Provider returns valid JSON that does not match the response schema → rejected (`schema_mismatch`), counted in usage.
- Provider rate limits → bounded retries with backoff; after the limit, findings stay `OPEN` with `ai_error`.
- Customer code contains instructions aimed at the model (prompt injection) → model output is data; plan, validation, and edit scope are unaffected (REQ-SEC-004).
- Region span changed between request and response (earlier edit in the same file) → before-text check fails, edit rejected, region re-requested at most once.
- Credentials passed on the command line (`--api-key`) → deprecated per D-10: accepted with a warning during the deprecation window, then rejected; never echoed.
- Token estimate unavailable for a provider → documented heuristic is used and marked `estimated` in usage.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: AI MUST be disabled by default; enabling requires an explicit flag, a configured provider, and an explicit consent flag to send code. Traces: REQ-AI-001, REQ-SEC-003
- **FR-002**: The core engine MUST interact with providers only through the `AIProvider` contract in [contracts/ai-provider.md](contracts/ai-provider.md); no provider SDK is imported by core. Traces: REQ-AI-001, REQ-ARC-001
- **FR-003**: Only findings whose rule has `ai_eligible = true` and no applicable deterministic fix MAY be escalated. Traces: REQ-AI-002
- **FR-004**: The prompt builder MUST send the smallest enclosing region (function, class body, or XML element), the rule documentation, and the cited evidence excerpt; line numbers MUST refer to the text actually sent. Traces: REQ-AI-004
- **FR-005**: Responses MUST conform to a declared response schema; non-conforming or truncated responses MUST be rejected with a reason code. Traces: REQ-AI-003, REQ-AI-005
- **FR-006**: Accepted replacement text MUST become an `Edit` and pass L1/L2 validation and the protected-identifier check (field names, model `_name`/`_inherit`, imports, XML IDs) before being kept. Traces: REQ-AI-003
- **FR-007**: Token budgets per request, file, module, and job MUST be enforced before sending; exhausting a budget skips further requests at that scope. Traces: REQ-AI-005
- **FR-008**: Usage (input, output, cached tokens, estimated flag) and cost (when pricing configured) MUST be recorded per request and aggregated in the report. Traces: REQ-AI-006
- **FR-009**: Verified results MUST be cached keyed by (content hash of region, rule ID, provider, model, prompt template version, evidence IDs); cached results MUST be re-validated before reuse. Traces: REQ-AI-007
- **FR-010**: Credentials MUST be read from environment variables or a secrets file outside scanned paths, and MUST be redacted from logs, reports, cache, and debug output. Traces: REQ-AI-008, REQ-SEC-003
- **FR-011**: Customer-code content MUST be treated as untrusted data in prompts (delimited, never interpolated into instructions), and AI output MUST NOT change the plan, rule set, or validation configuration. Traces: REQ-SEC-004
- **FR-012**: Retries MUST be bounded (configurable, default 2) with exponential backoff, applied only to transient errors. Traces: REQ-AI-005
- **FR-013**: AI MUST NOT create or modify rules or evidence; AI output for a finding without evidence-backed rule metadata MUST be refused. Traces: REQ-AI-002, REQ-EVD-003

*D-08 additions (ADR-017):*

- **FR-014**: External AI MUST be the default provider type; AI MUST still be disabled until explicitly enabled (FR-001). No GPU, local model, or inference service is required to install, start, or run. Traces: ADR-017, REQ-AI-001
- **FR-015**: First-class providers MUST be Anthropic Claude, OpenAI, DeepSeek, and Z.ai GLM; local endpoints (Ollama, vLLM, OpenAI-compatible) MUST be optional. The user selects provider and model. Traces: ADR-017, REQ-AI-001
- **FR-016**: All AI operations MUST pass through one gateway in `src/odooflux/ai/` with provider/model selection, configurable endpoints, per-provider adapters, timeouts, bounded retries (FR-012), explicit errors, and token/cost tracking where supported. Traces: ADR-017, REQ-AI-005
- **FR-017**: The gateway MUST NOT silently fall back to another provider on error, block, or budget exhaustion. Traces: ADR-017
- **FR-018**: Each provider MUST have a model catalog held as configuration (capabilities: context window, structured output, tool calling; optional pricing). Model names and prices MUST NOT be hardcoded; selecting an uncatalogued model MUST fail with `model_not_in_catalog`. Traces: ADR-017, REQ-AI-006
- **FR-019**: Transmitting code to an external provider MUST require explicit authorization naming the provider and the data categories (e.g. `source_python`, `source_xml`, `evidence_excerpt`). Credentials, secrets, database dumps, and unrelated customer data MUST NEVER be transmitted; content MUST be minimised before sending. Traces: ADR-017, REQ-SEC-003
- **FR-020**: A customer kill switch MUST disable all external transmission. Blocked transmission MUST NOT switch provider. Traces: ADR-017, REQ-SEC-003
- **FR-021**: API keys and prompt/response content MUST NOT be logged (extends FR-010); only metadata (provider, model, token counts, outcome) is logged. Traces: ADR-017, REQ-AI-008

### Key Entities

- **AIRequest / AIResponse**: see [contracts/ai-provider.md](contracts/ai-provider.md).
- **Budget**: limits per scope (request/file/module/job) for input and output tokens and optional cost.
- **UsageRecord**: provider, model, tokens, cost, cache hit, outcome, finding IDs.
- **CacheEntry**: key tuple, replacement text, validation digest, created_at.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With AI disabled, 0 provider calls across the full golden-fixture suite.
- **SC-002**: 100 % of scripted invalid fake-provider responses (renamed protected identifiers, syntax errors, schema mismatch, truncation) are rejected with the expected reason code.
- **SC-003**: A second run on unchanged input makes 0 provider calls.
- **SC-004**: Reported token totals equal the sum of provider-reported usage for every request in the test run.
- **SC-005**: Benchmark report (see [AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md](../../docs/planning/AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md#5-benchmarks)) is produced and its targets are set from the recorded baseline, not assumed.

## Assumptions

- D-08 approved (ADR-017, 2026-11-07): external is the default provider *type*; AI remains off until explicitly enabled; explicit provider- and category-specific authorization is required. Supersedes the earlier "no default provider" assumption.
- D-10 default applies: `--api-key` is deprecated with a warning for one minor release, then removed.
- Model identifiers, context windows, and prices are configuration data, never hardcoded.
- P5 rule metadata provides `ai_eligible` and evidence for each rule.

## Clarifications

### Session 2026-11-06

- Q: Which providers ship in P6? → A: Fake (tests), Anthropic Messages API, OpenAI-compatible chat completions, and a local OpenAI-compatible endpoint, all over stdlib `urllib`; SDK adapters optional. (Extended by D-08: OpenAI, DeepSeek, Z.ai GLM first-class; see FR-015.)
- Q: Unit of change returned by AI? → A: Replacement text for one engine-selected region (ADR-012); no whole-file rewrites.
- Q: Are XML views AI-eligible? → A: Only for findings the deterministic attrs converter marks unconvertible (P4/P5), same validation.
- Q: Default budget values? → A: None assumed; P6 records a baseline and sets defaults from it (documented in the benchmark report).

### Amendment: D-08 approved (ADR-017, 2026-11-07)

- External-first provider type; AI still off until enabled (FR-001 unchanged). Interpretation confirmed by the owner (default provider type, not default-on).
- P6 providers now also include DeepSeek and Z.ai (GLM), selected by the user, with a per-provider model catalog. No hardcoded model names. Capabilities differ per model.
- Per-provider data-category authorization and a customer kill switch for transmission are required beyond the existing consent flag.
- No silent provider fallback; blocked transmission never switches provider.
- Items marked new in ADR-017's scope split are now specified as FR-014–FR-021 and User Story 5 (tasks T035–T050). Still not implemented.
