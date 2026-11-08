# Implementation Plan: Knowledge Acquisition Pipeline

**Branch**: `011-knowledge-acquisition-pipeline` | **Date**: 2026-11-08 | **Spec**: [spec.md](spec.md)
**Input**: spec.md, [PHASE0_ASSESSMENT.md](../../docs/planning/kap/PHASE0_ASSESSMENT.md), ADR-020 (PROPOSED)

## Summary

Add a release layer around the existing JSON knowledge base. A release is an immutable, digest-identified copy of the knowledge tree plus manifests. `migrate` resolves one active release (or the implicit built-in one) and loads it through the existing loader with a root parameter. Maintainers build releases with an offline-first pipeline: pinned sources, content-addressed snapshots, structural diff, change ledger with full file accounting, deterministic candidate rules, coverage and gates, deterministic ZIP packages with safe import, atomic activation, and rollback. Manual rule CLI and AI proposals share the same schema and validator. Nothing in the built-in path changes.

## Technical Context

| Item | Value |
|---|---|
| Language | Python 3.10+, stdlib only in core (ADR-002) |
| Optional | tree-sitter JS adapter (existing extra `js`), AI gateway (existing extra `ai`) |
| Storage | JSON, ZIP (stdlib `zipfile`), directory blob store; no SQLite |
| Testing | `unittest`; offline pinned synthetic fixtures; opt-in live |
| Opt-in env | `ODOOFLUX_KAP_LIVE_TESTS=1` (network), `ODOOFLUX_KAP_CLONES=<dir>` (real upstream clones), `ODOOFLUX_KAP_DOCKER_TESTS=1`. Runtime env, not test switches: `ODOOFLUX_KB_HOME` (kb-home), reused `ODOOFLUX_AI_DISABLE_EXTERNAL`, `ODOOFLUX_STATE_DIR`. Naming follows existing `ODOOFLUX_<AREA>_TESTS`. |
| Perf | Extract is linear in changed files; budget test on 2 000 synthetic files under 30 s (non-binding, recorded) |

## Constitution Check

| Principle | Check | Status |
|---|---|---|
| I dependency-light | stdlib core, lazy extras | PASS |
| II safe, reversible | atomic import/activate, rollback, no overwrite of releases | PASS |
| V tests first | tasks list test names; tests precede implementation per phase | PASS |
| VI official evidence only | OCA/OpenUpgrade labelled, capped DETECT_ONLY | PASS |
| IX modular extension | adapters and extractors registered by data, no per-release code | PASS |
| ADR-009 KB in `src/odooflux/knowledge/` | Built-in stays there. Installed releases live in kb-home, a new location. This extends ADR-009, recorded in ADR-020. | PASS with ADR |

## Source layout (new packages, nothing renamed)

| Path | Responsibility | Phase |
|---|---|---|
| `src/odooflux/knowledge/release/` | `canonical.py` canonical JSON and digests; `model.py` ids and dataclasses; `manifest.py`; `store.py` kb-home, installed releases, `active.json`; `resolver.py` `KnowledgeHandle`; `builtin.py` implicit release and digest; `diff.py` release diff; `audit.py` audit wrapper | P2 |
| `src/odooflux/knowledge/package/` | `limits.py`; `archive.py` safe reader and deterministic writer; `builder.py` export; `importer.py`; `validate.py`; `compat.py` | P2 |
| `src/odooflux/knowledge/authoring/` | `rule_store.py` read/write rule files; `history.py`; `checks.py` duplicate/conflict; `promote.py`; `ops.py` verbs | P3 |
| `src/odooflux/knowledge/acquisition/` | `sources.py` registry; `snapshot.py`; `blobstore.py`; `adapters/{git_local,directory,snapshot_pack,docs_html,enterprise_local,supplementary}.py`; `fetch.py` (only networked module, opt-in) | P4 |
| `src/odooflux/knowledge/extract/` | `driver.py`, `accounting.py`, `classify.py`, `rename.py`, `domains/{python_orm,xml_views,security,manifest,js_owl,assets,data,reports_controllers,migration_scripts}.py` | P5 |
| `src/odooflux/knowledge/ledger/` | `ledger.py`, `dispositions.py`, `ids.py` | P5 |
| `src/odooflux/knowledge/candidates/` | `templates.py` (data loader), `generator.py`, `evidence_builder.py`, `ai_proposer.py` | P6 |
| `src/odooflux/knowledge/coverage/` | `metrics.py`, `crosscheck.py`, `gates.py`, `manifest.py` | P7 |
| `src/odooflux/knowledge/pipeline.py` | lifecycle orchestrator (step registry) | P7 |
| `src/odooflux/cli/kap_source.py`, `kap_release.py`, `kap_package.py`, `kap_rule.py` | one CLI module per command group (own file, no shared edits) | P2 to P7 |
| `src/odooflux/knowledge/schemas/` | new: `source_registry`, `snapshot`, `change_ledger`, `file_accounting`, `candidate_rule`, `release_manifest`, `package_manifest`, `coverage_manifest`, `gate_result`, `rule_history` schemas. Modified (optional fields only): `evidence.schema.json`, `rule_metadata.schema.json` | P2 to P7 |
| `src/odooflux/knowledge/extraction_templates/` | JSON templates for candidate generation (packaged via `knowledge/**/*.json`) | P6 |
| `tests/unit/knowledge/kap/`, `tests/integration/kap/`, `tests/fixtures/kap/` | tests and synthetic fixtures | all |

`pyproject.toml` package-data already covers `knowledge/**/*.json`; the new `schemas/` and `extraction_templates/` JSON are therefore shipped. The wheel asset test must stay green (task T-packaging check).

## Key design choices (details in research.md)

1. Release = complete tree copy + `release.json`; release id is `kr-` + first 12 hex of the release digest. Immutable once published.
2. Resolve once per process into a `KnowledgeHandle(root, release_id, digest, builtin)`; thread it where files are read directly (see Integration points).
3. Built-in release is implicit: no handle metadata is written to reports, no files created.
4. Gates recompute locally on import and on load; package claims are never trusted.
5. All CLI under existing `odooflux knowledge` plus `odooflux release` is rejected: one entry point is kept. New groups hang off `knowledge`: `knowledge source`, `knowledge release`, `knowledge package`, `knowledge rule`, `knowledge ledger`, `knowledge coverage` (contracts/cli-surface.md).

## Integration points with shared files

| Shared file | Why touched | Owner task | Change kind |
|---|---|---|---|
| `knowledge/loader.py` | optional root parameter exposure, `load_active_knowledge(handle)` helper added; `load_knowledge(root=KNOWLEDGE_ROOT)` signature unchanged | T-P8-loader | additive |
| `knowledge/validator.py` | accept new schema keywords only if the new schemas need them (verify first; avoid) | T-P2-validator | additive, or none |
| `knowledge/checks.py` | dup/conflict checks as new functions; call-site gated by `not builtin` | T-P3-checks | additive |
| `cli/knowledge.py` | register new subparser groups via one `register(sub)` call per CLI module | T-P2-cliwire | additive |
| `cli/main.py` | none expected (knowledge routing exists); verify | T-P2-cliwire | none or one line |
| `cli/migrate.py` | `--kb-home`, `--require-complete-kb` options, coverage warnings | T-P8-migrate | additive |
| `builtins.py` | binder takes loader from resolver | T-P8-loader | one line |
| `reporting/model/model.py`, `report.schema.json`, renderers | `knowledge_release` field, schema enum | T-P8-report | additive |
| `versions/registry/loader.py`, `knowledge/view_index.py`, `validation/static/rng.py`, `validation/runtime/docker_env.py`, `validation/dependency/integrity.py`, `cli/support_statement.py` | read files by `__file__` path; take `KnowledgeHandle` root | T-P8-readers (one task each, disjoint) | additive default = built-in |

Integration points were listed from the assessment; each task begins by verifying the call site (grep) before editing.

## RTM gate impact (main agent decides edits)

`tests/unit/release/rtm_tools.py` reads: `docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md`, `specs/*/tasks.md` task lines (`TASK_RE = ^- \[( |x|X)\] (T\d+)`), test sources under `tests/` (for `REQ-XXX-nnn` and `TST-nnn-nnn` strings), and `docs/planning/KNOWLEDGE_BASE_BACKLOG.md`. `REQ_RE = REQ-[A-Z]+-\d{3}` already matches `REQ-KAP-nnn`; `TST_RE = TST-\d{3}-\d{3}` matches `TST-011-nnn`. Needed:

1. Regenerate or extend the RTM so the 47 REQ-KAP rows appear (the RTM is generated from PRODUCT_REQUIREMENTS.md and `specs/*/spec.md`; verify the generator scans `specs/011-*`).
2. Task-id format: the existing RTM keys tasks as `<feature>:T###`. KAP task ids in this feature are `T###` plus a phase suffix in the title only (ids stay `T001..`), so the regex works unchanged. Symbolic names such as `T-P8-loader` in this plan are aliases, defined in tasks.md as `T0xx`.
3. Every REQ-KAP needs a test file citing its `TST-011-nnn` or the REQ id, or a `RECORD` or `DEFERRED_KB` entry. Tests cite `TST-011-nnn` in the module docstring.
4. Opt-in tests must carry `skipUnless(`; strict mode flags REQs whose only tests are opt-in (REQ-KAP-044 live parts must also have an offline test).

## Phase map

| Phase | Content | Exit gate |
|---|---|---|
| P1 | spec, plan, research, data-model, contracts, tasks (this document set) | owner reviews ADR-020 and OD-K1..K12 |
| P2 | storage, release, package | TST-011 storage and package suites; byte-compat golden |
| P3 | manual rule CLI, history, dup/conflict, promote | CLI suite |
| P4 | source registry, snapshots, adapters | acquisition suite incl. pinned-failure |
| P5 | diff extraction, accounting, ledger | per-domain golden extraction |
| P6 | evidence extension, candidates, AI proposer | determinism suite |
| P7 | coverage, cross-checks, gates, pipeline | e2e synthetic pipeline |
| P8 | migration integration | socket-blocked migrate, report golden |
| P9 | acceptance, docs, RTM handoff | quickstart executed, CI check script green |

## Risks

| Risk | Mitigation |
|---|---|
| Files read outside `load_knowledge` miss the active release | T-P8-readers one task per reader plus a test that greps `KNOWLEDGE_ROOT` uses outside an allow-list |
| Byte-compat regress | golden hashes captured first (task T-P2-golden, before any edit) |
| Archive attack surface | stdlib `zipfile` with pre-flight central-directory checks; streaming copy with caps; table-driven attack tests |
| Rename false positives | candidates only, confirm action required |
| Shared-file contention among Haiku agents | wave plan serializes; one CLI module per group |
| Existing FIX_ENABLED rules (10) have no VERIFIED evidence | grandfathered for built-in; stricter gate applies to releases (REQ-KAP-018, 043) |
| Heavy DOM/AST diff cost | per-file, bounded size limit with `EXCLUDED:too_large` reason, never silent |

## Complexity tracking

New: release layer, archive safety, accounting. Justified because each has no existing equivalent (assessment sections 2 to 10). Rejected: SQLite, YAML, a second planning system, a plugin entry-point registry (data-driven registries suffice).
