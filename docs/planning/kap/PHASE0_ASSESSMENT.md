# KAP Phase 0 Assessment: Knowledge Acquisition Pipeline

Read-only inspection of the repository at `main` (clean). No commits, no network, no Docker, no AI calls, no test suite run. Paths are relative to the repo root. Status key: IMPLEMENTED, PARTIAL, MISSING, UNVERIFIED.

## 1. Knowledge Base storage today

- **Package data is the KB.** `src/odooflux/knowledge/` (loader, validator, checks, matrix, refresh, view_index, runtime_runs, applicability, plus `schemas/`, `compatibility/`, `evidence/`, `official_sources/`, `gaps.json`). Status: IMPLEMENTED.
- **Root resolution.** `KNOWLEDGE_ROOT = Path(__file__).resolve().parent` in `knowledge/loader.py:7`. No environment override. `load_knowledge(root=KNOWLEDGE_ROOT)` takes a path parameter; the CLI exposes `--path` (`cli/knowledge.py:32,41,45`).
- **Repo-level `knowledge/`** holds only `knowledge/golden_corpus/` (`manifest.json` with per-file sha256, `INDEX.md`, `review/cases/` with 42 cases). It is not loaded by the engine and not shipped in the wheel.
- **Format.** All data is JSON (ADR-009). Each family has a schema in `schemas/*.schema.json`, checked by the stdlib subset validator `knowledge/validator.py`.
- **What the loader reads** (`knowledge/loader.py:61-101`): `official_sources/allow_list.json` (7 URL prefixes), `official_sources/revisions.json` (18 pinned entries), `evidence/*.json` (200 files), `compatibility/versions.json` (8 versions 12.0 to 19.0, 7 transitions), `compatibility/*.research.json` (8 steps, all RESEARCH_SEEDED except 19-20 NOT_ASSESSED), `gaps.json` (22 entries: 12 RESOLVED, 10 OPEN), `compatibility/*.rules.json` (91 rules), `rule_candidates.json` (43), `runtime_log_patterns.json`, `core_modules.json`, `rng_schemas.json`, `runtime_runs.json`. Missing files are tolerated; unreadable JSON goes to `kb.load_findings`.
- **Not loaded by `load_knowledge`:** `view_index/` (read by `view_index.load_view_index`), `runtime_images.json` and `enterprise_modules.json` (read directly by `validation/runtime/docker_env.py:28` and `validation/dependency/integrity.py:50`).
- **ID schemes.** Evidence `EV-nnn`, file name must equal id (checks E001). Gaps `G-R-nn`. Steps `NN-NN` (e.g. `17-18`) and wildcard `*` for shared rules. Rule ids are strings such as `12-13.python.api-multi-removed` (`compatibility/rule_candidates.json`). Revisions are 40-hex SHAs or catalogued tags.
- **Rule schema key fields** (`schemas/rule_metadata.schema.json`, items): required `id, step, category, maturity, risk, evidence, detector_ref, fixer_ref, tests`; optional `ai_eligible` (bool), `review_required`, `severity`, `file_kinds`, `params`, `validation`, `depends_on`, `conflicts_with`, `not_applicable_reason`, `retired_reason`, `legacy_ref`, `message`, `suggestion`. Maturity enum `DRAFT | DETECT_ONLY | FIX_ENABLED | RETIRED`. Fix field is `fixer_ref` (only legal with FIX_ENABLED, `rules/shared/loader.py:177-180`). Current counts: DETECT_ONLY 78, FIX_ENABLED 10, DRAFT 3; `ai_eligible` is False on all 91.
- **Evidence schema** (`schemas/evidence.schema.json`): required `id, rule_ids, category, source_applicability, target_applicability, description, url, repository, revision, locations, detection_method, proposed_transformation, risk, required_validation, status, checked_on, checked_by`; optional `runtime_test_ref`, `notes`. `status` enum `VERIFIED | DOCUMENTED_NOT_TESTED | UNVERIFIED | CONFLICTING | NOT_APPLICABLE`. Provenance per location: `path, branch, revision (SHA), line, match, kind`. Counts: 197 DOCUMENTED_NOT_TESTED, 3 UNVERIFIED, 0 VERIFIED. 0 of 200 locations carry a content hash.
- **Version registry.** `compatibility/versions.json` (schema `odooflux.versions/1`), read by `versions/registry/loader.py:10` and `knowledge/loader.py`. `versions/graph/graph.py` builds the step graph. No active-release concept.
- **Gaps.** `gaps.json` has no schema file (`schemas/gap.schema.json` exists, unverified against the data) and is not checked for duplicates.

## 2. Existing source acquisition

- **`knowledge/refresh.py`** (114 lines): verifies evidence locations with `git -C <clone> show <rev>:<path>` against local clones only. Classifies unchanged/moved/missing/unavailable; `apply_report` writes records (`json.dumps(sort_keys=True)`). No network. Status: PARTIAL (verification only; no fetch, no diff, no snapshot).
- **`tools/fetch_golden_corpus.py`** (stdlib): downloads 65 files for 12 entries (14.0 to 17.0) from `raw.githubusercontent.com` at pinned SHAs, verifies sha256 from `knowledge/golden_corpus/manifest.json`. Maintainer-only, not shipped. Status: IMPLEMENTED for corpus inputs.
- **`tools/verify_evidence.py`**: fetches each location at the pinned SHA over HTTPS, cache at `EV_CACHE` (default `/tmp/ev_cache`). Status: IMPLEMENTED as a maintainer check; the cache is outside the repo and has no integrity record.
- **`tools/extract_view_index.py`** (374 lines): builds `compatibility/view_index/<ver>.json` (8 files, e.g. 17.0 lists 413 modules) from `--repo` (git ls-tree/cat-file) or `--cache` (directory mirror). Output carries `repository`, `revision`, `content_sha256`, `tool`, `scope`. Fetch mode uses urllib against github/raw. Status: IMPLEMENTED.
- **`tools/extract_core_modules.py`** (88 lines): `git ls-tree` only; writes `core_modules.json` entries pinned to SHA and EV record. Status: IMPLEMENTED.
- **Pinning.** Commit SHAs in `official_sources/revisions.json` (18 rows: odoo/odoo 12.0 to 19.0, odoo/documentation 12.0 to 19.0, odoo/docker master x2). Allow-list enforced by `checks.py` E002. Status: IMPLEMENTED for SHA pinning. Tags are accepted but none are populated.
- **Snapshot or cache in the product:** none. No content-addressed store of upstream files, no KB digest across the tree. Status: MISSING.
- **Network surfaces in shipped code:** `ai/providers/transport.py`, `ai/providers/legacy_anthropic.py` (AI only). `validation/runtime/docker_env.py` runs `docker` via subprocess (opt-in runtime). `knowledge/refresh.py` runs git. No urllib/socket in migrate path otherwise (grep, see section 5).

## 3. Existing diff and extraction code

- **View index and core modules** are the only version-scoped extractors. Both read a pinned tree, not a diff. Status: PARTIAL.
- **No version diff extractor, no change ledger.** Diffing two revisions of one addon is absent. Status: MISSING.
- **Structural parsers** (`src/odooflux/parsers/`): `python/` (`document.py`, `spans.py`, stdlib ast + tokenize per ADR-004); `xml/` (`expat_locator.py`, `document.py`, `wellformed.py`, `attr_lexer.py`; stdlib expat per ADR-005); `javascript/` (`lexer.py` stdlib, `treesitter_adapter.py` optional extra per ADR-006). Status: IMPLEMENTED. Reusable for a per-file structural diff; no existing AST-level comparison of two trees.
- **Other extractors:** `dependencies/scan.py`, `analyzers/risk_inventory.py`, `rules/xml/view_refs.py` (view refs), `validation/dependency/integrity.py` (L3 core/enterprise lists).

## 4. Rule lifecycle today

- **Maturity gates.** `rules/shared/loader.py:36-39`: MATURITIES tuple; DETECT_ONLY needs positive and negative tests; FIX_ENABLED needs positive, negative, idempotence; `fixer_ref` required iff FIX_ENABLED. Status: IMPLEMENTED (enforced at bind time).
- **Execution filter.** `core/orchestrator/knowledge_rules.py`: RUNNABLE = DETECT_ONLY, FIX_ENABLED; DRAFT and RETIRED are skipped; only FIX_ENABLED gets a fixer; edits go through `apply_edits` (SC-005). Status: IMPLEMENTED.
- **Evidence cap.** `knowledge/checks.py:141-148` `rule_maturity` caps FIX_ENABLED to DETECT_ONLY when linked evidence is UNVERIFIED or CONFLICTING; W001 emitted (`checks.py:166-172`). Status: IMPLEMENTED.
- **Validator codes** (`knowledge/checks.py`): E001 schema, E002 allow-list, E003 revision not catalogued, E004 duplicate evidence id, E005 rule without evidence, E006 unknown evidence ref, E007 version order, E008 transition, W001 maturity cap, W002 duplicate claim. Status: IMPLEMENTED.
- **Duplicate rule ids** are not checked in `check_rules` (`checks.py:151-172`). Status: MISSING.
- **`conflicts_with` / `depends_on`** are in the schema and no knowledge-level check or loader enforces them (grep hits are in `core/engine/edits.py`, edit-level). Status: MISSING.
- **legacy_overlap:** `rules/shared/legacy_overlap.py` (`LEGACY_CATEGORIES`, `RETIRED_CATEGORIES = {"Page Attrs"}`, `covered()`); knowledge rows dedupe against legacy findings in `knowledge_rules.deduplicate`. Status: IMPLEMENTED.
- **Revision or history fields on rules:** none beyond `retired_reason` and `legacy_ref`. No changelog, no `superseded_by`. Status: MISSING.
- **Authoring tooling:** `odooflux knowledge` has exactly three subcommands, `validate`, `refresh`, `matrix` (`cli/knowledge.py:31-45`). No add, edit, promote, retire, or list. Status: MISSING for manual rule management.
- **Matrix:** `knowledge/matrix.py` (deterministic, refuses overclaim, FR-009); `matrix --check` detects drift. Status: IMPLEMENTED.

## 5. Migration integration

- **Load callers:** `builtins.py:66` (`RunRuleBinder(lambda: load_knowledge().rules, ...)`); `ai/integration.py:133-134`; `validation/runtime/log_classifier.py:60` (runtime patterns); `cli/support_statement.py:108`; `cli/knowledge.py`. Rules are bound per run by `core/orchestrator/run_inputs.py` and `knowledge_rules.bind_knowledge_rules` (`run.py:120`). Status: IMPLEMENTED.
- **Release id or digest in the report:** none. `reporting/model/report.schema.json` top level is `schema_version, run, modules, verification_scope, recovery, summary, ai_usage, warnings, provisional, severities`; `run` has `run_id, mode, status, source, target, steps, plan_status`. Only `runtime.digest` (container image) and `status_inputs_digest` exist. Status: MISSING.
- **Active release concept:** none (grep for active_release, release_id, kb_digest, knowledge_digest returns nothing). Status: MISSING.
- **Network during migrate:** grep for urllib, http, socket, subprocess and git outside `knowledge/refresh.py` and `ai/` finds only `validation/runtime/docker_env.py` (docker subprocess, runtime-only), `analyzers/risk_inventory.py` (module-name strings), and reporting modules (token table text, `urllib.parse.quote` in `sarif.py`). Status: IMPLEMENTED (no KB-fetch network in migrate). The AI gate in the migrate path is UNVERIFIED here.

## 6. Packaging facts

- `pyproject.toml` `[tool.setuptools.package-data]`: `odooflux = ["knowledge/**/*.json"]`, `odooflux.reporting.model = ["*.json"]`, `odooflux.ai = ["catalog/*.json"]`. Status: IMPLEMENTED.
- `MANIFEST.in` mirrors this for sdists (`recursive-include src/odooflux/knowledge *.json`).
- Wheel asset test: `tests/integration/packaging/test_wheel_assets.py` checks every source asset is in the wheel, every file a loader reads is in the wheel, and required dirs (`compatibility`, `evidence`, `view_index`, `schemas`, `official_sources`) are populated. Helper `_wheel.py`. Status: IMPLEMENTED.
- `dependencies = []` in `pyproject.toml`; optional extras `js`, `xml`, `rng`, `runtime`, `ai`, `rich`.

## 7. Spec Kit conventions

- **specs/** : `001-safety-stabilization` through `010-hardening-release`. **Next free number: `011`.** `.specify/feature.json` currently points to `specs/004-official-source-intelligence`.
- **Per-feature files:** `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `tasks.md`, `verification.md` or `verification-log.md` (007, 010), `contracts/` (003 to 010), `checklists/`. Extras in 002 (`reconciliation.md`) and 006 (`coverage-gaps.md`, `evidence-verification.md`, `research-notes/`, `AMENDMENT-REVIEW.md`).
- **.specify/** : `templates/` (spec, plan, tasks, checklist, constitution); `scripts/bash/` (`check-prerequisites.sh`, `common.sh`, `create-new-feature.sh`, `resolve-template.sh`, `setup-plan.sh`, `setup-tasks.sh`); `workflows/` (`workflow-registry.json`, `speckit/`); `integrations/` (`claude.manifest.json`, `speckit.manifest.json`); `memory/` (`constitution.md`, `.constitution-template.json`).
- **Constitution:** `.specify/memory/constitution.md` (Principles I to X, Technical Constraints, Development Workflow, Governance). ADR-002 notes "constitution 2.0.0".
- **ADR file:** `docs/planning/ARCHITECTURE_DECISIONS.md`. **Latest ADR: ADR-019** (line 285). Next free: **ADR-020**.
- **Requirement IDs:** `REQ-<AREA>-nnn` (e.g. REQ-EVD, REQ-SAF, REQ-TST, REQ-AI, REQ-MAN, REQ-DEP). Lists live in `docs/planning/PRODUCT_REQUIREMENTS.md` and `specs/*/spec.md`. Tests are `TST-<feature>-NNN`. No REQ prefix exists yet for knowledge acquisition (checked: no REQ-KNW/KAP/KB).
- **Task lines** (`specs/010-hardening-release/tasks.md`):
  - `- [X] T001 Implement the deterministic corpus generator ... (REQ-PRF-001) — Done when: ...`
  - `- [X] T002 [P] Record tests/benchmarks/budgets.json ... (REQ-PRF-001, REQ-PRF-004) — Done when: ...`
  - `- [X] T003 [P] Unit test: RTM completeness check ... (REQ-TST-005, REQ-TST-002; ...)`
  Markers: `[X]` done, `[P]` parallelisable. Human-gated items keep the original line unchecked plus `Certification: PENDING_HUMAN_REVIEW, register ID FHR-nnn` (ADR-019 section 3). Task IDs are `T###` per feature (RTM uses `<feature>:T###`).
- **REQUIREMENTS_TRACEABILITY_MATRIX.md** (`docs/planning/`): generated, not hand-edited (header says "planning helper"). It maps REQ, FR, task and TST tags across PRODUCT_REQUIREMENTS.md, `specs/*/spec.md` and `tasks.md`. Gate: `tools/ci_check.sh gates` runs RTM completeness (T003 of 010). KAP tasks must be added to the same scan to appear.

## 8. ADR and policy constraints binding KAP

- **ADR-002** stdlib core, optional adapters (status "Proposed", applied in constitution 2.0.0). Core must stay stdlib; network from core uses stdlib.
- **ADR-007** version graph of consecutive on-premise majors; Online releases map to the next on-premise major.
- **ADR-008** evidence status (claim) is separate from rule maturity (rule).
- **ADR-009** KB stored as JSON under `src/odooflux/knowledge/`, validated by stdlib checker; rule code lives in `rules/<language>/`.
- **ADR-010** presentation-independent report schema.
- **ADR-012** AI as an Edit-producing plugin.
- **ADR-013** job workspace, backups, state directory.
- **ADR-015** one Spec Kit feature per phase, no git branches.
- **ADR-017** D-08: external-first, provider-agnostic AI with explicit data authorization; kill switch; no fallback.
- **ADR-018** run parameters for DETECT_ONLY rules; all new rules DETECT_ONLY unless a later decision approves AUTO_TRANSFORM.
- **ADR-019** framework-first delivery; work states IMPLEMENTED / VERIFIED / PENDING_HUMAN_REVIEW / BLOCKED_TECHNICAL / DEFERRED_KB; provisional corpus must be labelled PROVISIONAL; L3 integrity mandatory; SC-005 (no automatic edits from review_required rules); register at `docs/reviews/FINAL_HUMAN_REVIEW_REGISTER.md`.
- **Constitution II** (safe, reversible, non-destructive) and **VI** (official evidence only) bind any new acquired knowledge. **IX** requires modular extension.
- **KB expansion deferral:** `docs/planning/KNOWLEDGE_BASE_BACKLOG.md`. Work starts only after the framework gate or in a session touching no framework file. Evidence must come from official sources at pinned SHAs and pass `tools/verify_evidence.py`; no invented evidence; new rules start DETECT_ONLY; promotion needs evidence, independent review and owner approval; every item ends with `knowledge validate`, `matrix --check` and the full suite.

## 9. Reusable utilities

- **`utils/atomic.py`**: `atomic_write_bytes`, `atomic_write_text` (IMPLEMENTED; reuse for package writes).
- **`utils/hashing.py`**: `sha256_bytes`, `sha256_file`, `digest_tree(root)` (returns a list), `finding_id`. Use for file and tree digests.
- **`core/recovery/audit_log.py`**: `AuditLog` hash-chained log, `verify_chain(path)`, `from_runlog`. Reusable for an acquisition or activation audit trail.
- **Redaction**: `utils/redaction.py` (`scrub`, `redact_text`, `is_secret_name`, `scan_for_canaries`, `scan_for_shapes`) and `utils/redact.py` (`redact`). Two modules with overlapping purpose; the architect should pick one.
- **Path safety**: `utils/paths.py` `is_within(child, root)` (resolve-based). No zipfile or tarfile usage anywhere in `src/` (grep), so archive extraction safety (zip-slip, symlink, size caps) is MISSING and must be designed.
- **Canonical JSON:** no shared helper. Writers use `json.dumps(..., sort_keys=True, indent=2) + "\n"` (`knowledge/refresh.py:112`, `cli/knowledge.py:64`, `reporting/model/json_renderer.py:13`); `ai/caching/cache.py:17` uses compact separators. Status: PARTIAL (no single canonical digest function).

## 10. Risks and gaps the architect must resolve

- **No release concept.** There is no KB release id, digest, manifest, active pointer, or history. Migration reports cannot record which KB produced a finding. Design the release manifest and its digest first.
- **Loader hardwired to the package path.** `KNOWLEDGE_ROOT` is `__file__`-relative, with no override or environment variable. Export/import/activate needs a root parameter threaded through `load_knowledge`, `load_view_index`, `versions/registry/loader.py` (`KNOWLEDGE_FILE`), `validation/static/rng.py`, `validation/runtime/docker_env.py`, `validation/dependency/integrity.py`, and `cli/support_statement.py`. Several modules read files without going through `load_knowledge`.
- **Two sources of version truth.** `official_sources/revisions.json`, `compatibility/versions.json`, `view_index/*.json` and `core_modules.json` each pin SHAs separately. A release must reconcile them or the validator must cross-check.
- **Evidence has no content hash.** 0 of 200 locations carry a sha256; refresh checks match text and line windows only. Acquisition needs a file digest per location.
- **Pinning is a SHA, not a snapshot.** `refresh` and `verify_evidence` require a live or local clone; nothing archives the bytes they checked. A reproducible acquisition needs a content store or manifest of digests.
- **Candidates overlap rules.** 39 of 43 `rule_candidates.json` ids already exist in `*.rules.json`; 12 candidates propose FIX_ENABLED, but the shipped rules are DETECT_ONLY (78) or FIX_ENABLED (10) with `ai_eligible` False. Promotion needs an explicit path that respects ADR-018 and the KB backlog.
- **No rule-level duplicate or conflict check**, and `conflicts_with` / `depends_on` are unenforced.
- **No authoring CLI** beyond validate, refresh and matrix. Manual rule management (list, show, add, promote, retire) is greenfield.
- **Coverage accounting** is text-only: `matrix.py` avoids percentages by design. KAP coverage needs a measured denominator (version pairs x categories) and a definition of "covered".
- **Archive safety** is absent (no zipfile/tarfile use), so importing knowledge packages needs path, symlink and size validation from scratch.
- **Runtime runs are empty** (`compatibility/runtime_runs.json`, 0 runs), so RUNTIME_VALIDATED is unreachable today; KAP outputs must not claim it.
- **Golden corpus is outside the package** and in repo root `knowledge/`; if KAP packages depend on it, the packaging test does not cover it.
- **Spec and governance:** KAP needs a new REQ prefix, a spec folder `011-*`, ADR-020 for the release model, and a register entry under ADR-019 for any human-review step. The RTM must scan the new tasks.
- **Unverified in this pass:** rule `ai_eligible` enforcement in the AI path (`ai/integration.py:133`), `gap.schema.json` coverage of `gaps.json`, the `DEFAULT_MATRIX` path, and whether the migrate path can reach AI when disabled. Each needs a targeted check before design relies on it.

## Capability status table

| Capability | Status | Evidence path |
|---|---|---|
| KB JSON storage and root resolution | IMPLEMENTED | src/odooflux/knowledge/loader.py |
| Stdlib schema validator | IMPLEMENTED | src/odooflux/knowledge/validator.py, schemas/ |
| KB validation codes E001 to W002 | IMPLEMENTED | src/odooflux/knowledge/checks.py |
| Evidence records (200) and status enum | IMPLEMENTED | src/odooflux/knowledge/evidence/, schemas/evidence.schema.json |
| Rule metadata (91 rows) | IMPLEMENTED | src/odooflux/knowledge/compatibility/*.rules.json |
| Version registry | IMPLEMENTED | src/odooflux/knowledge/compatibility/versions.json, src/odooflux/versions/registry/loader.py |
| Gaps register | PARTIAL | src/odooflux/knowledge/gaps.json (no load-time check) |
| Revision catalogue and SHA pinning | IMPLEMENTED | src/odooflux/knowledge/official_sources/revisions.json |
| Tag pinning | MISSING | src/odooflux/knowledge/official_sources/revisions.json (empty tags) |
| Allow-listed URLs | IMPLEMENTED | src/odooflux/knowledge/official_sources/allow_list.json, checks.py E002 |
| Evidence refresh (local git only) | PARTIAL | src/odooflux/knowledge/refresh.py |
| Corpus fetch with sha256 | IMPLEMENTED | tools/fetch_golden_corpus.py, knowledge/golden_corpus/manifest.json |
| Evidence fetch and verify | IMPLEMENTED | tools/verify_evidence.py |
| View index extraction | IMPLEMENTED | tools/extract_view_index.py, src/odooflux/knowledge/view_index.py |
| Core modules extraction | IMPLEMENTED | tools/extract_core_modules.py |
| Version diff extractor | MISSING | none |
| Change ledger | MISSING | none |
| Structural parsers (py, xml, js) | IMPLEMENTED | src/odooflux/parsers/ |
| Snapshot or content store | MISSING | none |
| Evidence content hash per location | MISSING | src/odooflux/knowledge/evidence/*.json (0 of 200 locations) |
| Maturity gates DRAFT/DETECT_ONLY/FIX_ENABLED | IMPLEMENTED | src/odooflux/rules/shared/loader.py, core/orchestrator/knowledge_rules.py |
| Evidence cap on maturity | IMPLEMENTED | src/odooflux/knowledge/checks.py:141-172 |
| Duplicate rule id check | MISSING | src/odooflux/knowledge/checks.py |
| Rule conflicts and dependencies enforcement | MISSING | src/odooflux/knowledge/schemas/rule_metadata.schema.json |
| legacy_overlap dedupe | IMPLEMENTED | src/odooflux/rules/shared/legacy_overlap.py |
| Rule revision or history fields | MISSING | src/odooflux/knowledge/schemas/rule_metadata.schema.json |
| Manual rule CLI (list/add/promote/retire) | MISSING | src/odooflux/cli/knowledge.py (validate, refresh, matrix only) |
| Compatibility matrix generator | IMPLEMENTED | src/odooflux/knowledge/matrix.py |
| Migrate loads KB rules | IMPLEMENTED | src/odooflux/builtins.py:66, core/orchestrator/run.py |
| KB release id and digest in report | MISSING | src/odooflux/reporting/model/report.schema.json |
| Active KB release concept | MISSING | none |
| No KB network in migrate | IMPLEMENTED | grep result, see section 5 |
| Knowledge packaged in wheel | IMPLEMENTED | pyproject.toml, MANIFEST.in, tests/integration/packaging/test_wheel_assets.py |
| Export, import, activate, rollback of KB | MISSING | none |
| Runtime runs recorded | MISSING | src/odooflux/knowledge/compatibility/runtime_runs.json (0 runs) |
| Atomic write utility | IMPLEMENTED | src/odooflux/utils/atomic.py |
| Hashing utility | IMPLEMENTED | src/odooflux/utils/hashing.py |
| Hash-chained audit log | IMPLEMENTED | src/odooflux/core/recovery/audit_log.py |
| Redaction | PARTIAL | src/odooflux/utils/redaction.py, src/odooflux/utils/redact.py |
| Archive path and size safety | MISSING | none (no zipfile or tarfile in src) |
| Canonical JSON digest helper | PARTIAL | src/odooflux/knowledge/refresh.py, src/odooflux/reporting/model/json_renderer.py |
| Spec Kit next number and layout | IMPLEMENTED | specs/, .specify/ |
| REQ scheme and RTM | IMPLEMENTED | docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md, docs/planning/PRODUCT_REQUIREMENTS.md |
| KAP-specific REQ prefix | MISSING | none |
| AI gate in migrate path | UNVERIFIED | src/odooflux/ai/authorization.py, src/odooflux/ai/integration.py |
| gap.schema coverage of gaps.json | UNVERIFIED | src/odooflux/knowledge/schemas/gap.schema.json |
