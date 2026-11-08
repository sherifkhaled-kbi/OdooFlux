---
description: "Task list for P6 — Optional, Provider-Neutral AI Assistance"
---

# Tasks: Optional, Provider-Neutral AI Assistance

**Input**: Design documents from `/specs/007-ai-assistance/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/; P3 and P5 complete; D-08 approved (ADR-017). **007 MUST NOT start before: P3 research complete, spec 006 done, spec 008 T029 done.**
**Tests**: Required (constitution Principle V). Tests are written first and must fail before implementation.

**Scope legend**: T001–T034 = existing P6 scope. T035–T050 = new D-08 scope (ADR-017, FR-014–FR-021, US5). Implementation started under ADR-019 (framework-first delivery) by orchestrator instruction; a task is marked `[X]` only when its Done-when is met and the offline tests pass. T029, T030 and T031 stay unchecked: their Done-when needs a live provider run, which was not possible (no network, no keys). No item records human approval.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

## Phase 1: Setup

- [X] T001 Create `src/odooflux/ai/{providers,prompts,caching,usage}/__init__.py` and `src/odooflux/ai/escalation.py` module skeletons registered in the plugin registry (REQ-AI-001) — Done when: `python -c "import odooflux.ai"` succeeds from `src/` and the import-graph test (REQ-ARC-001) still passes.
- [X] T002 [P] Create fixture directory `tests/fixtures/ai/` with scripted fake-provider responses `mixed.json`, `truncated.json`, `protected.json`, `syntax.json` (REQ-AI-003) — Done when: each script lists request→response pairs and is loadable by `json.load`.

## Phase 2: Foundational

- [X] T003 [P] Contract test for provider registry and contract-version check in `tests/contract/ai/test_provider_contract.py` (REQ-AI-001; TST-007-001) — Done when: test fails before T006 and covers load success, mismatch error `contract_version_mismatch`.
- [X] T004 [P] Unit test: core modules import no provider SDK in `tests/unit/ai/test_core_isolation.py` (REQ-AI-001; TST-007-002) — Done when: test scans `src/odooflux/core/**` imports and fails on any `odooflux.ai.providers.*` or third-party import.
- [X] T005 Implement `AIRequest`, `AIResponse`, `ModelDescriptor`, `UsageRecord` dataclasses per `contracts/ai-provider.md` in `src/odooflux/ai/providers/types.py` (REQ-AI-001, REQ-AI-006) — Done when: TST-007-001 type checks pass.
- [X] T006 Implement provider registry with contract-version validation in `src/odooflux/ai/providers/registry.py` (REQ-AI-001) — Done when: TST-007-001 passes.
- [X] T007 Implement scripted `FakeProvider` in `src/odooflux/ai/providers/fake.py` (REQ-AI-001) — Done when: it replays T002 scripts deterministically and reports usage as scripted.

**Checkpoint**: providers can be registered and faked.

## Phase 3: User Story 1 — AI off unless explicitly enabled (P1) 🎯 MVP

- [X] T008 [P] [US1] Integration test: no AI flags → zero transport opens across golden fixtures, in `tests/integration/ai/test_ai_disabled.py` (REQ-AI-001; TST-007-003) — Done when: test asserts `ai_usage.requests == 0` and a socket-guard records no connection.
- [X] T009 [P] [US1] Integration test: `--ai` without consent stops before discovery, in `tests/integration/ai/test_consent.py` (REQ-AI-001, REQ-SEC-003; TST-007-004) — Done when: exit code is the configuration-error code and message names `--ai-consent-send-code`.
- [X] T010 [P] [US1] Unit test: deterministic-fixable findings are never escalated, in `tests/unit/ai/test_eligibility.py` (REQ-AI-002; TST-007-005) — Done when: rules with `fix` present or `ai_eligible=false` yield zero requests.
- [X] T011 [US1] Implement CLI/config options `--ai`, `--ai-provider`, `--ai-model`, `--ai-consent-send-code`, budget options, in `src/odooflux/cli/ai_options.py` (REQ-AI-001) — Done when: TST-007-003/004 pass.
- [X] T012 [US1] Implement eligibility filter in `src/odooflux/ai/escalation.py` (REQ-AI-002) — Done when: TST-007-005 passes.

## Phase 4: User Story 2 — Validated AI edits (P1)

- [X] T013 [P] [US2] Unit test: prompt builder selects smallest enclosing region and line numbers match sent text, in `tests/unit/ai/test_prompt_builder.py` (REQ-AI-004; TST-007-006) — Done when: Python function, class-body, and XML element fixtures produce expected regions; line numbers verified against sent text.
- [X] T014 [P] [US2] Unit test: response handling rejects truncated, schema-mismatch, syntax-invalid, out-of-region responses with reason codes, in `tests/unit/ai/test_response_handling.py` (REQ-AI-003, REQ-AI-005; TST-007-007) — Done when: each scripted case yields the documented code.
- [X] T015 [P] [US2] Unit test: protected-identifier check rejects renamed fields, `_name`, `_inherit`, removed imports, changed XML IDs, in `tests/unit/ai/test_protected_identifiers.py` (REQ-AI-003; TST-007-008) — Done when: 5 negative and 2 positive cases pass.
- [X] T016 [P] [US2] Unit test: prompt-injection fixture does not alter plan, rules, or validation config, in `tests/unit/ai/test_prompt_injection.py` (REQ-SEC-004; TST-007-009) — Done when: plan/validation digests before and after are equal and the injected text appears only inside the `<code>` block.
- [X] T017 [P] [US2] Integration test: accepted AI edit marks finding `FIXED` only after re-scan, in `tests/integration/ai/test_escalation.py` (REQ-AI-003, REQ-TRF-005; TST-007-010) — Done when: finding status comes from re-scan diff; a review-required rule keeps module status `NEEDS_REVIEW`.
- [X] T018 [US2] Implement region selection and versioned templates in `src/odooflux/ai/prompts/builder.py` and `src/odooflux/ai/prompts/templates/v1/` (REQ-AI-004, REQ-SEC-004) — Done when: TST-007-006 and TST-007-009 pass.
- [X] T019 [US2] Implement response → `Edit` conversion and protected-identifier check in `src/odooflux/ai/escalation.py` (REQ-AI-003) — Done when: TST-007-007, TST-007-008, TST-007-010 pass.
- [X] T020 [US2] Implement bounded retry/backoff for transient errors in `src/odooflux/ai/providers/transport.py` (REQ-AI-005) — Done when: unit test in TST-007-007 for rate-limit script shows ≤ configured retries.

## Phase 5: User Story 3 — Budgets, caching, usage (P2)

- [X] T021 [P] [US3] Unit test: nested budgets block sends and record exhaustion events, in `tests/unit/ai/test_budgets.py` (REQ-AI-005; TST-007-011) — Done when: request/file/module/job cases each skip with `skipped:budget_<scope>`.
- [X] T022 [P] [US3] Unit test: usage totals equal provider-reported usage; cost null without pricing, in `tests/unit/ai/test_usage.py` (REQ-AI-006; TST-007-012) — Done when: totals match fixture sums exactly.
- [X] T023 [P] [US3] Integration test: second run on unchanged input makes zero calls and re-validates cached edits, in `tests/integration/ai/test_cache.py` (REQ-AI-007; TST-007-013) — Done when: second run `provider_calls == 0`, `cache_hits > 0`, and a tampered cache entry is rejected and deleted.
- [X] T024 [P] [US3] Unit test: secrets never appear in logs, reports, cache, or debug files, in `tests/unit/ai/test_secret_redaction.py` (REQ-AI-008, REQ-SEC-003; TST-007-014) — Done when: a canary key is absent from every artefact under the state dir and report outputs.
- [X] T025 [US3] Implement budgets in `src/odooflux/ai/usage/budgets.py` (REQ-AI-005) — Done when: TST-007-011 passes.
- [X] T026 [US3] Implement usage accounting and configured-pricing cost in `src/odooflux/ai/usage/usage.py`, emitted into `ReportModel.ai_usage` (REQ-AI-006) — Done when: TST-007-012 passes.
- [X] T027 [US3] Implement cache per `contracts/budget-and-cache.md` in `src/odooflux/ai/caching/cache.py` (REQ-AI-007, REQ-SEC-003) — Done when: TST-007-013 passes.
- [X] T028 [US3] Implement credential loading (env, secrets file outside scanned paths) and deprecation warning for `--api-key` per D-10 in `src/odooflux/ai/providers/credentials.py` (REQ-AI-008) — Done when: TST-007-014 passes and `--api-key` prints a deprecation warning without echoing the value.

## Phase 6: User Story 4 — Pluggable providers (P3)

- [ ] T029 [P] [US4] Opt-in contract tests for Anthropic and OpenAI-compatible adapters in `tests/contract/ai/test_live_providers.py` (REQ-AI-001; TST-007-015) — Done when: suite skips without `ODOOFLUX_AI_TESTS=1` and, when enabled with credentials, passes the shared contract checks.
  - Technical part: IMPLEMENTED and VERIFIED offline (recorded responses, `tests/contract/ai/test_gateway_providers.py`). Certification: live provider run NOT RUN, PENDING_HUMAN_REVIEW, register fragment `docs/reviews/fragments/ws-c-human-review.md` item WSC-AI-1 (register ID to be assigned: FHR-nnn).
- [ ] T030 [US4] Implement `src/odooflux/ai/providers/anthropic.py` over stdlib transport (REQ-AI-001, REQ-AI-006) — Done when: TST-007-001 (offline, recorded responses) and TST-007-015 (opt-in) pass.
  - Technical part: IMPLEMENTED and VERIFIED offline (recorded responses, `tests/contract/ai/test_gateway_providers.py`). Certification: live provider run NOT RUN, PENDING_HUMAN_REVIEW, register fragment `docs/reviews/fragments/ws-c-human-review.md` item WSC-AI-1 (register ID to be assigned: FHR-nnn).
- [ ] T031 [US4] Implement `src/odooflux/ai/providers/openai_compatible.py` usable for local endpoints via configurable base URL (REQ-AI-001, REQ-AI-006) — Done when: same as T030.
  - Technical part: IMPLEMENTED and VERIFIED offline (recorded responses, `tests/contract/ai/test_gateway_providers.py`). Certification: live provider run NOT RUN, PENDING_HUMAN_REVIEW, register fragment `docs/reviews/fragments/ws-c-human-review.md` item WSC-AI-1 (register ID to be assigned: FHR-nnn).

## Phase 7: Polish & Cross-Cutting

- [X] T032 (fake-provider baseline only; real-provider run NOT RUN, see WSC-AI-1; targets not set) Benchmark harness and baseline report in `tests/benchmarks/ai/run_benchmark.py` and `docs/planning/reports/AI_BENCHMARK_BASELINE.md` using metrics from AI_ARCHITECTURE §Benchmarks (REQ-AI-005, REQ-AI-006; TST-007-016) — Done when: baseline numbers for acceptance rate, rejection rate by reason, tokens per accepted edit, and calls per finding are recorded on the AI fixture corpus with the fake provider and (opt-in) one real provider.
- [X] T033 [P] Regression tests citing legacy findings F-AI-1, F-AI-2, F-AI-4, F-AI-5, F-AI-6, F-AI-7 in `tests/regression/test_ai_findings.py` (REQ-TST-005, REQ-AI-003; TST-007-017) — Done when: one test per finding ID passes.
- [X] T034 Run [quickstart.md](quickstart.md) scenarios 1–5 and record results in the phase verification log (REQ-AI-001) — Done when: log shows expected outcomes for each scenario.

## Phase 8: D-08 scope (NEW, ADR-017) — User Story 5 (P1)

Tests first; T035–T041 must fail before T042–T049. Depends on Foundational (T003–T007).

- [X] T035 [P] [US5] [D-08] Unit test: model catalog loads per provider; uncatalogued model fails `model_not_in_catalog`; no model names/prices hardcoded (source scan) in `tests/unit/ai/test_catalog.py` (FR-018; TST-007-018) — Done when: all cases fail pre-implementation, then pass.
- [X] T036 [P] [US5] [D-08] Unit test: authorization requires provider + data categories; missing/mismatch/category-denied codes in `tests/unit/ai/test_authorization.py` (FR-019; TST-007-019) — Done when: each `authorization_*` code asserted.
- [X] T037 [P] [US5] [D-08] Unit test: sensitive-content filter excludes credentials, secrets, DB dumps, unrelated data; minimisation applied in `tests/unit/ai/test_minimisation.py` (FR-019; TST-007-020) — Done when: canary secrets never reach the fake transport.
- [X] T038 [P] [US5] [D-08] Integration test: kill switch blocks all external transmission, local unaffected, in `tests/integration/ai/test_kill_switch.py` (FR-020; TST-007-021) — Done when: `transmission_disabled` and zero external transport opens.
- [X] T039 [P] [US5] [D-08] Integration test: no silent fallback on error, block, or budget exhaustion in `tests/integration/ai/test_no_fallback.py` (FR-017, FR-020; TST-007-022) — Done when: with two providers configured, only the selected one is ever called.
- [X] T040 [P] [US5] [D-08] Unit test: API keys and prompt/response content absent from logs; only metadata logged, in `tests/unit/ai/test_no_prompt_logging.py` (FR-021; TST-007-023) — Done when: canary key and prompt text absent from all log output.
- [X] T041 [P] [US5] [D-08] Contract test: gateway timeouts and bounded retries per provider adapter (offline recorded responses) for Anthropic, OpenAI, DeepSeek, Z.ai GLM, local, in `tests/contract/ai/test_gateway_providers.py` (FR-015, FR-016; TST-007-024) — Done when: each provider passes shared checks; live variants opt-in (`ODOOFLUX_AI_TESTS=1`, ADR-016).
- [X] T042 [US5] [D-08] Implement model catalog loader and per-provider catalog config in `src/odooflux/ai/providers/catalog.py` and `src/odooflux/ai/catalog/` (FR-018) — Done when: TST-007-018 passes.
- [X] T043 [US5] [D-08] Implement authorization grants, minimisation, and sensitive-content filter in `src/odooflux/ai/authorization.py` (FR-019) — Done when: TST-007-019, -020 pass.
- [X] T044 [US5] [D-08] Implement gateway with selection, authorization check, kill switch, timeouts, no fallback in `src/odooflux/ai/gateway.py` (FR-016, FR-017, FR-020) — Done when: TST-007-021, -022 pass; `escalation.py` calls only the gateway.
- [X] T045 [US5] [D-08] Add CLI/config options for provider, model, authorization (provider + categories), kill switch, endpoint in `src/odooflux/cli/ai_options.py`; external is default provider type, AI still off until `--ai` (FR-001, FR-014) — Done when: TST-007-003/004 still pass and an option test covers defaults.
- [X] T046 [US5] [D-08] Enforce no key/prompt logging in gateway and adapters (FR-021) — Done when: TST-007-023 passes.
- [X] T047 [US5] [D-08] Configure OpenAI, DeepSeek, Z.ai GLM via `openai_compatible.py` (base URL + catalog); add dedicated adapter only if T041 shows a gap (FR-015) — Done when: TST-007-024 passes for each.
- [X] T048 [US5] [D-08] Update `contracts/ai-provider.md` version note and `CONTRACT_VERSION` if error kinds are non-additive (FR-016) — Done when: TST-007-001 passes.
- [X] T049 [D-08] Add D-08 scenarios (authorization, kill switch, no fallback) to [quickstart.md](quickstart.md) (FR-019, FR-020) — Done when: scenarios listed with expected outcomes.
- [X] T050 [D-08] Extend T034 verification log with D-08 scenarios (FR-014–FR-021) — Done when: log records each.

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T007) → US1 (T008–T012) → US2 (T013–T020) → US3 (T021–T028) → US4 (T029–T031) → Polish (T032–T034) → D-08 (T035–T050; tests T035–T041 first; T042–T047 after Foundational; T050 last).
- US2 depends on US1 eligibility (T012). US3 depends on US2 escalation (T019). US4 depends only on Foundational.
- Within each story, tests (TST) before implementation.

### Parallel Example: User Story 2

```bash
Task: "T013 prompt builder test in tests/unit/ai/test_prompt_builder.py"
Task: "T014 response handling test in tests/unit/ai/test_response_handling.py"
Task: "T015 protected identifier test in tests/unit/ai/test_protected_identifiers.py"
Task: "T016 prompt injection test in tests/unit/ai/test_prompt_injection.py"
```

## Implementation Strategy

MVP = Setup + Foundational + US1 (AI provably off). Then US2 (validated edits), US3 (cost controls), US4 (real providers). Stop and validate after each story.
