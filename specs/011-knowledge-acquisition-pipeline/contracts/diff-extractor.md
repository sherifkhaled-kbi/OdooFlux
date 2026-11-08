# Contract: Diff Extractor

Module: `src/odooflux/knowledge/extract/` (REQ-KAP-011, 012, 013, 004).

## Interface

```
class DomainExtractor(Protocol):
    domain: str
    def handles(self, path: str) -> bool
    def facts(self, text: str, path: str) -> list[Fact]       # structural facts of ONE file version
    # raises ParseFailure(code, detail)

def extract_pair(from_snap, to_snap, scope, registry, *, limits) -> ExtractResult
# ExtractResult: changes: list[ChangeRecord-draft], accounting: FileAccounting
```

`Fact`: `{subject_key, kind, attrs (sorted dict), line}`. A change is the set difference of facts between the two snapshots for the same path or module, then classification.

## Pipeline per pair

1. List changed files = union of added, removed, modified (by blob sha256, not mtime). Apply scope globs; out-of-scope files are `EXCLUDED:OUT_OF_SCOPE_GLOB`.
2. For each file pick an extractor (`handles`); none: `UNSUPPORTED:NO_PARSER`; JS without adapter: `UNSUPPORTED:NO_JS_ADAPTER`.
3. Parse both versions with `odooflux.parsers.*`. `ParseFailure`: `FAILED:PARSE_ERROR` (change recorded as `UNKNOWN` with the file as subject so it reaches the ledger as `UNRESOLVED`, never hidden).
4. Fact diff, then classify (table below), then cross-file rename/move pairing (`rename.py`).
5. Every file ends in exactly one terminal state. `PENDING` exists only while running; the driver asserts none remain at exit (invariant INV-3).

## Classification

| Class | Rule |
|---|---|
| ADDED / REMOVED | fact only in `to` / only in `from`, no pairing |
| SIGNATURE_CHANGED | same `subject_key`, differing `attrs` of signature kind (args, defaults, field type/keywords, tag attrs) |
| BEHAVIOUR_CHANGED | same subject, same signature, differing body digest (python AST dump of body, XML subtree digest) |
| MOVED | same fact (identical attrs and body digest) at a different path/module |
| RENAMED_CANDIDATE | removed+added pair scoring at or above `rename_threshold` (data, default 0.8), unique one-to-one; `confirmed:false` always |
| REPLACEMENT_CANDIDATE | removed fact + added fact paired by documentation (`versionchanged`, `deprecated` text) or migration-script reference; `confirmed:false` |
| DEPRECATED | `@deprecated`/`warnings.warn(DeprecationWarning)`/docs `deprecated` directive/`deprecated` field attr newly present |
| UNKNOWN | ambiguous pairing, parse failure, unsupported-but-changed |

Thresholds and domain lists live in `extract/config.json` (packaged). No per-release code (REQ-KAP-016 analogue).

## Domains and facts

| Domain | Facts |
|---|---|
| python_orm | model names, `_inherit`, fields (+keyword attrs), methods (signature, decorators), constraints, imports from `odoo.*` |
| xml_view | view record ids, model, inherit_id, arch element/attribute set, xpath exprs |
| xml_data / security | record ids per model, `ir.model.access` rows, `ir.rule`, groups |
| manifest | depends, version, data, assets, license, installable |
| js_owl | exported symbols, registry keys, template names, imports |
| assets | bundle to file membership |
| data | CSV ids |
| report_controller | `@http.route` path/type/auth/methods, report actions, QWeb names |
| migration_script | pre/post/end script names, model/field names referenced via AST |

## Limits and determinism

Max file size from config (default 2 MiB): larger is `EXCLUDED:TOO_LARGE`. Per-file timeout (cooperative, token count cap). All outputs sorted; no wall-clock inside ids or digests. Extraction reads only snapshot blobs; never executes target code (ast/expat only; no import, no eval).

## Tests

`test_each_domain_golden`, `test_every_class_has_case`, `test_unparsable_is_failed_not_skipped`, `test_accounting_invariant`, `test_rename_never_confirmed`, `test_ambiguous_rename_unknown`, `test_js_without_adapter_unsupported`, `test_no_code_execution`, `test_extract_deterministic`.
