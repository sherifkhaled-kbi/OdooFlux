---
description: "Task list for Core Architecture (P2)"
---

# Tasks: Core Architecture (P2)

**Input**: Design documents from `/specs/003-core-architecture/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/; P1 (002) complete;
D-01 and D-09 approved

**Tests**: Required. Each test task precedes the implementation it verifies.

All paths are relative to the repository root; `pkg/` = `src/odooflux/`.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…)`

---

## Phase 1: Setup

- [X] T001 Create `pyproject.toml`: project `odooflux`, `requires-python >=3.10`, `dependencies = []`, console script `odooflux = "odooflux.cli.main:main"`, `[project.optional-dependencies]` `js`, `rng`, `runtime`, `ai`, `rich` (empty lists until the owning phase pins versions), and `src` layout. Done when: `pip install -e .` in a clean venv installs no third-party package. (REQ-ARC-001)
- [X] T002 Create `pkg/__init__.py` (`__version__`), `pkg/__main__.py`, and `__init__.py` in each package listed in [plan.md](plan.md#source-code-repository-root). Delete the `.gitkeep` of those directories only. Done when: `PYTHONPATH=src python -c "import odooflux"` succeeds and the other scaffold directories still have `.gitkeep`. (REQ-ARC-001; REQ-ARC-002)
- [X] T003 [P] Create `docs/changes/P2_CUTOVER.md` with the sections "Intended differences", "Deprecated options (D-10)", and "Legacy rule waivers". Done when: the file exists and is linked from `tests/README.md`. (REQ-ARC-004)

---

## Phase 2: Foundational (blocking)

- [X] T004 [P] Write `tests/unit/test_import_graph.py` (TST-003-001) per [research.md R-10](research.md). Done when: it fails on a planted third-party import in a core module and passes otherwise. (REQ-ARC-001; TST-003-001)
- [X] T005 [P] Write `tests/unit/test_no_code_execution.py` (TST-003-002): `ast` scan of `pkg/` forbids `exec`, `eval`, `compile(… 'exec')`, `importlib.import_module`, `runpy`, and `__import__`, except in `pkg/cli/plugins.py` (explicit `--plugin`), which is allow-listed with a comment. Done when: it passes and flags a planted `exec`. (REQ-SEC-001; TST-003-002)
- [X] T006 [P] Write `tests/unit/test_no_version_literals.py` (TST-003-003): regex scan for `\b1[0-9]\.0\b` and comparisons with integer majors outside `pkg/knowledge/`, `pkg/rules/shared/legacy_rules.py`, and tests. Done when: it passes. (REQ-ARC-003; TST-003-003)
- [X] T007 Implement `pkg/core/contracts/*` (dataclasses and Protocols for every entity in [CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md); `CONTRACT_VERSION = 1`). Done when: TST-003-004 passes. (REQ-ARC-002; REQ-TRF-001)
- [X] T008 [P] Write `tests/unit/test_contracts.py` (TST-003-004): constructing each data contract with required fields; `Edit` without `rejection_reason` in `REJECTED` raises; `ValidationResult` with a non-`PASS` outcome and no `reason` raises, and `coverage` accepts only `full`/`partial`/`None`; `Finding.id` stable for equal inputs. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TRF-001; TST-003-004)
- [X] T009 [P] Write `tests/unit/test_registry.py` (TST-003-005): duplicate ID → `DuplicateRegistrationError`; `all()` sorted; mismatched `contract_version` → `PluginContractError` naming both versions. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-006; TST-003-005)
- [X] T010 Implement `pkg/core/contracts/plugins.py` `Registry[T]` and the seven registries per [contracts/registries-and-plugins.md](contracts/registries-and-plugins.md). Done when: TST-003-005 passes. (REQ-ARC-002; REQ-ARC-006)
- [X] T011 Port the P0 helpers into `pkg/utils/{atomic,hashing,paths,redact}.py` (atomic write, SHA-256, `is_within`, secret redaction) with `tests/unit/test_utils.py` (TST-003-006). Done when: the tests pass, including atomic-write fault injection. (REQ-SAF-007; TST-003-006)

**Checkpoint**: Contracts and registries ready.

---

## Phase 3: User Story 2 - Any researched path is planned as explicit steps (P1)

- [X] T012 [P] [US2] Write `tests/unit/test_version_registry.py` (TST-003-007): loads `versions.json`; rejects duplicate IDs, unknown status enums, and missing keys; versions totally ordered. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-001; TST-003-007)
- [X] T013 [US2] Author `pkg/knowledge/versions.json` (12.0–19.0) per [research.md R-04](research.md): `python_min`/`python_max` from EV-125 (`null` where unknown), `online_releases` from EV-001, `research_status` from the planning matrix, `support_status = UNSUPPORTED` for all. Done when: TST-003-007 passes. (REQ-VER-001)
- [X] T014 [US2] Implement `pkg/versions/registry/loader.py` with a stdlib schema check. Done when: TST-003-007 passes. (REQ-VER-001)
- [X] T015 [P] [US2] Write `tests/unit/test_version_graph.py` (TST-003-008: all 28 ordered pairs among 12.0–19.0 give consecutive steps; s ≥ t raises; unknown version raises) and `test_synthetic_version.py` (TST-003-009: a temp registry adding `20.0` as data plans 19.0→20.0 with no code change). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-002; REQ-VER-005; TST-003-008; TST-003-009)
- [X] T016 [US2] Implement `pkg/versions/graph/graph.py` (`steps(source, target)`, `unresearched(steps)`). Done when: TST-003-008/009 pass. (REQ-VER-002; REQ-VER-003)
- [X] T017 [P] [US2] Write `tests/unit/test_dependency_graph.py` (TST-003-010): topological order, ties broken by name, a cycle reported with its members, external deps ignored. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-DEP-002; TST-003-010)
- [X] T018 [US2] Implement `pkg/dependencies/graph.py`. Done when: TST-003-010 passes. (REQ-DEP-002)
- [X] T019 [P] [US2] Write `tests/unit/test_discovery.py` (TST-003-011): finds modules in `--module/--modules/--addons-path`; reads `declared_version` via `ast.literal_eval`; a malformed manifest becomes a finding; a mismatch with the requested source becomes a finding; no-manifest directories are skipped with INFO; symlinks outside the root are not followed; nothing is written. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-006; REQ-MAN-001; TST-003-011)
- [X] T020 [US2] Implement `pkg/discovery/{modules,manifest,ignore}.py` (`.gitignore` support: `!` negation, `/` anchors, trailing `/`; fixes F-WALK-1). Done when: TST-003-011 passes. (REQ-VER-006; REQ-MAN-001)
- [X] T021 [P] [US2] Write `tests/unit/test_planner.py` (TST-003-012): an unresearched step → plan `BLOCKED` naming the step; `--allow-unverified` → plan runs and every module is capped at `NEEDS_REVIEW`; a source below the registry minimum → `BLOCKED` with the supported range. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-003; TST-003-012)
- [X] T022 [US2] Implement `pkg/core/orchestrator/run.py::build_plan`. Done when: TST-003-012 passes. (REQ-VER-003; REQ-DEP-002)
- [X] T023 [US2] Write `docs/guides/ADDING_A_VERSION.md` (data → rules → fixtures → matrix) and `tests/integration/test_adding_version_procedure.py` (TST-003-013), which follows the guide with a synthetic version in a temp knowledge dir and runs `plan`. Done when: it passes without core edits. (REQ-VER-005; TST-003-013)

**Checkpoint**: Planning works for all registry pairs.

---

## Phase 4: User Story 3 - Recoverable runs (P1)

- [X] T024 [P] [US3] Write `tests/unit/test_runlog.py` (TST-003-014): append fsyncs each entry; the reader accepts `odooflux.runlog/0` (P0) and `/1`; a truncated last line is ignored with a warning. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-006; TST-003-014)
- [X] T025 [US3] Implement `pkg/core/recovery/runlog.py`. Done when: TST-003-014 passes. (REQ-SAF-006)
- [X] T026 [P] [US3] Write `tests/integration/test_workspace_isolation.py` (TST-003-015): the source digest is unchanged until promotion, by sampling between steps via a hook. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-007; TST-003-015)
- [X] T027 [US3] Implement `pkg/core/jobs/{state_dir,workspace,promote}.py` per [contracts/recovery.md](contracts/recovery.md) (state dir refused inside scanned paths; verified backup; per-file atomic replace; run-log entries). Done when: TST-003-015 passes. (REQ-SAF-006; REQ-SAF-007)
- [X] T028 [P] [US3] Write `tests/integration/test_promote_failure.py` (TST-003-031): fault injected on file k restores files 1..k-1 and marks the module `FAILED`. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-007; TST-003-031)
- [X] T029 [P] [US3] Write `tests/integration/test_rollback.py`: `test_rollback_restores_bytes` (TST-003-032) on every golden fixture, and `test_rollback_conflict_skipped` (TST-003-033). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-008; TST-003-032; TST-003-033)
- [X] T030 [US3] Implement `pkg/core/recovery/rollback.py` and `odooflux rollback`. Done when: TST-003-031/032/033 pass (SC-003). (REQ-SAF-008)
- [X] T031 [P] [US3] Write `tests/integration/test_resume.py`: `test_resume_equals_uninterrupted` (TST-003-034), interrupting at each module boundary of a 3-module fixture, and `test_resume_refused_on_changed_source` (TST-003-035). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-009; TST-003-034; TST-003-035)
- [X] T032 [US3] Implement `pkg/core/recovery/{checkpoint,resume}.py` and `odooflux resume` per [data-model.md](data-model.md#modulerunstatestatus-transitions). Done when: TST-003-034/035 pass (SC-004). (REQ-SAF-009)
- [X] T033 [P] [US3] Write `tests/integration/test_analyze_state_only.py` (TST-003-030): analyze and dry-run create only `runs/<id>/{state.json,log}` and touch no source. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-007; REQ-SAF-001; TST-003-030)

---

## Phase 5: Engine and validation layers (supports US1/US5)

- [X] T034 [P] Write `tests/unit/test_engine_apply.py` (TST-003-016): non-overlapping edits apply right-to-left; overlap resolved by precedence (severity, then `depends_on`), else both rejected; `before` mismatch → `REJECTED` with reason. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-004; REQ-TRF-001; TST-003-016)
- [X] T035 Implement `pkg/core/engine/apply.py`. Done when: TST-003-016 passes. (REQ-VER-004; REQ-TRF-001)
- [X] T036 [P] Write `tests/unit/test_engine_rescan.py` (TST-003-017): only findings absent after the re-scan become `FIXED`; a finding moved by an edit is matched by rule and relocated span; uncertain matches stay `OPEN`. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TRF-005; TST-003-017)
- [X] T037 Implement `pkg/core/engine/rescan.py`. Done when: TST-003-017 passes. (REQ-TRF-005)
- [X] T038 [P] Write `tests/unit/test_syntax_validators.py` (TST-003-018): Python, XML, and manifest validators PASS on valid input and FAIL with location on invalid input; registered in `validators`. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VAL-001; TST-003-018)
- [X] T039 Implement `pkg/validation/syntax/{python,xml,manifest}.py`. Done when: TST-003-018 passes. (REQ-VAL-001)
- [X] T040 [P] Write `tests/unit/test_static_rescan_validator.py` (TST-003-019): L2 attaches post-fix findings per file to the report. Implement `pkg/validation/static/rescan.py`. Done when: it passes. (REQ-VAL-002; TST-003-019)
- [X] T041 [P] Write `tests/unit/test_step_runner_order.py` (TST-003-020): rules run in `depends_on` order within a step; steps run in graph order; each step's output is the next step's input; L1 runs after each step. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VER-004; TST-003-020)
- [X] T042 Implement `pkg/core/engine/step_runner.py`. Done when: TST-003-020 passes. (REQ-VER-004)

---

## Phase 6: User Story 5 - One report model, deterministic output (P2)

- [X] T043 [P] [US5] Write `tests/unit/test_status_decision.py` (TST-003-021): one subTest per row of the decision table in [VALIDATION_AND_TEST_STRATEGY.md](../../docs/planning/VALIDATION_AND_TEST_STRATEGY.md#result-statuses), including `UNAVAILABLE` layers capping the status. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-VAL-006; TST-003-021)
- [X] T044 [US5] Implement `pkg/core/orchestrator/status.py` (pure function). Done when: TST-003-021 passes. (REQ-VAL-006)
- [X] T045 [P] [US5] Write `tests/unit/test_report_model.py` (TST-003-022): a model built from a fixture run validates against `report.schema.json` via `schema_check.py`; status enums are enforced; required sections are present. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-REP-001; TST-003-022)
- [X] T046 [US5] Implement `pkg/reporting/model/{model.py,report.schema.json,schema_check.py,json_renderer.py}` per [contracts/result-model-v1.md](contracts/result-model-v1.md). Done when: TST-003-022 passes. (REQ-REP-001)
- [X] T047 [P] [US5] Write `tests/integration/test_determinism.py` (TST-003-023): two runs per golden fixture give identical normalised JSON (SC-005). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-005; TST-003-023)

---

## Phase 7: User Story 4 - Plugins without touching the core (P2)

- [X] T048 [P] [US4] Create `tests/contract/samples/` with one sample per registry kind (version data, rule, parser, validator, runtime fake, AI provider fake, renderer). Write `tests/contract/test_plugin_kinds.py` (TST-003-024: each is loaded via `--plugin` and its effect is visible in the report) and `test_plugin_contract_mismatch.py` (TST-003-025). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-002; REQ-ARC-006; TST-003-024; TST-003-025)
- [X] T049 [US4] Implement `pkg/cli/plugins.py` (`--plugin module:attr`, config `plugins`). Done when: TST-003-024/025 pass (SC-006). (REQ-ARC-002; REQ-ARC-006)
- [X] T050 [P] [US4] Write `tests/contract/test_plugin_exception.py` (TST-003-026): a raising rule → `RULE_ERROR` finding, the run continues, status capped at `NEEDS_REVIEW`. Implement the handling in `step_runner.py`. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-002; TST-003-026)

---

## Phase 8: User Story 1 - Same results through the new core (P1, cut-over)

- [X] T051 [P] [US1] Write `tests/unit/test_legacy_adapter.py` (TST-003-027): for every golden fixture, adapter findings equal the legacy `check_content` output (category, line, severity, message) captured from P1 expectations. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-004; REQ-TRF-001; TST-003-027)
- [X] T052 [US1] Move the legacy rule tables and fixers (as patched in P0) into `pkg/rules/shared/legacy_rules.py` and implement `legacy_adapter.py` per [research.md R-07](research.md). Whole-file legacy fixer output is converted to line-span Edits via `difflib`. Record the waivers in `docs/changes/P2_CUTOVER.md`. Done when: TST-003-027 passes. (REQ-ARC-004; REQ-TRF-001)
- [X] T053 [US1] Wrap the legacy Claude call unchanged as `pkg/ai/providers/legacy_anthropic.py`, registered in `ai_providers`, with the P0 validation gate applied. Done when: the P0 AI regression tests (TST-001-010, TST-001-030) pass via the new path. (REQ-ARC-004)
- [X] T054 [P] [US1] Write `tests/integration/test_cli_contract.py`: `test_options_and_exit_codes` (TST-003-028) per [contracts/cli.md](contracts/cli.md); `test_plan_command_writes_nothing` (TST-003-038); `test_versions_command_lists_registry` (TST-003-039). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-004; REQ-VER-002; TST-003-028; TST-003-038; TST-003-039)
- [X] T055 [US1] Implement `pkg/cli/{main.py,legacy_options.py,commands/*}`. No subcommand means `migrate` with the legacy flags; `--to-version` is validated against the registry; `--api-key` prints a deprecation warning (D-10). Done when: TST-003-028/038/039 pass. (REQ-ARC-004; REQ-ARC-003)
- [X] T056 [US1] Implement `pkg/reporting/model/{legacy_terminal.py,legacy_json.py}` reproducing legacy console and JSON output from the model. Done when: the characterisation report comparisons pass. (REQ-ARC-004; REQ-REP-001)
- [X] T057 [US1] Write `tests/integration/test_launcher_resolution.py` (TST-003-040): `python odooflux.py --help` resolves `odooflux` to `src/odooflux/__init__.py`. Then replace the root `odooflux.py` body with the launcher from [research.md R-01](research.md). Done when: TST-003-040 passes. (REQ-ARC-004; TST-003-040)
- [X] T058 [US1] Extend the P1 characterisation helper to accept differences listed in `docs/changes/P2_CUTOVER.md` (machine-readable table) with `tests/integration/test_cutover_differences.py` (TST-003-029: each listed difference is actually observed, so no stale entries). Run the full suite. Done when: unexplained failures = 0 (SC-001). (REQ-ARC-004; TST-003-029)

---

## Phase 9: Polish & Cross-Cutting

- [X] T059 [P] Implement `tests/benchmarks/{generate_repo.py,bench_analyze.py}` (TST-003-036, opt-in `ODOOFLUX_BENCH=1`) per [research.md R-09](research.md). Record wall time and peak RSS for 300 modules in `tests/benchmarks/BASELINE.md` with machine specs. Done when: the baseline is recorded (SC-007). (REQ-PRF-001; TST-003-036)
- [X] T060 [P] Write `tests/unit/test_structure.py` (TST-003-037): the top-level directories of `src/odooflux/` match [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md); unknown directories fail. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-ARC-002; TST-003-037)
- [X] T061 Update `tests/README.md` and `README.md` usage (subcommands, state dir, rollback/resume). Done when: every command in [quickstart.md](quickstart.md) is documented. (REQ-ARC-004)
- [X] T062 Run [quickstart.md](quickstart.md) and record outputs in `specs/003-core-architecture/verification.md`. Done when: SC-001…SC-007 are each evidenced. (REQ-ARC-004; REQ-SAF-008; REQ-VER-002)

---

## Deferred

- REQ-VAL-003…005 (L3–L5) → P5/P7. In P2 they report `UNAVAILABLE`.
- REQ-PRF-001 budget enforcement → P9 (baseline only here).
- Fine-grained span edits (REQ-TRF-002…004) → P4.

## Dependencies & Execution Order

- Setup → Foundational (T004–T011) → US2 (T012–T023) and US3 (T024–T033) in parallel → Engine
  (T034–T042) → US5 (T043–T047) → US4 (T048–T050) → US1 cut-over (T051–T058) → Polish.
- The cut-over (T057) must be last among implementation tasks: it changes the entry point.

## Parallel Example

```bash
Task: "T012 registry tests"  Task: "T015 graph tests"  Task: "T017 dependency graph tests"
Task: "T019 discovery tests" Task: "T024 runlog tests" Task: "T026 workspace isolation test"
```

## Counts

62 tasks; 40 tests (TST-003-001 … TST-003-040).
