---
description: "Task list for feature 005 — Structured Transformations (Phase P4)"
---

# Tasks: Structured Transformations

**Input**: Design documents from `/specs/005-structured-transformations/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: Required (Principle V). Write them first and confirm they fail before implementing.

## Format: `[ID] [P?] [Story] Description (REQ…; TST…) — Done when: …`

---

## Phase 1: Setup

- [X] T001 Create the modules listed in plan.md §Source Code under `src/odooflux/{core/engine,parsers/python,parsers/xml,parsers/javascript,transformers}/` and the test directories `tests/unit/{engine,parsers,transformers}/`, `tests/golden_fixtures/transformations/{python,xml,js,converter}/` (REQ-TRF-001) — Done when: imports succeed and the P2 structure test passes.
- [X] T002 [P] Declare the optional extra `js` (pinned `tree-sitter`, `tree-sitter-javascript`) in the packaging file created by P2, gated on D-02 approval (REQ-JS-001) — Done when: `pip install -e '.[js]'` works in CI and the core install pulls no new dependency.

## Phase 2: Foundational (blocks all stories)

- [X] T003 Write failing tests for `Document` decoding/encoding round-trip (UTF-8, UTF-8 BOM, CRLF, CR, mixed newlines, Latin-1 declared XML, Python coding cookie, undecodable bytes) in `tests/unit/engine/test_documents.py` (REQ-TRF-004; TST-005-001) — Done when: ≥ 10 cases fail.
- [X] T004 Implement `src/odooflux/core/engine/documents.py` (Document, Span, line/column conversion, encoding/newline/BOM preservation) (REQ-TRF-004) — Done when: TST-005-001 passes; an unchanged round-trip is byte-identical for all cases.

**Checkpoint**: documents round-trip byte-exactly.

---

## Phase 3: User Story 1 — Edits never corrupt files (P1) 🎯 MVP

- [X] T005 [P] [US1] Write failing tests for `apply_edits`: required-field validation, stale span, overlap groups (severity, `depends_on`, tie → reject), adjacency, same-offset insertions, input immutability, byte-preservation flag, in `tests/unit/engine/test_apply_edits.py` (REQ-TRF-001, REQ-TRF-002, REQ-TRF-004; TST-005-002) — Done when: ≥ 15 cases fail.
- [X] T006 [P] [US1] Write failing tests for `idempotence_check` with a toy rule that is idempotent and one that is not, in `tests/unit/engine/test_idempotence.py` (REQ-TRF-003; TST-005-003) — Done when: both cases fail before implementation.
- [X] T007 [US1] Implement `apply_edits` in `src/odooflux/core/engine/edits.py` exactly per contracts/edit-engine.md (REQ-TRF-001, REQ-TRF-002, REQ-TRF-004) — Done when: TST-005-002 passes.
- [X] T008 [US1] Implement `idempotence_check` in `src/odooflux/core/engine/edits.py` (REQ-TRF-003) — Done when: TST-005-003 passes.
- [X] T009 [US1] Add a harness test applying a randomised set of non-overlapping edits to every feature 002 golden fixture file and verifying byte preservation outside spans in `tests/unit/engine/test_preservation_fixtures.py` (REQ-TRF-004; TST-005-004) — Done when: 0 violations across all fixture files with a fixed random seed.

**Checkpoint**: the edit engine is safe; all later stories build edits on it.

---

## Phase 4: User Story 2 — Precise Python locations (P1)

- [X] T010 [P] [US2] Build the Python corpus `tests/golden_fixtures/transformations/python/`: multi-line decorators, comments between decorator and def, nested classes, keyword in first/middle/last/only position, trailing commas, continuation lines, non-ASCII identifiers/strings, tab indentation, `async`-as-identifier file (REQ-PY-001, REQ-PY-004) — Done when: ≥ 25 cases exist, each with `meta.json`.
- [X] T011 [P] [US2] Write failing span tests (`node_span`, `decorator_removal_span`, `keyword_removal_span`, `keyword_rename_span`) over the corpus in `tests/unit/parsers/test_python_spans.py` (REQ-PY-001; TST-005-005) — Done when: every corpus case has an expected span assertion.
- [X] T012 [US2] Implement `src/odooflux/parsers/python/{document,spans}.py` per contracts/span-locators.md, including UTF-8 column conversion (REQ-PY-001, REQ-PY-004) — Done when: TST-005-005 passes and the `async` file yields a `parse_error` with no spans.
- [X] T013 [US2] Write failing tests that apply the Python edit helpers to the corpus and assert that the output compiles and matches `expected.py`, in `tests/unit/transformers/test_python_helpers.py` (REQ-PY-001, REQ-TRF-003; TST-005-006) — Done when: all helper cases fail.
- [X] T014 [US2] Implement `src/odooflux/transformers/python.py` (`remove_decorator`, `remove_keyword`, `rename_keyword`, `replace_call_name`, `replace_attribute`) (REQ-PY-001, REQ-TRF-003) — Done when: TST-005-006 passes and a second application produces 0 edits.
- [X] T015 [US2] Add regression tests for audit F-PY-1 (decorator indentation) and F-PY-2 (`size=` comma) using the new helpers in `tests/regression/test_audit_transformations.py` (REQ-PY-001, REQ-TST-005; TST-005-007) — Done when: both pass and cite the finding IDs.

---

## Phase 5: User Story 3 — Precise XML locations and modifier conversion (P1)

- [X] T016 [P] [US3] Build the XML corpus `tests/golden_fixtures/transformations/xml/`: multi-line attributes, both quote styles, entities, comments, CDATA, DOCTYPE, processing instructions, non-ASCII, self-closing tags, nested views inside `<field name="arch">` (REQ-XML-001) — Done when: ≥ 20 cases exist.
- [X] T017 [P] [US3] Write failing XML span tests in `tests/unit/parsers/test_xml_spans.py` (REQ-XML-001; TST-005-008) — Done when: every case asserts element, start-tag, and attribute name/value spans.
- [X] T018 [US3] Implement `src/odooflux/parsers/xml/{document,expat_locator,attr_lexer}.py` per contracts/span-locators.md (REQ-XML-001) — Done when: TST-005-008 passes.
- [X] T019 [US3] Implement `src/odooflux/transformers/xml.py` (`set_attr`, `remove_attr`, `rename_tag`, `replace_element`, quote-safe escaping) with tests in `tests/unit/transformers/test_xml_helpers.py` (REQ-XML-001, REQ-TRF-003; TST-005-009) — Done when: all outputs are well-formed and idempotent.
- [X] T020 [P] [US3] Build the converter corpus (≥ 60 cases, groups listed in contracts/modifier-converter.md) in `tests/golden_fixtures/transformations/converter/` (REQ-XML-002) — Done when: every group has ≥ 3 cases and each case states mode and expected output or reason.
- [X] T021 [US3] Write failing converter tests in `tests/unit/transformers/test_modifiers.py` (REQ-XML-002; TST-005-010) — Done when: all corpus cases are asserted.
- [X] T022 [US3] Implement `src/odooflux/transformers/modifiers.py` (`convert_element`, `domain_to_expression`, both modes, merge, `states`, unconvertible reasons) (REQ-XML-002) — Done when: TST-005-010 passes; every output element is well-formed; a second conversion yields 0 edits.
- [X] T023 [US3] Add regression tests for audit F-XML-1 (no comments inside tags), F-XML-2 (expressions, not domains), F-XML-3 (`column_invisible` kept) and F-XML-4 (no duplicate `invisible`) in `tests/regression/test_audit_transformations.py` (REQ-XML-002, REQ-TST-005; TST-005-011) — Done when: all four pass.

---

## Phase 6: User Story 4 — JavaScript with or without a parser (P2)

- [X] T024 [P] [US4] Build the JS corpus `tests/golden_fixtures/transformations/js/`: `odoo.define` in code vs in strings/comments/template literals, regex literals containing `//`, ES modules with `@odoo-module`, a syntactically broken file (REQ-JS-001, REQ-JS-004) — Done when: ≥ 15 cases exist.
- [X] T025 [P] [US4] Write failing fallback-lexer tests (`code_spans` exclude strings, comments, templates, regex) in `tests/unit/parsers/test_js_lexer.py` (REQ-JS-001; TST-005-012) — Done when: all corpus cases are asserted.
- [X] T026 [US4] Implement `src/odooflux/parsers/javascript/lexer.py` (stdlib) (REQ-JS-001) — Done when: TST-005-012 passes.
- [X] T027 [US4] Write adapter tests (skipped unless `ODOOFLUX_JS_ADAPTER_TESTS=1`) for `parse`, `query`, `has_errors` in `tests/unit/parsers/test_js_adapter.py` (REQ-JS-001, REQ-JS-004; TST-005-013) — Done when: they run green in the CI job with the extra installed.
- [X] T028 [US4] Implement `src/odooflux/parsers/javascript/treesitter_adapter.py` with lazy import and `available()` (REQ-JS-001, REQ-ARC-001) — Done when: TST-005-013 passes and the core import-graph test still passes without the extra.
- [X] T029 [US4] Implement the L1 JS syntax validator `src/odooflux/validation/syntax/javascript.py` (FAIL on error nodes; UNAVAILABLE without the adapter), and the detect-only downgrade (`NEEDS_REVIEW`) hook used by JS rules (REQ-JS-004, REQ-JS-001) — Done when: tests in `tests/unit/parsers/test_js_validation.py` (TST-005-014) pass in both modes. **Status:** UNAVAILABLE path and detect-only hook done. The adapter-available branch is covered only by an injected test double; the real tree-sitter adapter (T027/T028) is skipped per D-02 (pending).

---

## Phase 7: Polish & Cross-Cutting

- [X] T030 [P] Benchmark parse+locate for generated 5,000-line Python and XML files in `tests/benchmarks/test_parse_perf.py` (REQ-PY-001, REQ-XML-001; TST-005-015) — Done when: each completes in < 1 s on the reference machine (opt-in suite).
- [X] T031 Run the whole-repository idempotence and preservation harness on all corpora and golden fixtures, and record the results in `specs/005-structured-transformations/verification.md` (REQ-TRF-003, REQ-TRF-004) — Done when: 0 violations are recorded, with the commit SHA.
- [X] T032 Run quickstart.md and record outputs in `specs/005-structured-transformations/verification.md` (REQ-TRF-001) — Done when: all expectations are met.

---

## Dependencies & Execution Order

- T001–T004 → US1 (T005–T009) → US2 (T010–T015) and US3 (T016–T023) in parallel → US4 (T024–T029; independent of US2/US3 except T007) → Polish.
- Feature dependencies: P2 exit (contracts, engine skeleton, validator registry). D-02 decides T002/T027/T028; if D-02 is rejected, T027/T028 are cancelled and FR-012 always reports UNAVAILABLE.

## Parallel Example

```text
After T008: T010, T016, T020, T024 (corpora) can be built in parallel by different agents.
After T012 and T018: T013 and T021 can proceed in parallel.
```

## Implementation Strategy

MVP = US1 (edit engine). Then US2 and US3 deliver what feature 006 needs first (Python and XML
rules); US4 can trail.
