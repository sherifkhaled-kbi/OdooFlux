# Implementation Plan: Structured Transformations

**Branch**: `005-structured-transformations` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-structured-transformations/spec.md`

## Summary

Replace regex-over-text with "parse to locate, splice to edit" (ADR-003). Deliverables:
- documents and span locators for Python (`ast`/`tokenize`), XML (expat + attribute lexer), and
  JS (optional tree-sitter adapter + stdlib lexer);
- the edit engine (conflicts, stale spans, byte preservation) and an idempotence harness;
- language edit helpers;
- the `attrs`/`states` → modifier-expression converter with a ≥60-case corpus.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: stdlib (`ast`, `tokenize`, `io`, `xml.parsers.expat`, `xml.etree.ElementTree`, `codecs`). Optional extra `odooflux[js]`: `tree-sitter` and `tree-sitter-javascript`, pinned versions (D-02)
**Storage**: N/A (in-memory documents; corpus files under `tests/golden_fixtures/transformations/`)
**Testing**: `unittest`; adapter tests skip when the extra is not installed (and a CI job installs it)
**Target Platform**: Linux/macOS/Windows
**Project Type**: CLI tool library layer
**Performance Goals**: SC-005 (5,000-line Python/XML file < 1 s parse + locate)
**Constraints**: Core must import only stdlib; adapters are imported lazily inside `parsers/javascript/treesitter_adapter.py` (REQ-ARC-001)
**Scale/Scope**: Files up to several MB; modules up to thousands of files (via P2 orchestration)

## Constitution Check (v2.0.0)

| Principle | Check | Status |
|---|---|---|
| I Dependency-light core | Python/XML stdlib; JS parser optional adapter with documented downgrade | PASS (adapter is the declared exception, ADR-006/D-02) |
| II Safe, reversible | Engine never mutates inputs; rejects instead of corrupting | PASS |
| III Deterministic first | Converter is deterministic; no AI | PASS |
| IV Honest reporting | Rejections carry reasons; JS fallback → NEEDS_REVIEW | PASS |
| V Test-backed | Corpus + idempotence + byte-preservation harness | PASS |
| VI Official evidence | Converter semantics gated on G-R-20 before FIX_ENABLED use (feature 006) | PASS |
| VII Layered validation | Language validators (L1) used on every edit batch | PASS |
| VIII Business logic | Converter refuses unsupported operators; merges are documented | PASS |
| IX Modular | Parser adapters behind `ParserAdapter` contract | PASS |
| X Phase delivery | Depends on P2; rules deferred to feature 006 | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/005-structured-transformations/
├── spec.md  plan.md  research.md  data-model.md  quickstart.md  tasks.md
├── contracts/{edit-engine.md, span-locators.md, modifier-converter.md}
└── checklists/requirements.md
```

### Source Code (repository root)

```text
src/odooflux/core/engine/edits.py              # apply_edits, idempotence_check
src/odooflux/core/engine/documents.py          # Document base, encoding/newline/BOM handling, Span
src/odooflux/parsers/python/{__init__,document,spans}.py
src/odooflux/parsers/xml/{__init__,document,expat_locator,attr_lexer}.py
src/odooflux/parsers/javascript/{__init__,lexer,treesitter_adapter}.py
src/odooflux/transformers/{__init__,python,xml,modifiers}.py
src/odooflux/validation/syntax/{python,xml,javascript}.py   # L1 validators (python/xml from P2; js new)
tests/unit/engine/  tests/unit/parsers/  tests/unit/transformers/
tests/golden_fixtures/transformations/{python,xml,js,converter}/
tests/regression/test_audit_transformations.py
```

**Structure Decision**: Matches [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md) (`parsers/`, `transformers/`, `core/engine/`).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Optional third-party JS parser (Principle I exception) | The stdlib cannot parse JavaScript; OBJ-002 requires JS/OWL transforms | A regex-only JS approach reproduces the audit's failure class (string/comment matches, broken output) |
| Custom expat attribute lexer | Stdlib XML APIs do not expose attribute spans | `lxml` sourceline lacks columns and re-serialisation breaks formatting |
