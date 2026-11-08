---
description: "Task list for Safety Stabilization (P0)"
---

# Tasks: Safety Stabilization (P0)

**Input**: Design documents from `/specs/001-safety-stabilization/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Required (constitution V; REQ-TST-005). Tests are written first and must fail before
the fix.

**Organization**: Grouped by user story. Line references (`odooflux.py:NNN`) are at commit `c9914e6`.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…)`

---

## Phase 1: Setup

- [X] T001 Create `tests/__init__.py`, `tests/regression/__init__.py`, and `tests/regression/helpers.py` with `tree_digest(path)` (sorted relative path + SHA-256 list), `make_addons(tmp, fixture)`, and `run_cli(args) -> (exit_code, stdout)` using `subprocess` on `odooflux.py`. Done when: `python -m unittest discover -s tests` runs 0 tests without error. (REQ-TST-005)
- [X] T002 Copy the audit Appendix A module into `tests/golden_fixtures/p0_kbi_demo_v14/`, file for file as listed in [the audit](../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md#appendix-a--reproduction-fixture-kbi_demo-v14), plus a `README.md` naming the findings each file triggers. Done when: an analyze run on a copy reproduces 25 issues and exit 2 on the unpatched script. (REQ-SAF-010)

---

## Phase 2: Foundational (blocking)

- [X] T003 Add `--state-dir` and run-ID creation to `main()` in `odooflux.py` (`:1645`). Default to `$XDG_CACHE_HOME/odooflux` or `~/.cache/odooflux`; create `runs/<run-id>/{backup,log}`; exit 4 if the resolved state dir is inside any resolved module or addons path. Done when: TST-001-001 passes. (REQ-SAF-003; REQ-SEC-003)
- [X] T004 [P] Write test `tests/regression/test_p0_backup_atomic.py::test_state_dir_inside_scanned_path_refused` (TST-001-001). Done when: it fails before T003 and passes after. (REQ-SAF-003; TST-001-001)
- [X] T005 Add a `atomic_write_text(path, text, encoding)` helper in `odooflux.py`: temp file in the same directory, `fsync`, `copymode`, `os.replace`, temp cleanup on error. Replace every `write_text` on customer files with it (`:946`, `:1505`, `:1491` draft). Done when: TST-001-002 passes. (REQ-SAF-005)
- [X] T006 [P] Write fault-injection test `test_atomic_write_interrupted` that patches `os.replace` to raise after the temp write; the original content is unchanged and no temp file remains (TST-001-002). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-005; TST-001-002)
- [X] T007 Add a run-log writer (`RunLog.append(event, **fields)`) producing `run_log.jsonl` per [data-model.md](data-model.md). Done when: TST-001-003 passes. (REQ-SAF-006)
- [X] T008 [P] Write test `test_run_log_lists_written_files` (TST-001-003): after a fix run, the `file_written` entries equal the set of changed files, and the hashes match the disk. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-006; TST-001-003)

**Checkpoint**: State dir, atomic write, and run log are available to all stories.

---

## Phase 3: User Story 1 - Analysis never changes my modules (P1) 🎯 MVP

- [X] T009 [P] [US1] Write `tests/regression/test_p0_safety_readonly.py::test_analyze_is_read_only` and `::test_dry_run_is_read_only`, comparing `tree_digest` before and after on the P0 fixture (TST-001-004, TST-001-005). Cites F-SAFE-1. Done when: both fail on the current script (manifest copy). (REQ-SAF-001; TST-001-004; TST-001-005)
- [X] T010 [US1] In `walk_module` (`odooflux.py:1045-1058`), move the `__openerp__.py` handling under `do_fix`: rename with atomic semantics in fix mode, and only report a planned action in analyze/dry-run mode. If both manifests exist, report an F-SAFE-5 finding and do not copy. Done when: TST-001-004/005 pass and TST-001-006 passes. (REQ-SAF-001; REQ-MAN-001)
- [X] T011 [P] [US1] Write test `test_both_manifests_reported_not_copied` (TST-001-006). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-MAN-001; TST-001-006)

**Checkpoint**: Analysis is provably read-only.

---

## Phase 4: User Story 2 - Fix mode never writes a broken file (P1)

- [X] T012 [P] [US2] Write `tests/regression/test_p0_validation_gate.py::test_invalid_python_not_written`, `::test_invalid_xml_not_written`, and `::test_invalid_manifest_not_written`, monkeypatching each `apply_*_fixes` to return invalid text (TST-001-007/008/009). Cites F-VAL-1. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-002; REQ-VAL-001; TST-001-007; TST-001-008; TST-001-009)
- [X] T013 [US2] Add `_validate_output(path, text) -> Optional[str]` (Python `ast.parse`, XML `ElementTree.fromstring(text.encode())`, manifest `ast.literal_eval`) and call it in `analyze_and_fix_file` before writing. On failure: no write, an `Issue` with `status=REJECTED`, category "Fix Rejected", the message, and a run-log `edit_rejected` event. Done when: TST-001-007/008/009 pass. (REQ-SAF-002; REQ-VAL-001)
- [X] T014 [US2] Apply the same gate to AI writes in `ai_fix_all_modules` (`:1495-1506`) for all file types, and write the drafts to the state dir instead of next to the module. Done when: TST-001-010 passes. (REQ-SAF-002; REQ-SEC-003)
- [X] T015 [P] [US2] Write test `test_ai_invalid_output_not_written` with `_call_claude_api` stubbed (TST-001-010). Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-002; TST-001-010)
- [X] T016 [P] [US2] Write `tests/regression/test_p0_python_fixers.py::test_size_first_arg`, `::test_size_continuation_line`, and `::test_size_last_arg` (TST-001-011). Cites F-PY-2. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-011)
- [X] T017 [US2] Replace the `size=` regex (`odooflux.py:531`) with a tokenize-based removal of the keyword and exactly one comma (research R-06). Done when: TST-001-011 passes and output compiles. (REQ-SAF-010)
- [X] T018 [P] [US2] Write test `test_decorator_removal_keeps_indentation` covering `@api.multi` at class level, with comments between decorator and `def` (TST-001-012). Cites F-PY-1. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-012)
- [X] T019 [US2] Rewrite decorator removal (`odooflux.py:512-518`) to delete whole decorator lines, including a multi-line `@api.returns(...)` argument span, via tokenize. Done when: TST-001-012 passes. (REQ-SAF-010)
- [X] T020 [P] [US2] Write `tests/regression/test_p0_xml_fixers.py::test_states_fix_well_formed` and `::test_states_fix_skipped_when_invisible_present` (TST-001-013, TST-001-014). Cites F-XML-1, F-XML-4. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-013; TST-001-014)
- [X] T021 [US2] In `_convert_states_to_invisible` (`odooflux.py:596-643`), remove the comment injection (`:632`). Skip tags that already have `invisible=` and add a review finding instead. The "verify controlling field" note goes into the finding message. Done when: TST-001-013/014 pass. (REQ-SAF-010)
- [X] T022 [P] [US2] Write test `test_no_js_comment_in_python` (TST-001-015). Cites F-PY-6. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-015)
- [X] T023 [US2] Remove the `ajax.jsonRpc` substitution from `apply_python_fixes` (`:532-536`), and the `@odoo-module` header injection and comment substitution from `apply_js_fixes` (`:785-797`). Make the JS rules detect-only. Done when: TST-001-015 passes and JS files are byte-identical after `--fix`. (REQ-SAF-010)
- [X] T024 [US2] Run `--fix` on the P0 fixture and assert that every written `.py` compiles and every `.xml` parses (TST-001-016, `test_fixture_fix_outputs_valid`). Done when: it passes (SC-001). (REQ-SAF-002; REQ-SAF-010; TST-001-016)

**Checkpoint**: No invalid file can be written.

---

## Phase 5: User Story 3 - Backups are safe and writes are atomic (P1)

- [X] T025 [P] [US3] Write `test_backup_outside_addons_path`, `test_backup_verified`, and `test_backup_failure_blocks_module` (TST-001-017/018/019). Cites F-SAFE-2/3. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-003; REQ-SAF-004; TST-001-017; TST-001-018; TST-001-019)
- [X] T026 [US3] Rewrite `backup_module` (`odooflux.py:1193`) to copy into `<state-dir>/runs/<run-id>/backup/<module>/`, write the `BackupManifest`, and verify file count and SHA-256. Return failure instead of continuing. In `main()` (`:1740`), mark the module `BLOCKED`, log `module_blocked`, and skip all writes for it. Done when: TST-001-017/018/019 pass. (REQ-SAF-003; REQ-SAF-004)
- [X] T027 [US3] Re-scanning the addons path after a backup run lists only the original modules. Covered by TST-001-017; add an explicit assertion. Done when: SC-003 holds. (REQ-SAF-003)

---

## Phase 6: User Story 4 - Version-correct, honest fixes (P2)

- [X] T028 [P] [US4] Write `test_api_returns_target18_kept_review`, `test_api_returns_target19_removed_review`, and `test_api_one_detect_only` (TST-001-020/021/022). Cite EV-101, EV-102, F-PY-3/4. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-020; TST-001-021; TST-001-022)
- [X] T029 [US4] Make `apply_python_fixes` (`:509`) take `to_version`: remove `@api.returns` only when `to_version >= 19`, always add a review `Issue`, and never remove `@api.one`. Update the rule messages at `:92-94` with the correct versions (13.0 for one/multi, 19.0 for returns). Done when: TST-001-020/021/022 pass. (REQ-SAF-010)
- [X] T030 [P] [US4] Write `test_sudo_bool_unchanged` and `test_sudo_user_rewritten_only_from_12` (TST-001-023). Cites EV-103, F-PY-5. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-023)
- [X] T031 [US4] Restrict the sudo rewrite (`:524`) to `from_version <= 12` and non-boolean, non-keyword arguments. Done when: TST-001-023 passes. (REQ-SAF-010)
- [X] T032 [P] [US4] Write `test_attrs_detect_only` asserting the `attrs=` text is unchanged and the finding status is `NEEDS_REVIEW` with suggestion "converted in a later release" (TST-001-024). Cites F-XML-2. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-024)
- [X] T033 [US4] Remove the `_convert_attrs_to_inline` call from `apply_xml_fixes` (`:652`), set the attrs rule `auto_fixable=False`, and fix its suggestion text to Python-expression syntax. Done when: TST-001-024 passes. (REQ-SAF-010)
- [X] T034 [P] [US4] Write `tests/regression/test_p0_reporting.py::test_fixed_count_equals_rescan_delta` (TST-001-025). Cites F-REP-1. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-TRF-005; TST-001-025)
- [X] T035 [US4] Replace `_mark_auto_fixes_applied` (`:901-912`) and the AI equivalent (`:1508-1510`) with re-scan attribution (research R-04). Done when: TST-001-025 passes (SC-004). (REQ-TRF-005)
- [X] T036 [P] [US4] Write `test_manifest_version_suffix_preserved` (single and double quotes) (TST-001-026). Cites F-MAN-1. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-MAN-002; TST-001-026)
- [X] T037 [US4] Change `apply_manifest_fixes` (`:763-782`) to replace only the major prefix (`^\d+\.0` → `<to>.0`), keeping the rest. Done when: TST-001-026 passes. (REQ-MAN-002)
- [X] T038 [P] [US4] Write `test_warning_message_versions` asserting the corrected messages (TST-001-027). Cites EV-110. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SAF-010; TST-001-027)
- [X] T039 [US4] Update the Warning rule messages (`:197-210`) to "deprecated 14.0–16.0, removed in 17.0". Done when: TST-001-027 passes. (REQ-SAF-010)

---

## Phase 7: User Story 5 - Run log and exit codes (P3)

- [X] T040 [P] [US5] Write `test_fail_on_thresholds` (none/info/warning/critical) and `test_exit_codes_rejected_3_blocked_4` (TST-001-028/029). Cites F-REP-3, F-VER-4. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-REP-005; TST-001-028; TST-001-029)
- [X] T041 [US5] Add `--fail-on` (default `critical`), exit 3 when any edit was rejected in write mode, and exit 4 for tool errors and blocked modules (precedence 4 > 3 > 1 > 0) in `main()` (`:1791-1797`). Done when: TST-001-028/029 pass. (REQ-REP-005)
- [X] T042 [P] [US5] Write `test_no_tool_artifacts_in_module` asserting no `ai_response_debug.txt`, `.ai_draft`, or log file inside the module after AI and fix runs with a stubbed provider (TST-001-030). Cites F-AI-6. Done when: the test is collected by `python -m unittest discover -s tests`, its assertions match this description, and it fails before the implementing task is done (red phase). (REQ-SEC-003; TST-001-030)
- [X] T043 [US5] Move `ai_response_debug.txt` (`:1454`) and `.ai_draft` outputs to `<state-dir>/runs/<run-id>/log/`. Done when: TST-001-030 passes. (REQ-SEC-003)

---

## Phase 8: Polish & Cross-Cutting

- [X] T044 [P] Write `docs/changes/P0_CHANGE_RECORD.md` listing every behaviour change: exit codes, `--state-dir`, backup location, detect-only rules, attrs, `@api.returns`/`@api.one`/`sudo`, and the manifest suffix. Done when: each FR-001…FR-013 maps to an entry. (REQ-TST-005; REQ-SAF-010)
- [X] T045 Update `--help` text and the module docstring (`odooflux.py:1-10`, `:1645-1655`) to the real script name and new options. Done when: `python odooflux.py --help` shows `--state-dir` and `--fail-on`. (REQ-REP-005)
- [X] T046 Run [quickstart.md](quickstart.md) end to end and paste the outputs into the verification evidence file `specs/001-safety-stabilization/verification.md`. Done when: SC-001…SC-005 are each shown with command output. (REQ-SAF-001; REQ-SAF-002; REQ-SAF-003)

---

## Deferred (assigned elsewhere)

- REQ-SAF-006 rollback consumer → P2 (003). REQ-SAF-007/008/009 → P2.
- REQ-MAN-001 full `ast.literal_eval` parsing for detection → P2. P0 covers the write-mode-only
  rename and validation.

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T008) → US1…US5. US1–US3 are P1, so do them first.
  US4 depends on T013 (gate). US5 depends on T003/T007.
- Within each story, the test task precedes its implementation task.
- T044–T046 come last.

## Parallel Example

```bash
# After Foundational, write all US2 tests together:
Task: "T012 validation gate tests"   Task: "T016 size= tests"
Task: "T018 decorator tests"         Task: "T020 states= tests"   Task: "T022 no-JS-in-Python test"
```

## Implementation Strategy

MVP = US1 and US2 (read-only analysis plus the validation gate), which removes the
data-destroying failure modes. Then US3 (backups and atomicity), US4 (correct, honest fixes),
and US5.

## Counts

46 tasks; 30 tests (TST-001-001 … TST-001-030).
