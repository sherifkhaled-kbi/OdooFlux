# Contract: Budgets and Cache

## Budgets

- Scopes nest: request ⊂ file ⊂ module ⊂ job. A request is sent only if `estimated_input + max_output_tokens` fits the remaining budget at **every** scope.
- After the response, actual usage replaces the estimate in all scopes.
- Exhaustion at a scope → all further requests in that scope are skipped with `skipped:budget_<scope>`; recorded once as an event.
- Unset budget at a scope = unlimited at that scope; the job budget MUST be set when AI is enabled (configuration error otherwise).

## Cache

- Key = sha256 of canonical JSON: `[region_text_sha256, rule_id, provider, model, prompt_template_version, sorted(evidence_ids), target_step]`.
- Location: `<state-dir>/ai-cache/<key[0:2]>/<key>.json` (outside scanned paths, REQ-SEC-003).
- Stored: replacement text, validation digest, prompt_version, created_at. No credentials, no request headers.
- Reuse: a hit is applied as an `Edit` and re-validated; a failed re-validation deletes the entry and the finding may be re-requested within budget.
- `--ai-no-cache` disables reads and writes; `--ai-clear-cache` deletes the cache directory.
