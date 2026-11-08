# WS-C provider configuration check

Date: 2026-11-07. Scope: `src/odooflux/ai/catalog/providers.json` and the adapters in `src/odooflux/ai/providers/`.
Rule: only official docs may change the catalog. No model names or prices were added.

## Checked against

| Provider | Catalog value | Source | Result |
| --- | --- | --- | --- |
| anthropic | `https://api.anthropic.com/v1/messages`, `x-api-key`, `anthropic-version: 2023-06-01` | https://platform.claude.com/docs/en/api/overview (fetched); https://platform.claude.com/docs/en/api/messages (fetched, endpoint `POST /v1/messages`); https://platform.claude.com/docs/en/api/versioning (fetched) | Endpoint matches. The overview lists `anthropic-version` as required and `x-api-key` as a supported legacy key header. `2023-06-01` is still a documented version. The latest documented version is `2026-10-21`. Catalog kept unchanged. |
| openai | base `https://api.openai.com/v1`, adapter appends `/chat/completions` | https://platform.openai.com/docs/api-reference/chat/create (HTTP 403 to the fetch tool; path confirmed only by search results) | Consistent with search results. Not confirmed from the primary page. |
| deepseek | base `https://api.deepseek.com`, adapter appends `/chat/completions` | https://api-docs.deepseek.com/ (fetched) | Matches: `https://api.deepseek.com/chat/completions`, Bearer auth. |
| zai | base `https://api.z.ai/api/paas/v4`, adapter appends `/chat/completions` | https://docs.z.ai/api-reference/introduction (fetched) | Matches: `https://api.z.ai/api/paas/v4/chat/completions`, `Authorization: Bearer`. The docs say GLM Coding Plan users need a separate endpoint; the catalog does not cover it. |

## Result

No catalog change. No official source contradicts an endpoint, header name, or the `anthropic-version` default.

## Legacy Anthropic adapter

`src/odooflux/ai/providers/legacy_anthropic.py` hardcodes `CLAUDE_MODEL = "claude-sonnet-4-6"` (line 21). It has no existing option to override it, and the file is the frozen P0 integration (`tests/unit/ai/test_catalog.py` treats it as legacy). Left unchanged, because making it configurable would require a new option.

## Unverified without a live key

- A real request to each endpoint: header acceptance, auth errors, and response shape.
- The OpenAI path on the primary OpenAI page (fetch returned 403).
- Whether `2023-06-01` stays accepted, and whether the Anthropic API still accepts `x-api-key` with `anthropic-version: 2023-06-01`.
- Z.ai GLM Coding Plan endpoint handling (not in catalog).
- Model ids, pricing, and rate or context limits (catalog is empty by design).
