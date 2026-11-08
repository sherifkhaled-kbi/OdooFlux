# Requirements Traceability Matrix

Generated on 2026-11-06 from the `REQ-…`, `FR-…`, task, and `TST-…` tags in
[PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md), `specs/*/spec.md`, and `specs/*/tasks.md`
(planning helper; not hand-edited). Task IDs use `<feature>:T###`; tests use `TST-<feature>-NNN`.
Long lists are truncated with a `(+N)` count. The full set is recoverable with
`grep -n "REQ-XXX-NNN" specs/*/tasks.md`.

Acceptance criteria and official-evidence requirements per requirement are in
[PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md) (columns *Acceptance criterion* and *Verify*;
`EV` = evidence audit). Rule-level evidence obligations are in
[MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md) and
[OFFICIAL_SOURCES_STRATEGY.md](OFFICIAL_SOURCES_STRATEGY.md).

## Summary

| Metric | Value |
|---|---|
| Product requirements | 92 |
| Requirements with ≥1 spec FR | 92 |
| Requirements with ≥1 task | 92 |
| Requirements with ≥1 test ID | 92 |
| Tasks (features 001–010) | 366 |
| Tasks without a requirement reference | 0 |
| Unique test IDs | 196 |
| References to undefined requirement IDs | 0 |
| KAP requirements (feature 011, rows REQ-KAP-001..047) | 47 (evidence: test files citing the requirement id; REQ-KAP-043 by verification record) |
| Missing mappings | none |

## Matrix

| REQ | OBJ | Phase | Spec FRs | Tasks | Tests | Verify | Gap |
|---|---|---|---|---|---|---|---|
| REQ-SAF-001 | OBJ-008 | P0 | 001:FR-001 | 001:T009, 001:T010, 001:T046, 002:T022, 003:T033 | TST-001-004, TST-001-005, TST-001-006, TST-002-008 (+1) | IT, GT | OK |
| REQ-SAF-002 | OBJ-008 | P0 | 001:FR-002 | 001:T012, 001:T013, 001:T014, 001:T015, 001:T024, 001:T046 | TST-001-007, TST-001-008, TST-001-009, TST-001-010 (+1) | UT, FI | OK |
| REQ-SAF-003 | OBJ-008 | P0 | 001:FR-003 | 001:T003, 001:T004, 001:T025, 001:T026, 001:T027, 001:T046 | TST-001-001, TST-001-017, TST-001-018, TST-001-019 | IT, FI | OK |
| REQ-SAF-004 | OBJ-008 | P0 | 001:FR-004 | 001:T025, 001:T026 | TST-001-017, TST-001-018, TST-001-019 | FI | OK |
| REQ-SAF-005 | OBJ-008 | P0 | 001:FR-005, 010:FR-009 | 001:T005, 001:T006, 010:T020, 010:T021 | TST-001-002, TST-010-010 | FI | OK |
| REQ-SAF-006 | OBJ-008 | P0 (log), P2 (rollback) | 001:FR-006, 003:FR-012 | 001:T007, 001:T008, 003:T024, 003:T025, 003:T027 | TST-001-003, TST-003-014, TST-003-015 | IT | OK |
| REQ-SAF-007 | OBJ-008 | P2 | 003:FR-012 | 003:T011, 003:T026, 003:T027, 003:T028, 003:T033 | TST-003-006, TST-003-015, TST-003-030, TST-003-031 | IT, FI | OK |
| REQ-SAF-008 | OBJ-008 | P2 | 003:FR-013, 010:FR-009 | 003:T029, 003:T030, 003:T062, 010:T020 | TST-003-031, TST-003-032, TST-003-033, TST-010-010 | IT | OK |
| REQ-SAF-009 | OBJ-008 | P2 | 003:FR-014, 010:FR-009 | 003:T031, 003:T032, 010:T020 | TST-003-034, TST-003-035, TST-010-010 | IT, FI | OK |
| REQ-SAF-010 | OBJ-008 | P0 | 001:FR-007, 001:FR-012, 001:FR-013 | 001:T002, 001:T016, 001:T017, 001:T018, 001:T019, 001:T020 (+13) | TST-001-011, TST-001-012, TST-001-013, TST-001-014 (+8) | UT, GT | OK |
| REQ-TST-001 | OBJ-009 | P1 | 002:FR-001, 002:FR-002, 002:FR-010, 002:FR-011 | 002:T001, 002:T003, 002:T006, 002:T007, 002:T008, 002:T009 (+2) | TST-002-001, TST-002-004 | IT | OK |
| REQ-TST-002 | OBJ-009 | P1 (harness), P5 (rules) | 002:FR-007, 006:FR-002, 010:FR-001 | 002:T026, 006:T002, 006:T059, 010:T003 | TST-002-011, TST-006-001, TST-010-001 | UT | OK |
| REQ-TST-003 | OBJ-009 | P1, P5 | 002:FR-003, 002:FR-004, 006:FR-014 | 002:T002, 002:T010, 002:T011, 002:T012, 002:T013, 002:T014 (+10) | TST-002-005, TST-002-008, TST-006-006, TST-006-015 (+1) | GT | OK |
| REQ-TST-004 | OBJ-009 | P1 | 002:FR-005, 002:FR-006 | 002:T004, 002:T006, 002:T018, 002:T019, 002:T020, 002:T021 (+1) | TST-002-001, TST-002-002, TST-002-006, TST-002-007 | GT | OK |
| REQ-TST-005 | OBJ-009 | P0–P9 | 001:FR-012, 002:FR-008, 002:FR-010, 010:FR-001 (+1) | 001:T001, 001:T044, 002:T007, 002:T023, 002:T024, 002:T028 (+10) | TST-002-009, TST-005-007, TST-005-011, TST-007-017 (+4) | RV | OK |
| REQ-TST-006 | OBJ-009 | P1 | 002:FR-002, 002:FR-009 | 002:T005, 002:T006, 002:T009, 002:T025, 002:T028 | TST-002-001, TST-002-003, TST-002-004, TST-002-010 | IT | OK |
| REQ-ARC-001 | OBJ-007 | P2 | 003:FR-001, 003:FR-022, 007:FR-002 | 003:T001, 003:T002, 003:T004, 004:T006, 005:T028, 007:T001 | TST-003-001, TST-004-001, TST-005-013 | UT | OK |
| REQ-ARC-002 | OBJ-007 | P2 | 003:FR-002, 008:FR-012 | 003:T002, 003:T007, 003:T010, 003:T048, 003:T049, 003:T050 (+1) | TST-003-004, TST-003-005, TST-003-024, TST-003-025 (+2) | UT, RV | OK |
| REQ-ARC-003 | OBJ-007 | P2 | 003:FR-003, 004:FR-005 | 003:T006, 003:T055, 004:T012, 004:T014, 010:T022 | TST-003-003, TST-003-028, TST-004-005, TST-010-011 | UT | OK |
| REQ-ARC-004 | OBJ-007 | P2 | 003:FR-004, 003:FR-021 | 003:T003, 003:T051, 003:T052, 003:T053, 003:T054, 003:T055 (+6) | TST-001-010, TST-001-030, TST-003-027, TST-003-028 (+5) | GT | OK |
| REQ-ARC-005 | OBJ-007 | P2 | 003:FR-005 | 003:T047 | TST-003-023 | IT | OK |
| REQ-ARC-006 | OBJ-007 | P2 | 003:FR-002 | 003:T009, 003:T010, 003:T048, 003:T049, 009:T006 | TST-003-005, TST-003-024, TST-003-025 | UT | OK |
| REQ-VER-001 | OBJ-001 | P2 (schema), P3 (data) | 003:FR-006, 004:FR-005, 004:FR-006 | 003:T012, 003:T013, 003:T014, 004:T012, 004:T013, 004:T014 (+1) | TST-003-007, TST-004-005 | UT | OK |
| REQ-VER-002 | OBJ-001 | P2 | 003:FR-007 | 003:T015, 003:T016, 003:T054, 003:T062 | TST-003-008, TST-003-009, TST-003-028, TST-003-038 (+1) | UT | OK |
| REQ-VER-003 | OBJ-001 | P2 | 003:FR-007, 003:FR-008, 010:FR-010 | 003:T016, 003:T021, 003:T022, 010:T006, 010:T007 | TST-003-008, TST-003-012, TST-010-003 | UT, IT | OK |
| REQ-VER-004 | OBJ-001 | P2 | 003:FR-009 | 003:T034, 003:T035, 003:T041, 003:T042 | TST-003-016, TST-003-020 | UT | OK |
| REQ-VER-005 | OBJ-001 | P2, P5 | 003:FR-010, 004:FR-010, 006:FR-016 | 003:T015, 003:T023, 004:T002, 006:T056 | TST-003-008, TST-003-009, TST-003-013, TST-006-034 | IT, RV | OK |
| REQ-VER-006 | OBJ-001 | P2 | 003:FR-011 | 003:T019, 003:T020 | TST-003-011 | UT | OK |
| REQ-EVD-001 | OBJ-003, OBJ-004 | P3 | 004:FR-003, 006:FR-001 | 004:T008, 004:T010, 004:T017, 006:T008, 006:T010, 006:T024 (+1) | TST-004-003, TST-004-006, TST-006-005 | UT | OK |
| REQ-EVD-002 | OBJ-003, OBJ-004 | P3 | 004:FR-001, 004:FR-006 | 004:T001, 004:T003, 004:T005, 004:T006, 004:T007, 004:T009 (+6) | TST-004-001, TST-004-002, TST-004-004, TST-004-006 (+2) | UT | OK |
| REQ-EVD-003 | OBJ-003, OBJ-004 | P3, P5 | 004:FR-004, 004:FR-009, 006:FR-015, 007:FR-013 | 004:T008, 004:T010, 004:T020, 006:T023, 006:T055 | TST-004-003, TST-004-008, TST-006-033 | UT | OK |
| REQ-EVD-004 | OBJ-003, OBJ-004 | P3 | 004:FR-002 | 004:T004, 004:T007, 004:T009, 008:T001, 008:T002 | TST-004-002 | UT | OK |
| REQ-EVD-005 | OBJ-003, OBJ-004 | P3 | 004:FR-007, 004:FR-010 | 004:T002, 004:T019, 004:T020, 004:T026 | TST-004-008 | IT, RV | OK |
| REQ-EVD-006 | OBJ-003, OBJ-004 | P3 | 004:FR-008, 004:FR-009, 010:FR-010 | 004:T018, 004:T021, 004:T022, 004:T023, 004:T026, 006:T025 (+4) | TST-004-009, TST-004-010, TST-008-006, TST-010-003 | UT | OK |
| REQ-TRF-001 | OBJ-002, OBJ-008 | P2 (contract), P4 | 003:FR-009, 003:FR-021, 005:FR-001, 005:FR-003 | 003:T007, 003:T008, 003:T034, 003:T035, 003:T051, 003:T052 (+4) | TST-003-004, TST-003-016, TST-003-027, TST-005-002 | UT | OK |
| REQ-TRF-002 | OBJ-002, OBJ-008 | P4 | 005:FR-002, 005:FR-003 | 005:T005, 005:T007 | TST-005-002 | UT | OK |
| REQ-TRF-003 | OBJ-002, OBJ-008 | P4, P5 | 005:FR-005, 005:FR-007 | 005:T006, 005:T008, 005:T013, 005:T014, 005:T019, 005:T031 (+1) | TST-005-003, TST-005-006, TST-005-009, TST-006-003 | GT | OK |
| REQ-TRF-004 | OBJ-002, OBJ-008 | P4 | 005:FR-004 | 005:T003, 005:T004, 005:T005, 005:T007, 005:T009, 005:T031 | TST-005-001, TST-005-002, TST-005-004 | GT | OK |
| REQ-TRF-005 | OBJ-002, OBJ-008 | P0 (re-scan), P2 | 001:FR-008, 003:FR-016 | 001:T034, 001:T035, 003:T036, 003:T037, 007:T017 | TST-001-025, TST-003-017, TST-007-010 | IT | OK |
| REQ-PY-001 | OBJ-002 | P4 | 005:FR-006, 005:FR-007 | 005:T010, 005:T011, 005:T012, 005:T013, 005:T014, 005:T015 (+1) | TST-005-005, TST-005-006, TST-005-007, TST-005-015 | UT | OK |
| REQ-PY-002 | OBJ-002 | P5 | 006:FR-001, 006:FR-003, 006:FR-015 | 006:T001, 006:T004, 006:T005, 006:T012, 006:T013, 006:T014 (+10) | TST-006-003, TST-006-008, TST-006-010, TST-006-011 (+6) | UT, EV | OK |
| REQ-PY-003 | OBJ-002 | P5 | 006:FR-004 | 006:T002, 006:T008, 006:T022, 006:T029, 006:T032, 006:T033 (+4) | TST-006-001, TST-006-005, TST-006-009, TST-006-012 (+5) | UT, GT | OK |
| REQ-PY-004 | OBJ-002 | P4 | 005:FR-008 | 005:T010, 005:T012 | TST-005-005 | UT | OK |
| REQ-XML-001 | OBJ-002 | P4 | 005:FR-009 | 005:T016, 005:T017, 005:T018, 005:T019, 005:T030 | TST-005-008, TST-005-009, TST-005-015 | UT | OK |
| REQ-XML-002 | OBJ-002 | P4, P5 | 005:FR-010, 006:FR-005 | 005:T020, 005:T021, 005:T022, 005:T023, 006:T010, 006:T037 | TST-005-010, TST-005-011, TST-006-017 | UT, GT | OK |
| REQ-XML-003 | OBJ-002 | P5 | 006:FR-005 | 006:T006, 006:T007, 006:T011, 006:T015, 006:T018, 006:T026 (+4) | TST-006-004, TST-006-007, TST-006-009, TST-006-012 (+1) | UT, EV | OK |
| REQ-XML-004 | OBJ-002 | P0 (well-formed), P7 (RNG) | 008:FR-010 | 008:T024, 008:T026 | TST-008-012 | UT, IT | OK |
| REQ-XML-005 | OBJ-002 | P5 | 006:FR-006 | 006:T006, 006:T007, 006:T017, 006:T042 | TST-006-004, TST-006-022 | UT, EV | OK |
| REQ-JS-001 | OBJ-002 | P4 | 005:FR-011 | 005:T002, 005:T024, 005:T025, 005:T026, 005:T027, 005:T028 (+1) | TST-005-012, TST-005-013, TST-005-014 | UT | OK |
| REQ-JS-002 | OBJ-002 | P5 | 006:FR-007 | 006:T019, 006:T052, 006:T053 | TST-006-030, TST-006-031 | UT, EV | OK |
| REQ-JS-003 | OBJ-002 | P5 | 006:FR-008 | 006:T016, 006:T054 | TST-006-032 | UT, GT | OK |
| REQ-JS-004 | OBJ-002 | P4 | 005:FR-012 | 005:T024, 005:T027, 005:T029 | TST-005-013, TST-005-014 | UT | OK |
| REQ-MAN-001 | OBJ-002 | P0 (no write), P2 | 001:FR-001, 003:FR-011 | 001:T010, 001:T011, 003:T019, 003:T020 | TST-001-004, TST-001-006, TST-003-011 | UT, IT | OK |
| REQ-MAN-002 | OBJ-002 | P0 | 001:FR-009 | 001:T036, 001:T037, 006:T045 | TST-001-026, TST-006-025 | UT | OK |
| REQ-MAN-003 | OBJ-002 | P5 | 006:FR-009 | 006:T045 | TST-006-025 | UT | OK |
| REQ-DEP-001 | OBJ-002 | P5 | 006:FR-010 | 006:T003, 006:T046, 006:T047 | TST-006-002, TST-006-026 | UT, EV | OK |
| REQ-DEP-002 | OBJ-002 | P2 | 003:FR-018 | 003:T017, 003:T018, 003:T022 | TST-003-010, TST-003-012 | UT | OK |
| REQ-DEP-003 | OBJ-002 | P5, P7 | 006:FR-011, 008:FR-003 | 006:T048, 008:T023, 008:T025 | TST-006-027, TST-008-011 | UT | OK |
| REQ-ACL-001 | OBJ-002 | P5 | 006:FR-012 | 006:T020, 006:T034, 006:T049 | TST-006-014, TST-006-028 | UT | OK |
| REQ-ACL-002 | OBJ-002 | P7 | 008:FR-006, 008:FR-007 | 008:T013, 008:T015, 008:T016 | TST-008-005, TST-008-006 | RT | OK |
| REQ-BIZ-001 | OBJ-002, OBJ-009 | P5 | 006:FR-013 | 006:T050, 006:T051 | TST-006-029 | UT | OK |
| REQ-BIZ-002 | OBJ-002, OBJ-009 | P7 | 008:FR-008 | 008:T004, 008:T005, 008:T020, 008:T021, 008:T022 | TST-008-009, TST-008-010 | RT | OK |
| REQ-BIZ-003 | OBJ-002, OBJ-009 | P7, P8 | 008:FR-001, 008:FR-009, 009:FR-007 | 008:T010, 008:T011, 008:T022, 009:T008 | TST-008-003, TST-008-010, TST-009-004 | IT | OK |
| REQ-VAL-001 | OBJ-009 | P0, P2 | 001:FR-002, 003:FR-015 | 001:T012, 001:T013, 003:T038, 003:T039 | TST-001-007, TST-001-008, TST-001-009, TST-003-018 | UT | OK |
| REQ-VAL-002 | OBJ-009 | P2 | 003:FR-015 | 003:T040 | TST-003-019 | IT | OK |
| REQ-VAL-003 | OBJ-009 | P5, P7 | 006:FR-011, 008:FR-003 | 006:T048, 008:T023, 008:T025 | TST-006-027, TST-008-011 | UT | OK |
| REQ-VAL-004 | OBJ-009 | P7 | 008:FR-004, 008:FR-006, 008:FR-012 | 008:T001, 008:T003, 008:T005, 008:T013, 008:T014, 008:T015 (+5) | TST-008-004, TST-008-005, TST-008-006, TST-008-008 | RT | OK |
| REQ-VAL-005 | OBJ-009 | P7 | 008:FR-008 | 008:T002, 008:T004, 008:T020, 008:T021 | TST-008-009 | RT | OK |
| REQ-VAL-006 | OBJ-009 | P2 (model), P7 | 003:FR-017, 008:FR-001, 008:FR-002 | 003:T043, 003:T044, 008:T006, 008:T007, 008:T008, 008:T009 (+4) | TST-003-021, TST-008-001, TST-008-002, TST-008-003 | UT | OK |
| REQ-AI-001 | OBJ-005 | P6 | 007:FR-001, 007:FR-002 | 007:T001, 007:T003, 007:T004, 007:T005, 007:T006, 007:T007 (+7) | TST-007-001, TST-007-002, TST-007-003, TST-007-004 (+1) | UT | OK |
| REQ-AI-002 | OBJ-005 | P6 | 007:FR-003, 007:FR-013 | 007:T010, 007:T012 | TST-007-005 | UT | OK |
| REQ-AI-003 | OBJ-005 | P6 | 007:FR-005, 007:FR-006 | 007:T002, 007:T014, 007:T015, 007:T017, 007:T019, 007:T033 | TST-007-007, TST-007-008, TST-007-010, TST-007-017 | UT | OK |
| REQ-AI-004 | OBJ-005 | P6 | 007:FR-004 | 007:T013, 007:T018 | TST-007-006, TST-007-009 | UT | OK |
| REQ-AI-005 | OBJ-005 | P6 | 007:FR-005, 007:FR-007, 007:FR-012 | 007:T014, 007:T020, 007:T021, 007:T025, 007:T032 | TST-007-007, TST-007-011, TST-007-016 | UT | OK |
| REQ-AI-006 | OBJ-005 | P6 | 007:FR-008 | 007:T005, 007:T022, 007:T026, 007:T030, 007:T031, 007:T032 | TST-007-001, TST-007-012, TST-007-015, TST-007-016 | UT | OK |
| REQ-AI-007 | OBJ-005 | P6 | 007:FR-009 | 007:T023, 007:T027 | TST-007-013 | IT | OK |
| REQ-AI-008 | OBJ-005 | P6, P9 | 007:FR-010, 010:FR-008 | 007:T024, 007:T028, 010:T016, 010:T017, 010:T019 | TST-007-014, TST-010-008, TST-010-009 | UT | OK |
| REQ-REP-001 | OBJ-006 | P2 (schema), P8 | 003:FR-017, 009:FR-001, 009:FR-002 | 003:T045, 003:T046, 003:T056, 009:T001, 009:T003, 009:T004 (+6) | TST-003-022, TST-009-001, TST-009-002, TST-009-008 (+1) | UT | OK |
| REQ-REP-002 | OBJ-006 | P8 | 009:FR-003 | 009:T007, 009:T009, 009:T010, 009:T011, 009:T025 | TST-009-003, TST-009-005 | UT | OK |
| REQ-REP-003 | OBJ-006 | P8 | 009:FR-004, 009:FR-008 | 009:T020, 009:T021, 009:T022 | TST-009-010, TST-009-011 | UT | OK |
| REQ-REP-004 | OBJ-006 | P8 | 009:FR-005 | 009:T002, 009:T012, 009:T015, 009:T018, 009:T019 | TST-009-006, TST-009-009 | UT | OK |
| REQ-REP-005 | OBJ-006 | P0 (basic), P8 | 001:FR-010, 009:FR-006 | 001:T040, 001:T041, 001:T045, 009:T013, 009:T016, 009:T024 | TST-001-028, TST-001-029, TST-009-007, TST-009-013 | UT | OK |
| REQ-REP-006 | OBJ-006 | P8 | 009:FR-007 | 009:T001, 009:T004, 009:T008, 009:T010, 009:T020, 009:T025 | TST-009-002, TST-009-003, TST-009-004, TST-009-010 | GT | OK |
| REQ-SEC-001 | OBJ-008 | P2, P7 | 003:FR-019, 008:FR-005, 008:FR-011 | 003:T005, 008:T012, 008:T014, 008:T027 | TST-003-002, TST-008-004, TST-008-013 | UT, RV | OK |
| REQ-SEC-002 | OBJ-008 | P7 | 008:FR-005 | 008:T012, 008:T014, 008:T017 | TST-008-004, TST-008-007 | RT, FI | OK |
| REQ-SEC-003 | OBJ-008 | P0, P6 | 001:FR-011, 007:FR-001, 007:FR-010, 009:FR-009 | 001:T003, 001:T014, 001:T042, 001:T043, 007:T009, 007:T024 (+2) | TST-001-001, TST-001-010, TST-001-030, TST-007-004 (+3) | IT | OK |
| REQ-SEC-004 | OBJ-008 | P6 | 007:FR-011, 009:FR-008 | 007:T016, 007:T018, 009:T009, 009:T021 | TST-007-006, TST-007-009, TST-009-005, TST-009-011 | UT | OK |
| REQ-SEC-005 | OBJ-008 | P9 | 010:FR-007 | 010:T015, 010:T016, 010:T018, 010:T024 | TST-010-007, TST-010-008 | IT | OK |
| REQ-PRF-001 | OBJ-007 | P2 (baseline), P9 | 003:FR-020, 010:FR-003 | 003:T059, 010:T001, 010:T002, 010:T011, 010:T014, 010:T024 | TST-003-036, TST-010-006 | BM | OK |
| REQ-PRF-002 | OBJ-007 | P9 | 010:FR-004 | 010:T010, 010:T013 | TST-010-005 | IT | OK |
| REQ-PRF-003 | OBJ-007 | P9 | 010:FR-005 | 010:T009, 010:T012 | TST-010-004 | IT | OK |
| REQ-PRF-004 | OBJ-007 | P9 | 010:FR-006 | 010:T002, 010:T011, 010:T014 | TST-010-006 | BM | OK |
| REQ-KAP-001 | OBJ-KAP | KAP | 011:REQ-KAP-001 | 011:T015, 011:T016, 011:T035, 011:T039, 011:T040, 011:T083 (+1) | test_adapter_git, test_cli_source, test_cli_wiring, test_fetch_offline (+3) | UT, IT | OK |
| REQ-KAP-002 | OBJ-KAP | KAP | 011:REQ-KAP-002 | 011:T060, 011:T079 | test_ai_proposer, test_reader_ai_log | UT | Live provider runs never executed (offline FakeProvider only); D-08 grant, denial and kill-switch tests pass |
| REQ-KAP-003 | OBJ-KAP | KAP | 011:REQ-KAP-003 | 011:T084 | test_kap_import_graph | UT | OK |
| REQ-KAP-004 | OBJ-KAP | KAP | 011:REQ-KAP-004 | 011:T047, 011:T051, 011:T084 | test_domain_js, test_extract_driver, test_kap_import_graph | UT | OK |
| REQ-KAP-005 | OBJ-KAP | KAP | 011:REQ-KAP-005 | 011:T001, 011:T015, 011:T016, 011:T020, 011:T022, 011:T055 (+4) | test_authoring_checks, test_builtin_digest, test_builtin_golden, test_cli_wiring (+6) | UT | OK |
| REQ-KAP-006 | OBJ-KAP | KAP | 011:REQ-KAP-006 | 011:T031, 011:T032, 011:T040 | test_cli_source, test_p4_schemas, test_sources | UT | OK |
| REQ-KAP-007 | OBJ-KAP | KAP | 011:REQ-KAP-007 | 011:T035, 011:T037, 011:T038 | test_adapter_docs, test_adapter_enterprise_supp, test_adapter_git, test_git_local_malicious_repo (+1) | UT | OK |
| REQ-KAP-008 | OBJ-KAP | KAP | 011:REQ-KAP-008 | 011:T032, 011:T037, 011:T057 | test_adapter_enterprise_supp, test_evidence_builder, test_sources | UT | OK |
| REQ-KAP-009 | OBJ-KAP | KAP | 011:REQ-KAP-009 | 011:T032, 011:T035, 011:T039, 011:T040, 011:T071, 011:T085 | test_adapter_git, test_cli_source, test_fetch_offline, test_live_sources (+1) | UT, IT | Live clone/fetch tests are opt-in and were never run; offline counterparts pass |
| REQ-KAP-010 | OBJ-KAP | KAP | 011:REQ-KAP-010 | 011:T031, 011:T033, 011:T034, 011:T036 | test_adapter_dir_pack, test_blobstore, test_p4_schemas, test_snapshot | UT | OK |
| REQ-KAP-011 | OBJ-KAP | KAP | 011:REQ-KAP-011 | 011:T030, 011:T038, 011:T045, 011:T047, 011:T048, 011:T049 (+3) | test_adapter_docs, test_classify, test_domain_js, test_domain_manifest_assets_data (+7) | UT | OK |
| REQ-KAP-012 | OBJ-KAP | KAP | 011:REQ-KAP-012 | 011:T043, 011:T045, 011:T046, 011:T053, 011:T054 | test_classify, test_cli_extract_ledger, test_dispositions, test_extract_e2e (+1) | UT, IT | OK |
| REQ-KAP-013 | OBJ-KAP | KAP | 011:REQ-KAP-013 | 011:T034, 011:T041, 011:T044, 011:T047, 011:T053, 011:T054 | test_accounting, test_cli_extract_ledger, test_extract_driver, test_extract_e2e (+2) | UT, IT | OK |
| REQ-KAP-014 | OBJ-KAP | KAP | 011:REQ-KAP-014 | 011:T041, 011:T042, 011:T043, 011:T053, 011:T058 | test_cli_extract_ledger, test_dispositions, test_generator, test_ledger (+1) | UT | OK |
| REQ-KAP-015 | OBJ-KAP | KAP | 011:REQ-KAP-015 | 011:T055, 011:T057 | test_evidence_builder, test_evidence_schema_ext | UT | OK |
| REQ-KAP-016 | OBJ-KAP | KAP | 011:REQ-KAP-016 | 011:T056, 011:T058, 011:T059, 011:T061, 011:T062 | test_accept, test_candidates_e2e, test_cli_candidates, test_generator (+1) | UT, IT | OK |
| REQ-KAP-017 | OBJ-KAP | KAP | 011:REQ-KAP-017 | 011:T060, 011:T061 | test_ai_proposer, test_cli_candidates, test_evidence_schema_ext, test_release_consistency | UT | OK |
| REQ-KAP-018 | OBJ-KAP | KAP | 011:REQ-KAP-018 | 011:T009, 011:T025, 011:T027, 011:T062 | test_candidates_e2e, test_cli_rule, test_promote, test_release_safety | UT, IT | OK |
| REQ-KAP-019 | OBJ-KAP | KAP | 011:REQ-KAP-019 | 011:T020, 011:T023, 011:T024, 011:T027 | test_authoring_ops, test_cli_rule, test_rule_schema_ext, test_rule_store | UT | OK |
| REQ-KAP-020 | OBJ-KAP | KAP | 011:REQ-KAP-020 | 011:T022, 011:T026, 011:T059 | test_accept, test_authoring_checks, test_conflicts, test_knowledge_root_guard | UT | OK |
| REQ-KAP-021 | OBJ-KAP | KAP | 011:REQ-KAP-021 | 011:T020, 011:T021, 011:T024, 011:T027, 011:T059 | test_accept, test_authoring_ops, test_cli_rule, test_rule_history (+1) | UT | OK |
| REQ-KAP-022 | OBJ-KAP | KAP | 011:REQ-KAP-022 | 011:T002, 011:T004, 011:T005, 011:T006, 011:T011, 011:T012 (+2) | test_canonical, test_cli_package, test_p2_schemas, test_package_builder (+4) | UT | OK |
| REQ-KAP-023 | OBJ-KAP | KAP | 011:REQ-KAP-023 | 011:T003, 011:T010 | _archives, test_archive_reader, test_package_limits | UT | OK |
| REQ-KAP-024 | OBJ-KAP | KAP | 011:REQ-KAP-024 | 011:T002, 011:T006, 011:T011, 011:T018 | test_canonical, test_cli_package, test_package_builder, test_release_manifest | UT | OK |
| REQ-KAP-025 | OBJ-KAP | KAP | 011:REQ-KAP-025 | 011:T007, 011:T013, 011:T017, 011:T019 | test_cli_release, test_package_importer, test_package_lifecycle, test_release_store | UT, IT | OK |
| REQ-KAP-026 | OBJ-KAP | KAP | 011:REQ-KAP-026 | 011:T004, 011:T007, 011:T013, 011:T017, 011:T019 | test_cli_release, test_package_importer, test_package_lifecycle, test_release_model (+1) | UT, IT | OK |
| REQ-KAP-027 | OBJ-KAP | KAP | 011:REQ-KAP-027 | 011:T009, 011:T013, 011:T018 | test_cli_package, test_loader_active, test_package_importer, test_promote (+1) | UT | Default import of a pipeline-built release is refused for carried-forward built-in FIX_ENABLED rows (open decision KAP-OD-K13) |
| REQ-KAP-028 | OBJ-KAP | KAP | 011:REQ-KAP-028 | 011:T011, 011:T086 | test_kap_redaction, test_kap_redaction_boundaries, test_package_builder, test_package_snapshot_rule | UT | OK |
| REQ-KAP-029 | OBJ-KAP | KAP | 011:REQ-KAP-029 | 011:T068, 011:T070, 011:T071, 011:T089 | test_cli_release_build, test_pipeline, test_pipeline_e2e, test_pipeline_release_usable (+1) | UT, IT | OK |
| REQ-KAP-030 | OBJ-KAP | KAP | 011:REQ-KAP-030 | 011:T014, 011:T043, 011:T068 | test_dispositions, test_pipeline, test_release_diff, test_release_diff_layout | UT | OK |
| REQ-KAP-031 | OBJ-KAP | KAP | 011:REQ-KAP-031 | 011:T026, 011:T043, 011:T059 | test_accept, test_conflicts, test_dispositions | UT | OK |
| REQ-KAP-032 | OBJ-KAP | KAP | 011:REQ-KAP-032 | 011:T064, 011:T069, 011:T071 | test_cli_coverage, test_metrics | UT | OK |
| REQ-KAP-033 | OBJ-KAP | KAP | 011:REQ-KAP-033 | 011:T065 | test_crosscheck | UT | Cross-checks run as NOT_RUN without inputs; no named benchmark set exists (OD-K8), so no recall is reported |
| REQ-KAP-034 | OBJ-KAP | KAP | 011:REQ-KAP-034 | 011:T063, 011:T066, 011:T067, 011:T069, 011:T071 | test_cli_coverage, test_coverage_manifest, test_gates, test_p7_schemas | UT | M8 (transition coverage) has no gate: open owner question in the contract |
| REQ-KAP-035 | OBJ-KAP | KAP | 011:REQ-KAP-035 | 011:T063, 011:T067 | test_cli_coverage, test_coverage_manifest, test_p7_schemas | UT | OK |
| REQ-KAP-036 | OBJ-KAP | KAP | 011:REQ-KAP-036 | 011:T015, 011:T072, 011:T073, 011:T074, 011:T075, 011:T076 (+5) | test_builtin_digest, test_knowledge_root_guard, test_loader_active, test_migrate_with_release (+10) | UT, IT | OK |
| REQ-KAP-037 | OBJ-KAP | KAP | 011:REQ-KAP-037 | 011:T082 | test_migrate_coverage | UT | OK |
| REQ-KAP-038 | OBJ-KAP | KAP | 011:REQ-KAP-038 | 011:T082, 011:T083 | test_migrate_coverage, test_migrate_with_release | UT, IT | OK |
| REQ-KAP-039 | OBJ-KAP | KAP | 011:REQ-KAP-039 | 011:T009, 011:T072 | test_loader_active, test_migrate_coverage, test_pipeline_release_usable, test_release_consistency (+1) | UT, IT | Carried-forward built-in rows are grandfathered by identity at load (open decision KAP-OD-K13) |
| REQ-KAP-040 | OBJ-KAP | KAP | 011:REQ-KAP-040 | 011:T081 | test_report_release | UT | OK |
| REQ-KAP-041 | OBJ-KAP | KAP | 011:REQ-KAP-041 | 011:T082 | test_migrate_coverage | UT | OK |
| REQ-KAP-042 | OBJ-KAP | KAP | 011:REQ-KAP-042 | 011:T076, 011:T077, 011:T082, 011:T083 | test_migrate_coverage, test_migrate_with_release, test_reader_docker_env, test_reader_integrity | UT, IT | OK |
| REQ-KAP-043 | OBJ-KAP | KAP | 011:REQ-KAP-043 | 011:T088, 011:T090 | — | RV | RECORD (no test): docs/reviews/fragments/kap.md; certification stays PENDING_HUMAN_REVIEW |
| REQ-KAP-044 | OBJ-KAP | KAP | 011:REQ-KAP-044 | 011:T019, 011:T030, 011:T054, 011:T085, 011:T089, 011:T090 | test_extract_e2e, test_live_sources, test_package_lifecycle, test_quickstart (+1) | UT, IT | Opt-in live tests (ODOOFLUX_KAP_LIVE_TESTS, ODOOFLUX_KAP_CLONES, ODOOFLUX_KAP_DOCKER_TESTS) never run |
| REQ-KAP-045 | OBJ-KAP | KAP | 011:REQ-KAP-045 | 011:T008, 011:T017, 011:T068 | test_cli_release, test_pipeline, test_release_audit | UT | OK |
| REQ-KAP-046 | OBJ-KAP | KAP | 011:REQ-KAP-046 | 011:T008, 011:T086 | test_kap_redaction, test_kap_redaction_boundaries, test_release_audit | UT | OK |
| REQ-KAP-047 | OBJ-KAP | KAP | 011:REQ-KAP-047 | 011:T005, 011:T012, 011:T019 | test_p2_schemas, test_package_lifecycle, test_package_validate | UT, IT | OK |

## Release gate data

Hand-maintained input to the release gate (`tests/unit/release/rtm_tools.py`, feature 010 T003/T005, FC A-8). It is not
produced by the generator above. A requirement passes the gate through (1) a test file under `tests/` that cites one of
its `TST-nnn-nnn` ids or the requirement id, (2) a `DEFERRED_KB` row below with at least one backlog id that exists in
[KNOWLEDGE_BASE_BACKLOG.md](KNOWLEDGE_BASE_BACKLOG.md), or (3) a row in "Verification records". A requirement with none
of the three fails the gate. A row below on a requirement that also has tests marks a *partial* deferral: the mapped tests
exist, and the listed backlog items hold the part that waits for the Knowledge Base. Provisional-corpus tests (ADR-019)
count as tests for the framework mechanics, not as approved migration truth.

| REQ | Gate status | KB backlog IDs | Basis |
|---|---|---|---|
| REQ-TST-003 | DEFERRED_KB | KB-002-FIX, KB-002-T015, KB-006-T035r, KB-006-T044r, KB-006-SC003 | golden fixtures for 12.0, 13.0, 15.0, 16.0, 17.0 (OWL) and 18.0 sources; expected trees for 17.0 to 19.0 beyond the provisional module; 14.0, 15.0, 16.0 trees (002 T011-T016, 006 T035, T044) |
| REQ-TST-002 | DEFERRED_KB | KB-006-T059r | full quickstart run recorded for all paths (006 T059) |
| REQ-EVD-001 | DEFERRED_KB | KB-006-T025r | peer review of research records outside the validation path (006 T025) |
| REQ-EVD-006 | DEFERRED_KB | KB-006-T025r, KB-008-T029r, KB-010-SUP | `RESEARCHED` and `RUNTIME_VALIDATED` marks for paths beyond the validation path (006 T025, 008 T029); support statement growth |
| REQ-VAL-004 | DEFERRED_KB | KB-008-T029r | `RUNTIME_VALIDATED` for targets other than the validation path (008 T029) |
| REQ-VER-003 | DEFERRED_KB | KB-010-SUP | the support statement lists only the validation path as supported until more paths reach `RULES_TESTED` and `RUNTIME_VALIDATED` |

## Verification records

Rows that satisfy the gate by a recorded verification (RV/EV) instead of a test. Each row names a file and an anchor
text that must occur in it. Feature 011 adds one row: REQ-KAP-043 is a documentation requirement (technical completion is separate from human certification) and is satisfied by the register fragment, not by a test.

| REQ | Record | Anchor |
|---|---|---|
| REQ-KAP-043 | docs/reviews/fragments/kap.md | PENDING_HUMAN_REVIEW |
