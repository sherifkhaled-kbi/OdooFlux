# Verification log: AI Assistance (T034 and T050)

Recorded 2026-11-07 on the implementation machine: no network, no provider keys. Everything below ran offline with the scripted
fake provider or recorded transport responses. **Nothing here is a live-provider result** and **nothing here records human
approval**. Commands use `PYTHONPATH=src python3 -m odooflux`; "kbi_demo" is a copy of `tests/golden_fixtures/p0_kbi_demo_v14`.

## Quickstart scenarios 1 to 6 (T034)

| # | Scenario | Expected | Observed |
|---|---|---|---|
| 1 | No AI flags, fix and dry-run | zero provider or transport opens, no `ai_config` in state | PASS. `tests.integration.ai.test_ai_disabled` (transport and socket guards raise on any open; none recorded; gateway constructor patched to fail, never called). The report model's `ai_usage` shows `enabled: false`, no providers, zero requests. |
| 2 | `--ai` without `--ai-consent-send-code` | stops before discovery, names the flag | PASS. `usage error: --ai needs --ai-consent-send-code: source regions are sent to the selected provider only after you consent explicitly`, exit 2, no state directory created. |
| 3 | Scripted fake provider | accepted and rejected reasons match the script | PASS in tests (`test_escalation`, `test_response_handling`, `test_pipeline_pass`). CLI run with `ODOOFLUX_AI_FAKE_SCRIPT=tests/fixtures/ai/mixed.json ... --fix`: pass ran, an `ai_usage` record with zero requests (`providers: []` or empty totals), because no rule in the shipped knowledge base has `ai_eligible = true` (not expanded, ADR-019). |
| 4 | Job budget | over-budget request skipped with `skipped:budget_job` | PASS. `tests.unit.ai.test_budgets` (job, module, file, request scopes; latch and single event; actual usage replaces the estimate). |
| 5 | Cache | second run 0 provider calls, cache hits, re-validation, tamper rejected | PASS. `tests.integration.ai.test_cache` and `test_pipeline_pass.test_second_run_on_unchanged_input_makes_zero_provider_calls`. |
| 6 | Real provider (opt-in) | contract suite passes or skips with a reason | **NOT RUN.** `tests.contract.ai.test_live_providers` skips (10 skips: 5 providers x 2 tests) without `ODOOFLUX_AI_TESTS=1`; no keys, no network here. See review fragment item AI-1. |

## D-08 scenarios (T050; FR-014 to FR-021)

| # | Scenario | Observed |
|---|---|---|
| 7 | Authorization missing | PASS. External provider with no grant: `authorization_missing`, zero transport opens, finding stays OPEN with an `AI Error` note (`test_pipeline_pass`, `test_authorization`, `test_no_fallback`). |
| 8 | Provider mismatch and category denied | PASS (`test_authorization`: `authorization_provider_mismatch`, `authorization_category_denied`; unknown and forbidden categories always denied). |
| 9 | Forbidden category | PASS. `--ai-authorize alpha=credentials` prints `usage error: forbidden_category: credentials can never be sent`, exit 2. |
| 10 | Kill switch | PASS. `test_kill_switch`: `transmission_disabled` for every external adapter, zero opens, valid grant does not override, local provider unaffected. CLI header shows `AI auth : alpha=source_python; EXTERNAL TRANSMISSION DISABLED (kill switch)` when `ODOOFLUX_AI_DISABLE_EXTERNAL=1`. |
| 11 | No silent fallback | PASS. `test_no_fallback`: on 5xx, 401, authorization block, kill switch, provider-name mismatch and budget exhaustion the other configured providers (including local) record zero calls; finding stays OPEN with `error:<kind>` or `skipped:budget_job`. The gateway holds exactly one provider. |
| 12 | Sensitive content | PASS. `test_minimisation`: private key, AWS key, provider key, bearer header, password literal, connection string with password, `admin_passwd`, and three database-dump forms all give `sensitive_content_excluded`; canaries never reach the transport. |
| 13 | Model catalog | PASS. CLI: `--ai-provider openai --ai-model nope` gives `usage error: model_not_in_catalog: openai/nope`, exit 2; external `--ai-endpoint http://...` gives `endpoint_not_https`; `--ai-budget-job-cost` on a model without pricing gives a "pricing not configured" error. Source scan: no model name or price in `src/odooflux/ai` (the frozen legacy module is excluded by name). |
| 14 | No key or prompt in logs | PASS. `test_no_prompt_logging`: canary key, prompt text and response text absent from log records, stdout and stderr on success, HTTP error bodies and transport exceptions; metadata (provider, model, token counts, outcome) is logged. |

## Test counts at this point

AI suites: unit 123, contract 84 (10 opt-in live skipped), integration 48, benchmark 4 (1 opt-in skipped), regression 6.
Full default suite at the last run: 1533 tests, 33 skipped, 4 failures, none in AI code (see the workstream report): the
wheel-assets test reports `odooflux/ai/catalog/providers.json` missing from the wheel (needs a package-data line in
`pyproject.toml`, owned elsewhere); three golden and provisional-corpus tests belong to other workstreams.
