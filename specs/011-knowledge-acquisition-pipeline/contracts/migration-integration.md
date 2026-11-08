# Contract: Migration Integration

Modules: `knowledge/release/resolver.py`, `knowledge/loader.py`, `cli/migrate.py`, reporting model (REQ-KAP-036..042, 001, 005). Verify each call site by grep before editing; the list comes from PHASE0_ASSESSMENT section 5 and 10.

## Resolution

```
resolve_knowledge(kb_home: Path|None, *, require_complete=False) -> KnowledgeHandle
KnowledgeHandle(root: Path, release_id: str, digest: str|None, builtin: bool, completeness: str|None, steps: dict)
```

1. kb-home = `--kb-home`, else `ODOOFLUX_KB_HOME`, else the default path (OD-K1). If it does not exist or has no `active.json`: return the built-in handle (`root=KNOWLEDGE_ROOT`, `builtin=True`) and do nothing else (no file created, no digest computed).
2. If `active.json` exists: read, verify the release (digest recomputed from file hashes, cost O(release size), cached per process). Failure raises `KnowledgeReleaseError` and `migrate` exits with the existing configuration-error code; no fallback to built-in (REQ-KAP-036).
3. `--require-complete-kb` (and OD-K10): refuse PARTIAL/FAILED.
4. Never network; no write to kb-home during migrate (read-only access).

## Loader

`load_knowledge(root=KNOWLEDGE_ROOT)` unchanged. New `load_active_knowledge(handle)` calls it with `handle.root`. `builtins.py` binder uses `lambda: load_active_knowledge(handle).rules`. Other direct readers take `handle.root` through an optional parameter whose default equals today's path: `versions/registry/loader.py`, `knowledge/view_index.py`, `validation/static/rng.py`, `validation/runtime/docker_env.py`, `validation/dependency/integrity.py`, `cli/support_statement.py`, `ai/integration.py`, `validation/runtime/log_classifier.py`. A guard test fails if a module outside an allow-list references `KNOWLEDGE_ROOT`.

## Rule execution

Release rules flow through the existing binder, `legacy_overlap` deduplication, `rule_maturity` cap, `RUNNABLE` filter and `apply_edits` unchanged. Additionally at load of a non-built-in release: any FIX_ENABLED rule failing the promotion gates 1 to 5 of manual-rule-cli is capped to DETECT_ONLY with warning `KAP_FIX_CAPPED` (defence in depth, REQ-KAP-039). Built-in rules are grandfathered.

## Transition coverage (REQ-KAP-037, 041)

After the plan is built, for each step `NN-NN` in the plan: look up `handle.steps[step]`. Built-in handle: no check, no new warnings (byte-compat). Active release:

| Release step status | Report effect |
|---|---|
| COMPLETE | none beyond release line |
| PARTIAL | warning `KAP_TRANSITION_PARTIAL` with limits summary |
| absent or FAILED | warning `KAP_TRANSITION_NOT_COVERED`; the step cannot contribute to `VERIFIED_SUCCESS` (existing `StatusInputs` gets the same signal as an unverified-scope limit; no new status value) |

Absence of findings is never described as "no issues" for a not-covered step; the human summary prints "knowledge not available for step X".

## Report

Optional top-level object, present only when a non-built-in release is active:

```
"knowledge_release": {"release_id": "kr-...", "digest": "<sha256>", "label": "...", "completeness": "COMPLETE|PARTIAL",
                       "steps": [{"step": "17-18", "completeness": "COMPLETE"}], "official_only": true}
```
`report.schema.json`: `schema_version` becomes `enum ["1.0.0","1.1.0"]`, `knowledge_release` optional; `SCHEMA_VERSION` constant stays `1.0.0` and the builder uses `1.1.0` only when the field is added (OD-K4). All renderers (JSON, HTML, SARIF properties, text) show one line. With no active release the report bytes are identical to today (golden test). Warning codes added to the existing `warnings` list shape.

## Unchanged

Rollback, L3 dependency integrity (`validation/dependency/integrity.py` still mandatory, `enterprise_modules.json` taken from the release root when present, else error for non-built-in), release-status decision, AI authorization. Tests for these run unmodified with an active fixture release.

## CLI additions on `migrate`

`--kb-home PATH`, `--require-complete-kb`. No other new options.

## Tests

`test_no_active_byte_identical`, `test_active_release_rules_used`, `test_corrupt_release_fails_closed`, `test_not_covered_step_warns_and_not_verified`, `test_partial_warns`, `test_report_has_release_id_digest`, `test_report_schema_both_versions`, `test_socket_blocked_migrate`, `test_fix_capped_on_gate_failure`, `test_guard_no_knowledge_root_outside_allowlist`, `test_legacy_overlap_with_release`, `test_rollback_contract_unchanged`.
