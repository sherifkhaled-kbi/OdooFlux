# Data Model: Knowledge Acquisition Pipeline

All records are JSON, UTF-8, `sort_keys`, `indent=2`, trailing newline on disk; canonical compact form for digests (research R1). Every new record family has a schema in `src/odooflux/knowledge/schemas/<name>.schema.json` checked by the existing stdlib validator. Timestamps are UTC ISO-8601 `Z`. Integers only in digested manifests.

## Entity overview

```
SourceSpec 1..n -> SourceSnapshot (per source+revision) -> FileAccounting (per from/to pair)
SourceSnapshot pair (from,to) -> ChangeLedger -> ChangeRecord n
ChangeRecord -> EvidenceRecord n -> CandidateRule n -> Rule (rule_metadata)
Rules + Evidence + Ledger + CoverageManifest + provenance -> KnowledgeRelease -> KnowledgePackage
CoverageManifest -> ReleaseGateResult
```

## SourceSpec (registry entry, `source_registry.schema.json`)

| Field | Type | Notes |
|---|---|---|
| source_id | string | stable, `^[a-z0-9][a-z0-9._-]{2,63}$`, e.g. `odoo-community-17.0` |
| kind | enum | `GIT_COMMUNITY`, `DOCS`, `UPGRADE_SCRIPTS`, `ENTERPRISE_LOCAL`, `OCA`, `OPENUPGRADE`, `SNAPSHOT_PACK`, `DIRECTORY` |
| official | bool | false for OCA, OpenUpgrade; true only for odoo/odoo, odoo/documentation |
| url | string | allow-listed URL prefix for official kinds (existing E002 allow-list); `local:` scheme for local inputs |
| licence_access | enum | `PUBLIC_OPEN` (LGPL/CC), `ENTERPRISE_AUTHORIZED`, `UNKNOWN` plus `licence_id` string |
| branch | string | informational |
| revision | string | 40-hex SHA for git; content digest for pack/dir |
| scope | object | `modules` (list or `*`), `include` globs, `exclude` globs with `reason`, `file_kinds` |
| retrieved_at | string or null | |
| checksum | string or null | snapshot manifest digest after retrieval |
| status | enum | `DECLARED`, `RETRIEVED`, `VERIFIED`, `UNAVAILABLE`, `FAILED`, `SKIPPED_UNAUTHORIZED` |
| failure_reason | string or null | closed codes `REVISION_UNAVAILABLE`, `CHECKSUM_MISMATCH`, `AUTH_REQUIRED`, `NOT_ALLOWLISTED`, `IO_ERROR` plus text |
| required | bool | counts in metric M1 denominator |
| expected_origin | string or null | required for an official `local:` clone: the allow-listed https URL (under the kind's official prefix) that the clone's `origin` remote must match after normalisation. Declared identity only, not authenticity |
| origin_url | string or null | set on RETRIEVED from the verified snapshot; null before retrieval and for every source without a verified official clone |

Lifecycle: `DECLARED -> RETRIEVED -> VERIFIED`; any step may go to `FAILED`/`UNAVAILABLE`; `ENTERPRISE_LOCAL` without entitlement goes `SKIPPED_UNAUTHORIZED`. `VERIFIED` is terminal and immutable for a given revision.

## SourceSnapshot (`snapshot.schema.json`)

| Field | Notes |
|---|---|
| snapshot_id | `ss-` + first 12 hex of `snapshot_digest` |
| source_id, revision | from SourceSpec |
| entries | sorted list of `{path, sha256, size, kind}`; `path` canonical relative POSIX |
| snapshot_digest | sha256 of canonical JSON of `entries` plus `source_id` and `revision` |
| created_at | non-digested |
| limits | `{excluded: [{path, reason}]}` for files outside scope (reasons are listed, never dropped) |
| origin_url | optional `https` URL; present only for a verified official local clone (the normalised origin from `sources.official_origin`). Not part of `snapshot_digest` |

Blobs live in `objects/sha256/<aa>/<hex>`. Read verifies hash. Lifecycle: `CREATED -> VERIFIED`; corrupt blob moves it to `CORRUPT` (reported, not repaired silently).

## FileAccounting (`file_accounting.schema.json`, per from/to snapshot pair)

| Field | Notes |
|---|---|
| pair | `{from_snapshot, to_snapshot, step}` |
| files | sorted list `{path, change_kind (added/removed/modified/renamed_file), state, reason_code, domain, parser, error}` |
| state | `PENDING` (non-terminal), `ANALYZED`, `EXCLUDED`, `UNSUPPORTED`, `FAILED` |
| totals | counts per state; invariant `sum == len(files) == in-scope changed files` |
| independent_count | count from tool-independent listing (cross-check XC-INDEP) |

`reason_code` closed list: `OUT_OF_SCOPE_GLOB`, `GENERATED_FILE`, `BINARY`, `TOO_LARGE`, `NO_PARSER`, `NO_JS_ADAPTER`, `PARSE_ERROR`, `ENCODING_ERROR`, `TIMEOUT`, `OTHER` (OTHER needs free text). `EXCLUDED` and `UNSUPPORTED` always have a reason.

## ChangeRecord (entry of ChangeLedger, `change_ledger.schema.json`)

| Field | Notes |
|---|---|
| change_id | `CH-` + 16 hex (research R2). Immutable. |
| step | `NN-NN` step id (ADR-007) |
| domain | `python_orm`, `xml_view`, `xml_data`, `security`, `manifest`, `js_owl`, `assets`, `data`, `report_controller`, `migration_script`, `docs` |
| kind / subject | e.g. `field`, `method`, `view`, `model`, `route`, `dependency`; `subject_key` canonical string (`res.partner::field::foo`) |
| class | `ADDED`, `REMOVED`, `RENAMED_CANDIDATE`, `MOVED`, `SIGNATURE_CHANGED`, `BEHAVIOUR_CHANGED`, `DEPRECATED`, `REPLACEMENT_CANDIDATE`, `UNKNOWN` |
| detail | class-specific: `{from, to, score, basis, candidates[]}` for renames; old/new signature for signature changes |
| confirmed | bool, only meaningful for rename and replacement candidates; set only by a `confirm` action |
| locations | `[{snapshot_id, path, line, sha256}]` |
| disposition | `RULE_CREATED`, `EXISTING_RULE_LINKED`, `NO_CUSTOM_MODULE_IMPACT`, `DETECTION_ONLY`, `HUMAN_REVIEW`, `UNSUPPORTED`, `UNRESOLVED` |
| disposition_data | `{rule_ids[], evidence_ids[], rationale, reviewer, decided_at}`; `rationale` required for `NO_CUSTOM_MODULE_IMPACT` and `HUMAN_REVIEW` |
| proposed_by | `DETERMINISTIC`, `AI_PROPOSED`, `MANUAL` |
| history | append-only list of `{seq, at, actor, action, from, to, prev_hash}` |

Lifecycle of disposition: `UNRESOLVED` (initial) -> any other. Transitions between non-initial dispositions are allowed and recorded; moving back to `UNRESOLVED` needs a reason. Class transitions: `UNKNOWN`/`RENAMED_CANDIDATE` -> confirmed via action `confirm` (actor manual). Ledger file: `ledger/<step>.ledger.json` with `{schema, step, from, to, entries[sorted by change_id], ledger_digest}`.

## EvidenceRecord (existing schema, extended compatibly)

Existing required fields unchanged. Optional additions (all optional, `additionalProperties:false` kept):

| Field | Level | Notes |
|---|---|---|
| origin | record | `LEGACY_BUILTIN` (default meaning when absent), `KAP_DETERMINISTIC`, `KAP_MANUAL` |
| source_id | record | SourceSpec ref |
| change_ids | record | list of `CH-` ids supported |
| official | record | bool, false for OCA/OpenUpgrade-derived |
| content_sha256 | location | sha256 of the file bytes at the pinned revision |
| snapshot_ref | location | `snapshot_id` |

Rules: `AI_PROPOSED` is never a value of `origin` for evidence (AI cannot create evidence, REQ-KAP-017). `status` enum unchanged; KAP writes `DOCUMENTED_NOT_TESTED` at most unless `tools/verify_evidence.py`-equivalent verification ran, then `VERIFIED` per existing ADR-008 meaning. File name equals id check unchanged. Existing 200 records remain valid and unchanged.

## RuleMetadata (existing, optional additions)

| Field | Notes |
|---|---|
| origin | `BUILTIN` (absent means this), `GENERATED`, `MANUAL` |
| rev | integer revision counter matching the history sidecar |

`ai_eligible`, `maturity`, `fixer_ref`, tests: unchanged semantics. Generated rules: `maturity` `DETECT_ONLY` if positive and negative tests exist, else `DRAFT`; `review_required` true when class is `BEHAVIOUR_CHANGED`, `SIGNATURE_CHANGED`, or confidence below threshold.

## RuleHistory (`rule_history.schema.json`, `history/rules/<rule-id>.json`)

`{rule_id, created_by, created_at, entries[{rev, at, actor, action, summary, rule_sha256, provenance, validation_status, prev_hash}]}`. Actions: `create`, `edit`, `disable`, `enable`, `retire`, `link_evidence`, `add_test`, `promote`, `import`, `supersede`. `validation_status`: `NOT_RUN`, `PASSED`, `FAILED` with validator codes. Append-only; each entry hashes the previous (tamper evidence like the audit log).

## CandidateRule (`candidate_rule.schema.json`, `candidates/<step>.candidates.json`)

| Field | Notes |
|---|---|
| candidate_id | `CR-` + 16 hex of sha256(change_id + template_id + params canonical) |
| change_id | source change |
| template_id | from `extraction_templates/*.json` |
| rule | full proposed `rule_metadata` row (id, step, category, maturity DRAFT/DETECT_ONLY, risk, evidence ids, `detector_ref`, `params`, tests refs) |
| applicability | `{source_versions, target_versions, file_kinds, modules_scope}` |
| confidence | `HIGH`, `MEDIUM`, `LOW` (from closed table in templates; not a probability) |
| status | `PROPOSED`, `ACCEPTED`, `REJECTED`, `CONFLICT`, `SUPERSEDED` |
| origin | `DETERMINISTIC` or `AI_PROPOSED` |
| conflicts | list of `{kind, with}` |

Lifecycle: `PROPOSED -> ACCEPTED` (validator + dup/conflict + tests pass; writes rule and history entry, ledger disposition `RULE_CREATED`) or `-> REJECTED` (reason) or `-> CONFLICT` (waiting for decision). `AI_PROPOSED` items reach `ACCEPTED` only after the same checks plus a verified evidence record exist; acceptance never changes maturity above DETECT_ONLY.

## CoverageManifest (`coverage_manifest.schema.json`)

| Field | Notes |
|---|---|
| declared_scope | sources, modules, steps, domains |
| inventory | per source file counts, per snapshot digest |
| file_accounting_summary | per step state totals |
| metrics | eight entries, each `{id, numerator, denominator, status, denominator_definition}`; `status` `MEASURED` or `NOT_APPLICABLE` (denominator 0) |
| crosschecks | list `{id, status (PASS, FAIL, NOT_RUN, NOT_MEASURED), benchmark_id or null, benchmark_size, detail}` |
| gates | list of ReleaseGateResult |
| limits | list of strings (mandatory non-empty when `completeness` is `PARTIAL`) |
| completeness | `COMPLETE`, `PARTIAL`, `FAILED` |
| tool | `{version, schema_versions}` |
| manifest_digest | included in release digest |

Metric definitions (denominators are fixed here):

| Id | Metric | Numerator | Denominator |
|---|---|---|---|
| M1 | source_retrieval | required sources `VERIFIED` | required sources declared |
| M2 | file_scan | in-scope changed files `ANALYZED` | in-scope changed files; plus reported separately: excluded, unsupported, failed, pending |
| M3 | change_classification | changes with class not `UNKNOWN` | all changes |
| M4 | change_disposition | changes with disposition not `UNRESOLVED` | all changes |
| M5 | evidence | changes needing evidence (dispositions RULE_CREATED, EXISTING_RULE_LINKED, DETECTION_ONLY) having at least one valid EvidenceRecord | changes needing evidence |
| M6 | rule_validation | release rules (new or changed in this release) passing schema, dup/conflict and test gates | release rules new or changed |
| M7 | fix_verification | FIX_ENABLED rules passing G-SAFE | FIX_ENABLED rules in release (built-in grandfathered rows counted separately) |
| M8 | version_transition | transitions in the declared target set whose steps have verified sources, completed accounting and a ledger | transitions in declared target set (from `versions.json`) |

## ReleaseGateResult (`gate_result.schema.json`)

`{gate_id, name, blocking(bool), status (PASS, FAIL, WARN, NOT_RUN), reason_codes[], offenders[] (capped, count given), checked_at}`. Gates: `G-SRC`, `G-FILES`, `G-CLASS`, `G-DISP`, `G-EVID`, `G-MANIFEST`, `G-RULES` (schema, dup, conflict, tests), `G-SAFE`, `G-XCHECK`, `G-SECRETS`. Rule: `completeness=COMPLETE` iff all blocking gates `PASS`; `PARTIAL` iff only gates in the declared `allowed_partial` set fail and `limits` is non-empty; else `FAILED`. Gate details in contracts/coverage-and-gates.md.

## KnowledgeRelease (`release_manifest.schema.json`, `release.json`)

| Field | Notes |
|---|---|
| release_id | `kr-` + first 12 hex of `release_digest` |
| label | free text, e.g. `community-17.0-18.0-2026.11` |
| format | `odooflux.release/1` |
| parent_release | release_id or null (incremental builds) |
| framework | `{built_with, min_framework, max_framework}` |
| schema_versions | map family to version |
| files | sorted `[{path, sha256, size}]` of every file in the release tree except `release.json` |
| sources | list of `{source_id, revision, snapshot_digest, official, status, origin_url, snapshot_id}`; `origin_url` is null when absent. Bound in `release.json` and therefore in `release_digest` |
| provenance | `provenance/sources.json`: sorted entries `{source_id, kind, url, origin_url, revision, snapshot_id, snapshot_digest, official, status}` (gate 1 input). `url` is the verified https origin for an official local clone, never a local path. `snapshots/<snapshot_id>.json` ships the snapshot manifest (not blobs) |
| steps_covered | list of `{step, completeness, ledger_digest}` |
| coverage_manifest_digest | |
| completeness | copy for display; authoritative value is in coverage manifest |
| build | `{tool_version, build_time (SOURCE_DATE_EPOCH or fixed), host_free: true}` |
| release_digest | sha256 canonical JSON of the manifest without this field |

Lifecycle states of an installed release (kept in `releases/<id>/state.json`, outside the digest): `STAGED -> INSTALLED -> ACTIVE -> INSTALLED` (deactivated) `-> REMOVED`. Only `INSTALLED` and `ACTIVE` are loadable. Built-in release: synthetic `release_id: builtin`, digest computed over the packaged tree via `digest_tree` (lazy, only when a report needs it and a release is active; never written when built-in).

## KnowledgePackage (`package_manifest.schema.json`, `package.json`)

`{format: "odooflux.package/1", release_id, release_digest, created_with, compat:{min_framework,max_framework,schemas}, entries:[{path, sha256, size}], entry_count, total_size, contains_enterprise_derived(bool), redaction_scan:{status, scanner_version}}`. `integrity/SHA256SUMS` repeats entries. Package digest = sha256 of the `.ofkp` bytes (informational); identity is `release_digest`.

## ActivePointer (`active.json`)

`{format, release_id, digest, activated_at, previous:[{release_id, digest, deactivated_at}]}` written only via `atomic_write_text`. Absent file means built-in.

## Invariants (tested)

| Id | Invariant |
|---|---|
| INV-1 | Release digest is a function of file bytes and manifest only. |
| INV-2 | Published release directories are never modified (no write after `INSTALLED`). |
| INV-3 | `sum(file states) == in-scope changed files` per pair. |
| INV-4 | Every ledger change has exactly one disposition, one class. |
| INV-5 | A `FIX_ENABLED` rule has non-AI, non-unofficial linked evidence and passes gates, in any non-built-in release. |
| INV-6 | History chains verify for every rule, change and release. |
| INV-7 | Packages hold no path outside the manifest list. |
