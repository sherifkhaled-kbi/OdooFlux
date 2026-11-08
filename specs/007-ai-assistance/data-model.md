# Data Model: AI Assistance

| Entity | Fields | Rules |
|---|---|---|
| ProviderConfig | `name`, `endpoint`, `models[]` (`id`, `context_window`, `max_output`, `pricing{input_per_mtok, output_per_mtok, cached_per_mtok}` optional), `credential_env`, `timeout_s`, `max_retries` | Loaded from config file/env; `pricing` absent → cost `null` |
| AIRequest | see [contracts/ai-provider.md](contracts/ai-provider.md) | `cache_key` required |
| AIResponse | see contract | `stop_reason ∈ {complete, max_tokens, error}` |
| Budget | `scope ∈ {request,file,module,job}`, `max_input_tokens`, `max_output_tokens`, `max_cost` (optional) | Checked before send; remaining tracked per scope |
| UsageRecord | `request_id`, `provider`, `model`, `input_tokens`, `output_tokens`, `cached_tokens`, `estimated` (bool), `cost` (nullable), `outcome ∈ {accepted, rejected:<reason>, skipped:<reason>, error:<kind>, cache_hit}`, `finding_ids[]`, `duration_ms` | One per attempt |
| CacheEntry | `key` (sha256 of key tuple), `replacement`, `validation_digest`, `created_at`, `prompt_version` | Reused only after re-validation |
| AIUsageSummary | totals per provider/model, per module, job totals, budget exhaustion events | Embedded in ReportModel `ai_usage` |

Rejection reason codes: `truncated`, `schema_mismatch`, `syntax_invalid`, `protected_identifier_changed`, `before_text_mismatch`, `validation_failed:<validator>`, `out_of_region`, `budget_*`, `consent_missing`.
