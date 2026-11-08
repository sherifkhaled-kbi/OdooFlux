# Quickstart: AI Assistance (validation scenarios)

Commands run from the repository root with `PYTHONPATH=src python3 -m odooflux ...` (or the installed `odooflux`). Fixture
scripts for the fake provider are in `tests/fixtures/ai/`; a catalog with fake model names for the external-provider
scenarios is `tests/fixtures/ai/catalog.test.json`. Results of a recorded run are in
[verification-log.md](verification-log.md).

1. **Off by default**: `migrate --module ./addons/kbi_demo --from-version 14 --to-version 19 --fix --state-dir /tmp/st` →
   no `ai_config` in the run state, zero provider/transport opens (TST-007-003).
2. **Consent required**: add `--ai --ai-provider fake --ai-model fake-model --ai-budget-job-tokens 2000` without
   `--ai-consent-send-code` → usage error naming the flag, exit 2, no state directory created, no discovery.
3. **Scripted fake provider**: `ODOOFLUX_AI_FAKE_SCRIPT=tests/fixtures/ai/mixed.json migrate ... --fix --ai --ai-consent-send-code
   --ai-provider fake --ai-model fake-model --ai-budget-job-tokens 2000` → the pass runs; only findings of rules with
   `ai_eligible = true`, no fixer and evidence are escalated (the shipped knowledge base has none yet, so this CLI run
   sends zero requests; the escalation behaviour is exercised by `python -m unittest tests.integration.ai.test_escalation
   tests.integration.ai.test_pipeline_pass`, where accepted/rejected reasons match the scripts).
4. **Budget**: `--ai-budget-job-tokens 300` on the escalation tests (`tests.unit.ai.test_budgets`) → `skipped:budget_job`
   once, later requests skipped without a send, usage records show `0` provider requests.
5. **Cache**: run the pipeline twice against one state directory (`tests.integration.ai.test_cache`,
   `test_pipeline_pass.test_second_run_on_unchanged_input_makes_zero_provider_calls`) → second run `provider_calls: 0`,
   `cache_hits > 0`, cached edits re-validated, a tampered entry rejected and deleted.
6. **Real provider (opt-in)**: `ODOOFLUX_AI_TESTS=1 ANTHROPIC_API_KEY=... ODOOFLUX_AI_ANTHROPIC_MODEL=<id in your catalog>
   python3 -m unittest tests.contract.ai.test_live_providers` → the shared contract checks pass or the test skips with a
   reason. Not run when this feature was implemented (no network, no keys).

## D-08 scenarios (ADR-017, FR-014 to FR-021)

7. **Authorization missing**: external provider selected, no `--ai-authorize` → every planned request is blocked with
   `authorization_missing`; no transport opens; the finding stays `OPEN` with an `AI Error` note
   (`tests.integration.ai.test_pipeline_pass.test_unauthorized_external_provider_sends_nothing_and_leaves_finding_open`,
   `tests.unit.ai.test_authorization`).
8. **Provider mismatch and category denied**: `--ai-authorize beta=source_python` while `alpha` is selected →
   `authorization_provider_mismatch`; `--ai-authorize alpha=source_python` while evidence excerpts are sent →
   `authorization_category_denied` (`tests.unit.ai.test_authorization`, `tests.integration.ai.test_no_fallback`).
9. **Forbidden category**: `--ai-authorize alpha=credentials` → usage error `forbidden_category` before discovery.
10. **Kill switch**: `--ai-disable-external` or `ODOOFLUX_AI_DISABLE_EXTERNAL=1` → external requests blocked with
    `transmission_disabled` even with a valid grant; a local provider is unaffected
    (`tests.integration.ai.test_kill_switch`). The run header prints `EXTERNAL TRANSMISSION DISABLED (kill switch)`.
11. **No silent fallback**: with several providers in the catalog, only the selected one is ever contacted on error,
    block or budget exhaustion; the finding stays `OPEN` (`tests.integration.ai.test_no_fallback`).
12. **Sensitive content**: a region holding a private key, provider key, password literal, connection string with a
    password, or database-dump text is not sent (`sensitive_content_excluded`); canaries never reach the transport
    (`tests.unit.ai.test_minimisation`).
13. **Model catalog**: `--ai-provider openai --ai-model nope` → usage error `model_not_in_catalog`; `--ai-endpoint
    http://...` for an external provider → `endpoint_not_https`; `--ai-budget-job-cost` for a model without pricing →
    usage error ("pricing not configured") (`tests.unit.ai.test_catalog`, `tests.integration.ai.test_pipeline_pass`).
14. **No key or prompt in logs**: canary key and prompt text absent from all log output; only provider, model, token
    counts, attempts and outcome are logged (`tests.unit.ai.test_no_prompt_logging`).
