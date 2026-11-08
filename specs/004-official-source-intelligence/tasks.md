---
description: "Task list for feature 004 — Official Source Intelligence (Phase P3)"
---

# Tasks: Official Source Intelligence

**Input**: Design documents from `/specs/004-official-source-intelligence/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/knowledge-cli.md
**Tests**: Required (constitution Principle V). Write tests first and confirm they fail.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

---

## Phase 1: Setup

- [X] T001 Create `src/odooflux/knowledge/` package files listed in plan.md (empty modules with docstrings only) and `tests/{unit,integration,golden_fixtures}/knowledge/` directories (REQ-EVD-002) — Done when: `python -c "import odooflux.knowledge"` succeeds with `src` on the path, and `.gitkeep` files in the populated leaves are removed.
- [X] T002 [P] Write `docs/planning/research/RESEARCH_PROCEDURE.md` from OFFICIAL_SOURCES_STRATEGY.md §Research workflow and §Refresh workflow, with exact commands (REQ-EVD-005, REQ-VER-005) — Done when: a second agent can follow it to produce one evidence record without other context (peer check recorded in the PR).

## Phase 2: Foundational (blocks all stories)

- [X] T003 [P] Write schema documents `src/odooflux/knowledge/schemas/{evidence,version,revisions,allow_list,step_research,gap,rule_metadata}.schema.json` exactly per data-model.md (REQ-EVD-002) — Done when: each file parses as JSON and covers every field and constraint in data-model.md (review checklist in PR).
- [X] T004 [P] Create `src/odooflux/knowledge/official_sources/allow_list.json` from OFFICIAL_SOURCES_STRATEGY.md and `revisions.json` with the 16 pinned SHAs from OFFICIAL_EVIDENCE_REGISTER.md (REQ-EVD-004) — Done when: 7 allow-list prefixes and 16 revision entries are present.
- [X] T005 Write failing unit tests for the stdlib schema checker (type, enum, pattern, required, array items, nested objects, unknown keys) in `tests/unit/knowledge/test_schema_checker.py` (REQ-EVD-002; TST-004-001) — Done when: ≥ 20 cases exist and fail before T006.
- [X] T006 Implement the stdlib schema checker in `src/odooflux/knowledge/validator.py` supporting the subset of keywords used by T003 schemas (REQ-EVD-002, REQ-ARC-001) — Done when: TST-004-001 passes and the module imports only stdlib modules (import-graph test from P2 passes).

**Checkpoint**: schemas and checker ready.

---

## Phase 3: User Story 1 — Rules cannot exist without official evidence (P1) 🎯 MVP

### Tests

- [X] T007 [P] [US1] Write failing tests for evidence validation codes E001–E004 and W002 using fixture records in `tests/golden_fixtures/knowledge/invalid/` and `tests/unit/knowledge/test_evidence_validation.py` (REQ-EVD-002, REQ-EVD-004; TST-004-002) — Done when: one fixture per code exists, plus a non-allow-listed URL, a branch-name revision, a duplicate ID, and an unknown status.
- [X] T008 [P] [US1] Write failing tests for rule evidence enforcement (E005, E006) and maturity capping (W001), including the shared-rule `NOT_APPLICABLE` exception, in `tests/unit/knowledge/test_rule_evidence.py` (REQ-EVD-001, REQ-EVD-003; TST-004-003) — Done when: the tests cover a rule with no evidence, unknown evidence, UNVERIFIED+FIX_ENABLED (capped), CONFLICTING+FIX_ENABLED (capped), and a `*` rule with NOT_APPLICABLE (accepted).

### Implementation

- [X] T009 [US1] Implement evidence-record checks (allow-list prefix, revision pattern/catalogue, unique IDs, file name = ID, location rules for `present`/`absent`, `runtime_test_ref` required for VERIFIED) in `src/odooflux/knowledge/validator.py` (REQ-EVD-002, REQ-EVD-004) — Done when: TST-004-002 passes.
- [X] T010 [US1] Extend `src/odooflux/rules/shared/loader.py` to resolve rule evidence, reject E005/E006, and cap maturity per OFFICIAL_SOURCES_STRATEGY.md §Evidence statuses (REQ-EVD-001, REQ-EVD-003) — Done when: TST-004-003 passes and capped rules appear in the run report's warnings.
- [X] T011 [US1] Implement `odooflux knowledge validate` per contracts/knowledge-cli.md in `src/odooflux/cli/knowledge.py` (REQ-EVD-002) — Done when: integration test `tests/integration/knowledge/test_validate_cli.py` (TST-004-004) checks exit codes 0/1/2 and the sorted output format.

**Checkpoint**: invalid evidence or evidence-less rules cannot load.

---

## Phase 4: User Story 2 — Version registry as data (P1)

- [X] T012 [P] [US2] Write failing tests for registry loading: order, uniqueness, Online-release mapping, `SUPPORTED` preconditions, and a fixture adding `20.0` with no code changes, in `tests/unit/knowledge/test_versions.py` (REQ-VER-001, REQ-ARC-003; TST-004-005) — Done when: 6 cases exist and fail.
- [X] T013 [US2] Create `src/odooflux/knowledge/compatibility/versions.json` with 12.0–19.0, using `python_min` from EV-125, `online_releases` from EV-001 (15.1–18.4 as applicable), `research_status: RESEARCH_SEEDED`, and `support_status: UNSUPPORTED` (REQ-VER-001) — Done when: 8 entries validate and values cite their EV IDs in `evidence`.
- [X] T014 [US2] Implement registry validation rules in `src/odooflux/knowledge/validator.py` and expose `KnowledgeBase.versions` to `src/odooflux/versions/registry/` (REQ-VER-001, REQ-ARC-003) — Done when: TST-004-005 passes, including the 20.0 fixture.

---

## Phase 5: User Story 3 — Seed evidence migrated, gaps as data (P2)

- [X] T015 [P] [US3] Write a failing reconciliation test listing every EV and G-R ID from OFFICIAL_EVIDENCE_REGISTER.md and research.md, asserting each exists as data with the same claim, locations, and status, in `tests/unit/knowledge/test_seed_reconciliation.py` (REQ-EVD-002; TST-004-006) — Done when: the test enumerates 52 EV IDs and 19 gap IDs.
- [X] T016 [US3] Implement `src/odooflux/knowledge/seed_migration.py` and `odooflux knowledge migrate-seed` (idempotent) (REQ-EVD-002) — Done when: a second run produces no file changes (TST-004-007 in `tests/unit/knowledge/test_seed_migration.py`).
- [X] T017 [US3] Run the seed migration, then hand-complete fields the register does not state (`detection_method`, `proposed_transformation`, `risk`, `required_validation`) using the seed rule catalogue in VERSION_COMPATIBILITY_MATRIX.md, writing `src/odooflux/knowledge/evidence/EV-*.json` and `gaps.json` (REQ-EVD-001, REQ-EVD-002) — Done when: TST-004-006 passes and `odooflux knowledge validate` reports errors=0.
- [X] T018 [US3] Create `src/odooflux/knowledge/compatibility/<step>.research.json` for steps 12-13…18-19 with per-category status from the matrix, and 19-20 as NOT_ASSESSED (REQ-EVD-006, REQ-VER-001) — Done when: 8 files validate and every category below RESEARCHED lists ≥1 gap or `NOT_ASSESSED`.

---

## Phase 6: User Story 4 — Refresh evidence (P2)

- [X] T019 [P] [US4] Write failing tests that build two throwaway git repositories (old/new SHA) with files where a match is unchanged, moved, deleted, or the revision is unavailable, in `tests/integration/knowledge/test_refresh.py` (REQ-EVD-005; TST-004-008) — Done when: 4 classified cases plus the `--apply` demotion case exist; tests use only local `git`.
- [X] T020 [US4] Implement `src/odooflux/knowledge/refresh.py` (read via `git show <rev>:<path>`, ±50-line window, absent-claim search scope, candidate path search) and the `refresh` CLI (dry-run default, `--apply`) (REQ-EVD-005, REQ-EVD-003) — Done when: TST-004-008 passes and dry-run leaves `git status` clean.

---

## Phase 7: User Story 5 — Generated matrix (P3)

- [X] T021 [P] [US5] Write failing tests for matrix generation determinism, over-claim refusal (FR-009), and `--check` drift detection in `tests/unit/knowledge/test_matrix.py` (REQ-EVD-006; TST-004-009) — Done when: 3 cases fail.
- [X] T022 [US5] Implement `src/odooflux/knowledge/matrix.py` and the `matrix` CLI, producing the section layout of the current VERSION_COMPATIBILITY_MATRIX.md (REQ-EVD-006) — Done when: TST-004-009 passes.
- [X] T023 [US5] Replace `docs/planning/VERSION_COMPATIBILITY_MATRIX.md` with generated output and add the `--check` invocation to the test suite in `tests/integration/knowledge/test_matrix_committed.py` (REQ-EVD-006; TST-004-010) — Done when: the generated file differs from the planning version only in formatting, the semantic content (statuses, evidence IDs) is equal (diff reviewed in PR), and TST-004-010 passes.

---

## Phase 8: Polish & Cross-Cutting

- [X] T024 [P] Add a performance test asserting full validation < 5 s on the shipped data in `tests/benchmarks/test_knowledge_validate_perf.py` (REQ-EVD-002; TST-004-011) — Done when: it passes on the reference machine (opt-in benchmark suite).
- [X] T025 [P] Remove the `migrate-seed` command and `seed_migration.py` after T017 is merged; keep TST-004-006 (REQ-EVD-002) — Done when: the command is absent from `--help` and the reconciliation test still passes.
- [X] T026 Run quickstart.md end to end and record outputs in the phase evidence log `specs/004-official-source-intelligence/verification.md` (REQ-EVD-005, REQ-EVD-006) — Done when: all quickstart expectations are met and logged.

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T006) → US1 (T007–T011) and US2 (T012–T014) in parallel → US3 (T015–T018; needs T009, T014) → US4 (T019–T020; needs T017) and US5 (T021–T023; needs T018) → Polish.
- Feature dependency: P2 exit (package, contracts, rule loader skeleton, CLI entry point). T013–T018 data entry may be drafted after P1 and validated once T006/T009 exist.

## Parallel Example

```text
After T006: run T007, T008, T012 together (different test files).
After T017: run T019 and T021 together.
```

## Implementation Strategy

MVP = US1 + US2 (evidence enforcement + registry). These unblock features 005/006 rule loading.
US3–US5 complete the phase exit criteria in IMPLEMENTATION_ROADMAP.md.
