# Contract: AIProvider (refines [CONTRACTS.md § AIProvider](../../../docs/planning/architecture/CONTRACTS.md#aiprovider))

Contract version: 1.

**Version note (T048, ADR-017).** The D-08 additions below are additive: new `error_kind` values, new optional `AIRequest`
fields (`provider`, `data_categories`, `rule_id`, `meta`) and new `AIResponse` fields (`attempts`, `detail`). A provider
written against the earlier shape still loads and runs, and a consumer that ignores unknown kinds keeps working, so
`CONTRACT_VERSION` stays `1` (TST-007-001 passes unchanged). A future non-additive change (removing or renaming a kind
or field) must bump `CONTRACT_VERSION`; the registry then reports `contract_version_mismatch`.

**Usage normalisation.** `Usage.input` counts non-cached input tokens and `Usage.cached` counts tokens served from a
provider cache; adapters normalise to that. `AIResponse.attempts` is the number of provider attempts (retries included);
`usage` is summed over the attempts. A gateway block (authorization, kill switch, sensitive content) has `attempts = 0`.
`AIResponse.detail` is a short, content-free diagnostic (for example `http_429`); it never holds prompt text, response
text or a key.

## Provider

| Member | Obligation |
|---|---|
| `name: str` | Unique registry key, e.g. `anthropic`, `openai-compatible`, `fake` |
| `contract_version: int` | Must equal engine `CONTRACT_VERSION` else load error `contract_version_mismatch` |
| `models() -> list[ModelDescriptor]` | From configuration; never hardcoded |
| `complete(req: AIRequest) -> AIResponse` | No exceptions for provider/HTTP errors: returns `stop_reason = "error"` with `error_kind ∈ {auth, rate_limit, transient, invalid_request, unknown}` |
| `count_tokens(text, model) -> (int, estimated: bool)` | Uses provider counter if available, else documented heuristic (`ceil(len(utf8_bytes)/4)`) with `estimated = True` |
| `supports() -> set[str]` | Optional capabilities: `prompt_cache`, `json_schema`, `usage_cached_tokens` |

## Model catalog (D-08, ADR-017)

Per-provider configuration (JSON), not code. `models()` is derived from it.

| Field | Notes |
|---|---|
| `provider`, `model` | Catalog key; unknown model → `model_not_in_catalog` |
| `context_window`, `structured_output`, `tool_calling` | Per-model capabilities |
| `pricing?` | Optional; absent → cost `null` |
| `endpoint?` | Configurable base URL (local, Z.ai, DeepSeek, etc.) |

## Data-category authorization (D-08)

`AIRequest` gains `provider`, `data_categories: list[str]` (from `source_python`, `source_xml`, `evidence_excerpt`). The gateway sends only if an authorization grant names that provider and covers every category, the kill switch is off, and content passed the sensitive-content filter. Credentials, secrets, DB dumps, and unrelated customer data are never allowed categories. Blocked requests return `stop_reason = "error"`, never switch provider.

| `error_kind` (added) | Meaning |
|---|---|
| `authorization_missing` | No grant for provider |
| `authorization_provider_mismatch` | Grant names a different provider |
| `authorization_category_denied` | Category not covered |
| `transmission_disabled` | Customer kill switch on |
| `sensitive_content_excluded` | Region held credentials/secrets/dump data |
| `model_not_in_catalog` | Model absent from provider catalog |

Contract version stays 1 only if these are additive; otherwise bump and update `CONTRACT_VERSION`.

## AIRequest

| Field | Type | Notes |
|---|---|---|
| `request_id` | str | Unique per run |
| `model` | str | From configuration |
| `system` | str | Versioned template text; contains no customer code |
| `messages` | list[{role, content}] | Customer code only inside a delimited `<code>` block; evidence excerpts inside `<evidence>` |
| `response_schema` | JSON-schema subset | `{ "replacement": str, "notes": str, "cannot_fix": bool }` |
| `max_output_tokens` | int | ≤ remaining request budget |
| `budget_ref` | str | Scope chain request→file→module→job |
| `cache_key` | str | See [budget-and-cache.md](budget-and-cache.md) |
| `region` | {path, span, kind} | Engine-selected; response applies only here |

## AIResponse

`text`, `parsed` (validated against `response_schema` or `None`), `usage{input, output, cached, estimated}`, `stop_reason`, `error_kind?`, `cost?` (computed by usage module from configured pricing, not by provider).

## Engine obligations on response

1. `stop_reason != complete` → reject (`truncated` / `error:<kind>`).
2. `parsed is None` → reject `schema_mismatch`.
3. `cannot_fix = true` → finding stays `OPEN`, outcome `skipped:model_declined`.
4. Build `Edit(span=region.span, before=current text, after=replacement, rule_id="ai:<provider>/<model>")`.
5. Run protected-identifier check, then L1/L2 validators; any failure → `REJECTED`.
