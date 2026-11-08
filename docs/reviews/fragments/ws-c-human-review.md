# Workstream C (feature 007, AI assistance): human review fragment

Register fragment under ADR-019 item 5. Every item is `PENDING_HUMAN_REVIEW`. None records an approval; only a named human
reviewer can do that, in the consolidated register. The technical parts (T001 to T050 except where noted) are IMPLEMENTED
and VERIFIED by offline automated tests. Reviewer qualification names a role, not a person.

Common evidence: `specs/007-ai-assistance/verification-log.md`, `docs/planning/reports/AI_BENCHMARK_BASELINE.md`.

## WSC-AI-1. Live provider contract tests not run

| Field | Entry |
|---|---|
| Task / requirement | T029, T041 (live variants), T032 (real-provider half); TST-007-015, TST-007-024; REQ-AI-001, FR-015 |
| Component | `src/odooflux/ai/providers/{anthropic,openai_compatible}.py`, `tests/contract/ai/test_live_providers.py` |
| What to review | Run the opt-in suite against each provider the project claims to support (Anthropic, OpenAI, DeepSeek, Z.ai, one local endpoint) and read the results. Command: `ODOOFLUX_AI_TESTS=1 <KEY_VAR>=... ODOOFLUX_AI_<PROVIDER>_MODEL=<id from your catalog> python3 -m unittest tests.contract.ai.test_live_providers`. The suite sends only a trivial synthetic prompt (a few tokens), never customer code. |
| Why | The adapters were verified only against recorded or hand-written response bodies shaped after the providers' documented wire formats. Real endpoints may differ (error bodies, usage fields such as cached tokens, structured-output support, `max_tokens` parameter naming for newer models, DeepSeek and Z.ai specifics). |
| Evidence / tests | Offline: `tests.contract.ai.test_gateway_providers` (84 contract tests, 10 live skipped). Live: **NOT RUN** (no network, no keys, no owner-chosen model ids). The skip reason is printed by the suite. |
| Risk | Medium. A wrong field mapping would give wrong usage, cost or truncation handling for that provider, or a hard error; it cannot send unauthorized data (the gateway checks run before any adapter). |
| Reviewer qualifications | Engineer with API access and budget for each provider; able to read provider API docs. |
| Certification impact | Blocks any statement "provider X is supported" or "tested live". Does not block framework completion. Until run, describe the adapters as "offline-verified". |

## WSC-AI-2. Data-authorization policy sign-off

| Field | Entry |
|---|---|
| Task / requirement | T036, T037, T043, T044; FR-019, FR-020, FR-001; ADR-017 |
| Component | `src/odooflux/ai/authorization.py`, `src/odooflux/ai/gateway.py`, `src/odooflux/cli/ai_options.py` |
| What to review | (1) Allowed categories are exactly `source_python`, `source_xml`, `evidence_excerpt`; credentials, secrets, database dumps and customer data cannot be granted. (2) Both `--ai-consent-send-code` (every `--ai` run) and a per-provider `--ai-authorize provider=categories` grant (external providers only) are required, and the kill switch (`--ai-disable-external`, `ODOOFLUX_AI_DISABLE_EXTERNAL`) beats a grant. (3) Local and fake providers need no grant: a `local` provider is whatever endpoint the user configured, which may be a remote host on the user's network; the code does not verify that it is loopback. (4) A region matching the sensitive-content filter is excluded whole, never redacted and sent. (5) External endpoints must be `https://`. (6) Whether the default-provider-type reading ("external default type, AI still off until `--ai`") matches the owner's intent (ADR-017 says confirmed 2026-11-07). |
| Why | Source transmission to a third party is irreversible; this policy is the control. It is a data-handling decision, not only code. |
| Evidence / tests | `tests.unit.ai.test_authorization`, `test_minimisation`, `test_cli_options`; `tests.integration.ai.test_kill_switch`, `test_no_fallback`, `test_consent`; all pass offline. |
| Risk | High if wrong: unauthorized disclosure of customer code. Known gaps: the filter is pattern-based (see WSC-AI-3); `local` trust is declarative. |
| Reviewer qualifications | Data-protection or security lead with authority over customer-data handling; a person who has read the customer contracts that cover source code. |
| Certification impact | Production certification of AI use stays blocked until signed off (ADR-019 item 6). The default-off behaviour needs no sign-off to ship. |

## WSC-AI-3. Prompt-injection and secret-handling review

| Field | Entry |
|---|---|
| Task / requirement | T016, T024, T037, T040, T046; REQ-SEC-004, FR-010, FR-011, FR-021, REQ-AI-008 |
| Component | `src/odooflux/ai/prompts/{builder.py,templates/v1}`, `protected.py`, `providers/credentials.py`, `providers/transport.py`, `gateway.py` |
| What to review | Template v1 wording; the delimiter rule (a region containing `<code>` or `</code>` is skipped, not escaped); that model output only ever becomes an `Edit` for one region and passes syntax, region-shape, protected-identifier, L1, L2 re-scan and L3 checks; the sensitive-content regex set for false negatives (it does not detect generic high-entropy strings or secrets in non-literal forms) and for false positives that would silence useful escalations; the XML guard (DOCTYPE and ENTITY text in a replacement is refused); the `Secret` wrapper, the secrets-file rules (outside scanned paths, owner-only permissions on POSIX); that logging carries metadata only, and error bodies are never read into diagnostics; TLS uses the stdlib default certificate verification. |
| Why | Customer code is attacker-controlled text; secrets in customer repositories are common; a miss is a leak or a bad edit. Automated tests use canary values, which only prove the patterns catch what was anticipated. |
| Evidence / tests | `tests.unit.ai.test_prompt_injection`, `test_secret_redaction`, `test_minimisation`, `test_no_prompt_logging`, `test_protected_identifiers`, `test_response_handling`; `tests.regression.test_ai_findings` (F-AI-1,2,4,5,6,7). All pass offline. No penetration test, no fuzzing, no review of a real customer repository. |
| Risk | High for the filter's coverage; medium for injection (output is validated, but protected-identifier coverage is limited to fields, `_name`/`_inherit`/`_inherits`, imported names, XML ids, field references, `ref` and `t-name`). Known limits: methods and classes may be renamed in a statement-kind region; behaviour changes inside a function body are not detected beyond syntax and the re-scan. |
| Reviewer qualifications | Application-security engineer familiar with LLM prompt injection and secret scanning; an Odoo developer to judge the protected-identifier set. |
| Certification impact | Blocks a security claim for AI assistance. `review_required` rules cap modules at `NEEDS_REVIEW` even for accepted AI edits (kept as designed). |

## WSC-AI-4. Model and pricing configuration needing owner input

| Field | Entry |
|---|---|
| Task / requirement | T035, T042, T047; FR-018, FR-015; ADR-017 |
| Component | `src/odooflux/ai/catalog/providers.json` (packaged), user catalogs via `--ai-catalog` |
| What to review | The packaged catalog deliberately lists **no models and no prices**: model ids, context windows, output limits, structured-output and tool-calling capabilities, and pricing are the owner's configuration (Principle VI forbids asserting them). The owner must supply a catalog per provider before real use. The following defaults in the packaged file were written from general knowledge and are **unverified**: the four external base URLs, the `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY` variable names, and `options.anthropic_version`. Also decide: default budgets (none are set; the job budget is mandatory and has no default), model-by-complexity tiers (not implemented), per-model `max_tokens_param` for newer OpenAI models (option exists, default `max_tokens`), whether DeepSeek and Z.ai accept `response_format` (sent only when the model declares `structured_output`). |
| Why | Names, prices and endpoints change and are provider facts; code must not assert them. |
| Evidence / tests | `tests.unit.ai.test_catalog` (including a source scan that fails on model names or prices in `src/odooflux/ai`), `tests.contract.ai.test_gateway_providers`. Test catalogs use invented names (`m-one`, `t-model`). |
| Risk | Low to medium: a wrong endpoint or header gives clean `auth` or `invalid_request` errors, never a silent switch of provider. Wrong pricing gives wrong cost reports and cost budgets. |
| Reviewer qualifications | Project owner or a billing-aware engineer with access to each provider's current documentation and account. |
| Certification impact | None for the framework. Blocks "ready to use with provider X out of the box" and any cost claim. |

## WSC-AI-5. Items surfaced during implementation (not asked for, recorded for the register)

| Field | Entry |
|---|---|
| Task / requirement | T012, T026, T034; FR-003, FR-013, REQ-AI-006 |
| Component | Knowledge Base rule metadata; report model schema; packaging |
| What to review | (a) **No Knowledge Base rule has `ai_eligible = true`**, so a real run currently escalates nothing. Choosing which rules become AI-eligible, with evidence, is Knowledge Base work (`DEFERRED_KB`, backlog ID to be assigned by the owner); it was not done here. (b) The AI pass writes `state["ai_usage"]` in the report model's shape (`enabled`, `consent`, `providers`, text `budget_events`, `totals`, plus detail fields); `build_report` picks it up and the schema check passes (`test_pipeline_pass`). The HTML section prints per-provider rows from it. Whether the extra detail fields (outcomes, rejections, cache stats, L3 log) should be added to the schema is the reporting owner's call. (c) `odooflux/ai/catalog/providers.json` needs a `package-data` entry in `pyproject.toml` (the wheel-assets test fails until then). |
| Why | Without (a) the feature is inert by design; without a schema decision on (b) the extra fields are accepted but unspecified; without (c) a built wheel breaks `--ai`. |
| Evidence / tests | `tests.integration.packaging.test_wheel_assets` (fails on (c) at the time of writing); verification log scenario 3. |
| Risk | Low (all fail closed). |
| Reviewer qualifications | Project owner (a), reporting owner (b), packaging owner (c). |
| Certification impact | (a) limits what can be claimed about AI value; (c) blocks framework completion for 007 until fixed; (b) is a documentation and schema nicety. |
