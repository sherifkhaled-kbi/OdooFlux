# Project Structure

The target layout follows [ADR-001](ARCHITECTURE_DECISIONS.md#adr-001--src-layout-legacy-script-untouched-until-cut-over).
All directories below were **created during planning as empty scaffolding** (`.gitkeep` only, no
`__init__.py`, no code). Existing files are unchanged. The current-to-target mapping is in
[MIGRATION_MAP.md](MIGRATION_MAP.md).

## Repository root

```text
OdooFlux/
├── odooflux.py                 EXISTING legacy entry point (unchanged; becomes a launcher in P2)
├── README.md, LICENSE, .gitignore   EXISTING (unchanged)
├── src/odooflux/               NEW scaffold: target package (P2+)
├── tests/                      NEW scaffold: test suites (P0+)
├── specs/                      NEW Spec Kit features 001–010 (planning)
├── docs/
│   ├── reviews/                audit report (planning)
│   └── planning/               this planning package
├── .specify/                   Spec Kit 1.3.1 (constitution 2.0.0)
└── .claude/skills/             Spec Kit agent skills
```

## `src/odooflux/` — responsibilities and ownership

| Directory | Responsibility | Key contracts | Owner phase | Depends on |
|---|---|---|---|---|
| `cli/` | Argument parsing, configuration loading, exit codes, legacy option compatibility | — | P2 (P8 UX) | core, reporting |
| `core/contracts/` | Data types and protocols from [CONTRACTS.md](architecture/CONTRACTS.md); `CONTRACT_VERSION` | all | P2 | stdlib only |
| `core/engine/` | Edit application, conflict resolution, before-text checks, re-scan diff, fix attribution | Edit, Finding | P2 (P4 extends) | contracts |
| `core/orchestrator/` | Runs plans: steps × modules, dependency order, parallelism, status decision hook | MigrationPlan | P2 | engine, versions, validation |
| `core/jobs/` | Run IDs, state directory, workspace copies, promotion | — | P2 | utils |
| `core/recovery/` | Run log, checkpoints, rollback, resume | — | P2 | jobs |
| `discovery/` | Find modules and manifests, source-version detection, ignore handling | ModuleRef | P2 | parsers/python (manifest) |
| `versions/registry/` | Loads OdooVersion data from knowledge | OdooVersion | P2 (data P3) | knowledge |
| `versions/graph/` | Consecutive-step planning, blocked-step detection | MigrationStep | P2 | registry |
| `versions/adapters/` | Per-version hooks that are not rules (e.g., Python range checks, file-kind mapping changes) | — | P5 | registry |
| `rules/shared/` | Rule base helpers, rule loader, metadata validation | Rule | P2 (loader), P5 | contracts, knowledge |
| `rules/python/` | ORM/Python rules | Rule | P5 | parsers/python, transformers |
| `rules/xml/` | View/data XML rules (attrs, view types, chatter, data tags) | Rule | P5 | parsers/xml |
| `rules/qweb/` | QWeb directive rules | Rule | P5 | parsers/xml |
| `rules/javascript/` | Module system, services, imports | Rule | P5 | parsers/javascript |
| `rules/owl/` | OWL components, hooks, templates, registries | Rule | P5 | parsers/javascript, parsers/xml |
| `rules/assets/` | Manifest `assets`, legacy `qweb` key, XML asset templates | Rule | P5 | parsers/python, parsers/xml |
| `rules/manifest/` | Manifest keys, version string, `depends` | Rule | P5 | parsers/python |
| `rules/security/` | ACL CSV, record rules, groups | Rule | P5 | parsers/xml |
| `parsers/python/` | `ast`/`tokenize` Documents and span queries (ADR-004) | ParserAdapter | P4 | stdlib |
| `parsers/xml/` | expat span locator, attribute lexer (ADR-005) | ParserAdapter | P4 | stdlib |
| `parsers/javascript/` | Optional tree-sitter adapter + stdlib detection lexer (ADR-006) | ParserAdapter | P4 | optional extra |
| `analyzers/` | Business-logic risk inventory (overrides, computes, constraints, crons, controllers) | Finding | P5 | parsers |
| `transformers/` | Language-specific edit helpers (indentation-safe line removal, attribute rewrite, expression converter) | Edit | P4 | parsers |
| `dependencies/` | Module dependency graph, cross-module reference index, core module lists per version | — | P2 (graph), P5 (data) | knowledge |
| `knowledge/official_sources/` | Allow-list of official domains/repos and pinned revision catalogue | — | P3 | — (data) |
| `knowledge/compatibility/` | Per-step rule metadata and research records (JSON) | Rule metadata | P3, P5 | schemas |
| `knowledge/evidence/` | Evidence records `EV-…` (JSON) | Evidence | P3 | schemas |
| `knowledge/schemas/` | JSON schemas + stdlib validator definitions | — | P3 | — |
| `ai/providers/` | Provider adapters (fake, Anthropic, OpenAI-compatible, local) | AIProvider | P6 | optional extras |
| `ai/prompts/` | Versioned prompt templates | — | P6 | — |
| `ai/caching/` | Prompt/result cache keyed by content hash | — | P6 | jobs (state dir) |
| `ai/usage/` | Token and cost accounting, budgets | — | P6 | — |
| `validation/syntax/` | L1: Python, XML, manifest, JS (adapter) | Validator | P0 logic in legacy → P2 | parsers |
| `validation/static/` | L2: post-fix re-scan; RNG (optional lxml) | Validator | P2, P7 (RNG) | rules |
| `validation/dependency/` | L3: modules, models, fields, XML IDs, groups, packages | Validator | P5, P7 | dependencies |
| `validation/runtime/` | L4: container install/upgrade, log analysis (ADR-011) | RuntimeEnvironment | P7 | optional extra |
| `validation/behavioral/` | L5: module tests on source/target, comparison | Validator | P7 | runtime |
| `reporting/model/` | Versioned report model and JSON schema | ReportModel | P2 | contracts |
| `reporting/terminal/` | Terminal renderer (ANSI; optional rich) | Renderer | P8 | model |
| `reporting/html/` | Static offline HTML renderer | Renderer | P8 | model |
| `reporting/exporters/` | JSON, SARIF 2.1.0, unified diff | Renderer | P8 | model |
| `utils/` | Hashing, atomic write, path safety, redaction | — | P0 (legacy), P2 | stdlib |

Note: `parsers/` and `validation/dependency/` are refinements of the brief's proposed structure
(the brief had analyzers/transformers only). `rules/qweb`, `rules/assets`, `rules/shared`,
`versions/graph`, `core/contracts`, and `knowledge/schemas` were added so that each responsibility
has exactly one home.

## Knowledge Acquisition Pipeline (feature 011, KAP)

Added by [specs/011-knowledge-acquisition-pipeline](../../specs/011-knowledge-acquisition-pipeline/spec.md) under [ADR-020](ARCHITECTURE_DECISIONS.md#adr-020--knowledge-acquisition-pipeline-releases-packages-and-offline-first-knowledge) (PROPOSED). Stdlib only (REQ-KAP-004); no SQLite (REQ-KAP-003); network only in `knowledge/acquisition/fetch.py` (REQ-KAP-001). Implementation is technically complete and checked offline; nothing here is certified. Human items are in [docs/reviews/fragments/kap.md](../reviews/fragments/kap.md). Integration decisions and open items are in [kap/INTEGRATION_NOTES.md](kap/INTEGRATION_NOTES.md).

| Path | Responsibility |
|---|---|
| `knowledge/release/` | Knowledge release model, canonical digests, kb-home store, read-only fail-closed resolver, promotion gates (`safety.py`), provenance writer and verifier (`provenance.py`), release diff, transition coverage check, built-in descriptor, kb-home audit log |
| `knowledge/package/` | Deterministic `.ofkp` package builder, safe archive reader (`archive.py`), compatibility checks, staged validation, importer with atomic activation |
| `knowledge/authoring/` | Manual rule verbs (`ops.py`, `promote.py`), authoring checks A001..A006, generated-versus-manual conflicts, rule history sidecars, byte-preserving rule store |
| `knowledge/acquisition/` | Source registry and status machine (`sources.py`), explicit network fetch (`fetch.py`), content-addressed blob store, snapshot builder |
| `knowledge/acquisition/adapters/` | Source adapters: directory, git local clone (`git_local.py`), snapshot pack, Enterprise local path, docs `.rst`, supplementary OCA and OpenUpgrade (`official: false`) |
| `knowledge/extract/` | Diff extraction driver, file accounting with terminal states, fact diff and classification, rename and replacement candidate pairing |
| `knowledge/extract/domains/` | Domain extractors: `python_orm`, `xml_views`, `js_owl`, `security`, `manifest`, `assets`, `data`, `migration_scripts`, `reports_controllers` |
| `knowledge/ledger/` | Change ledger with stable change ids (`ids.py`), dispositions, confirm and merge |
| `knowledge/candidates/` | Deterministic candidate generation, evidence builder for ledger changes, candidate acceptance (`accept.py`), AI proposer (`ai_proposer.py`, proposals only), extraction template loader |
| `knowledge/extraction_templates/` | JSON candidate skeletons for Python change classes (data, not code) |
| `knowledge/coverage/` | Eight coverage metrics (M1..M8), cross-checks against independent sources, release gates and completeness decision, coverage manifest and consistency check |
| `knowledge/pipeline.py` | Release build pipeline: ordered, individually re-runnable steps |
| `knowledge/schemas/` | KAP schemas: `active_pointer`, `change_ledger`, `coverage_manifest`, `package_manifest`, `release_manifest`, `rule_candidates`, `source_registry` |
| `parsers/extract_toolkit.py` | Document-level adapters that give the extract domains parsers through the composition root (keeps the REQ-ARC-001 import guard) |

CLI modules (`src/odooflux/cli/`), all reached through `odooflux knowledge ...`:

| Module | Command group |
|---|---|
| `kap_common.py` | Shared wiring for the knowledge acquisition command groups |
| `kap_source.py` | `knowledge source ...` (source registry and acquisition) |
| `kap_extract.py` | `knowledge extract` and `knowledge ledger ...` |
| `kap_candidates.py` | `knowledge candidates ...` and `knowledge ai propose` |
| `kap_rule.py` | `knowledge rule ...` (manual rule verbs) |
| `kap_release.py` | `knowledge release ...` (release lifecycle) |
| `kap_package.py` | `knowledge package ...` (package build and validation) |
| `kap_coverage.py` | `knowledge coverage show` and `knowledge coverage gates` |

Tests and fixtures: `tests/unit/knowledge/kap/`, `tests/integration/kap/` (offline; live and Docker tests are opt-in, REQ-KAP-044), `tests/fixtures/kap/` (synthetic `fixture_release` and golden hashes).

## `tests/`

| Directory | Contents | Owner phase |
|---|---|---|
| `tests/unit/` | Pure unit tests per component | P1+ |
| `tests/integration/` | CLI and pipeline tests on fixtures | P1+ |
| `tests/regression/` | One test per resolved finding (`F-…`) | P0+ |
| `tests/contract/` | Contract tests for every plugin kind | P2+ |
| `tests/golden_fixtures/` | Fixture modules per source version with expected outputs/reports | P1, P5 |
| `tests/runtime/` | Opt-in container tests (`ODOOFLUX_RUNTIME_TESTS=1`) | P7 |
| `tests/benchmarks/` | Opt-in performance benchmarks | P2 (baseline), P9 |

## Development tools and change records

These paths are introduced by feature tasks. `tools/` was scaffolded by feature 006 (T001); the other paths are created when their feature task runs.

| Path | Purpose | Introduced by |
|---|---|---|
| `tools/update_expectations.py` | Regenerates golden-fixture expectations from the legacy CLI; output is reviewed via `git diff` | [002:T018](../../specs/002-test-foundation/tasks.md) |
| `tools/extract_core_modules.py` | Extracts the core module list per pinned Odoo SHA for dependency checks (REQ-DEP-001) | [006 tasks](../../specs/006-version-compatibility-rules/tasks.md) |
| `docs/changes/P0_CHANGE_RECORD.md` | Behaviour changes made by P0 to the legacy script (Principle X) | [001 tasks](../../specs/001-safety-stabilization/tasks.md) |
| `docs/changes/P2_CUTOVER.md` | Accepted differences between legacy and new CLI at cut-over (REQ-ARC-004) | [003 contracts/cli.md](../../specs/003-core-architecture/contracts/cli.md) |

`tools/` holds developer utilities only. They are never imported by `src/odooflux/` and never
shipped as part of the tool.

## Scaffolding inventory (created during planning)

- 51 `.gitkeep` files, one in each leaf directory listed above for `src/odooflux/` and `tests/`,
  plus `docs/planning/phase-handoffs/` (removed once handoffs exist).
- 0 `__init__.py` files. P2 creates package initialisers deliberately (ADR-001).
- 0 executable files, 0 stubs, 0 dependency or packaging files.

## Structural risks

| Risk | Mitigation |
|---|---|
| `src/odooflux` package shadowing root `odooflux.py` | `src/` is not on `sys.path`; P2 switches the root script to a launcher only at cut-over (ADR-001) |
| Directories without owners drifting | Every directory has an owner phase above; P2 adds a structure test that fails on unknown top-level directories |
| Rule code and rule metadata diverging | Rule loader validates that every metadata entry has code and tests (REQ-TST-002) |
