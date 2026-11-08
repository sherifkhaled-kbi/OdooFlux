# Feature Specification: Structured Transformations

**Feature Branch**: `005-structured-transformations`
**Created**: 2026-11-06
**Status**: Draft — planned, not implemented
**Phase**: P4 ([handoff](../../docs/planning/phase-handoffs/PHASE_04_TRANSFORMATIONS.md))
**Input**: User description: "Implement Python, XML, JavaScript, and OWL transformation infrastructure: syntax-aware span location, a targeted edit engine with conflict detection and idempotence, byte-preserving edits, and a correct attrs/states to modifier-expression converter."

## Clarifications

### Session 2026-11-06

- Q: May any transformation re-serialise a whole file? → A: No. Edits are spans spliced into the original text (ADR-003); untouched bytes must be identical.
- Q: Which JavaScript parser? → A: Optional tree-sitter adapter (D-02, default as proposed in ADR-006); without it, JS is detect-only and results are `NEEDS_REVIEW`.
- Q: Does this feature ship migration rules? → A: No. It ships infrastructure, the converter, and test corpora. Rules are feature 006.
- Q: Is the attrs converter allowed to run on real modules in this feature? → A: Only through rules in feature 006. Here it is a library with a corpus. Its `FIX_ENABLED` use depends on gap G-R-20.
- Q: What happens with customer Python that the tool interpreter cannot parse? → A: File-level finding, `NEEDS_REVIEW`, no edits (REQ-PY-004).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Edits never corrupt files (Priority: P1)

A migration engineer runs fixes on a module. Every change is a targeted edit. Overlapping or stale
edits are rejected with a reason. Everything outside the edited spans remains byte-identical, and
running the fixes again changes nothing.

**Why this priority**: The audit's most damaging failures (F-PY-1, F-PY-2, F-XML-1) came from
untargeted rewrites. Every rule in feature 006 depends on this engine.

**Independent Test**: Apply synthetic edit sets (non-overlapping, overlapping, adjacent,
insertions, stale) to corpus files. Check outcomes, byte preservation, and idempotence.

**Acceptance Scenarios**:

1. **Given** two edits whose spans overlap, **When** applied, **Then** the documented precedence decides, or both are rejected with `conflict`, and the text is unchanged for rejected edits.
2. **Given** an edit whose `before` text no longer matches, **When** applied, **Then** it is rejected with `stale-span`.
3. **Given** a file with CRLF line endings, a BOM, and non-ASCII text, **When** edits are applied, **Then** the line endings, BOM, and all bytes outside the spans are unchanged.
4. **Given** a rule pipeline run on its own output, **When** re-run, **Then** zero edits are produced.

---

### User Story 2 - Precise Python locations (Priority: P1)

Rule authors locate decorators, call keyword arguments, imports, class attributes, and method
definitions, including multi-line constructs. They get exact spans and can remove or rewrite them
without breaking indentation or commas.

**Why this priority**: Python is the bulk of module code, and the audit showed line-regex
removal breaking indentation and commas.

**Independent Test**: Corpus files with multi-line decorators, comments between decorator and
`def`, keyword arguments in first, middle, and last position, and continuation lines. Spans and
removal helpers produce outputs that compile.

**Acceptance Scenarios**:

1. **Given** `@api.one` with a comment line before `def`, **When** the decorator-removal helper runs, **Then** the result compiles and the `def` keeps its original indentation.
2. **Given** `fields.Char(size=64, string='X')`, **When** the keyword-removal helper removes `size`, **Then** the result is `fields.Char(string='X')`.
3. **Given** a file valid only on Python ≤3.6 (`async` as an identifier), **When** parsed, **Then** a parse finding is returned and no spans are offered.

---

### User Story 3 - Precise XML locations and correct modifier conversion (Priority: P1)

Rule authors locate elements and attributes, including multi-line attribute values. `attrs` and
`states` are converted into modifier expressions, merged with existing modifiers. Unconvertible
cases are left untouched and explained.

**Why this priority**: View modifiers are the largest 16→17 change (EV-109). The legacy output
was wrong (F-XML-2) and invalid (F-XML-1).

**Independent Test**: The converter corpus covers each operator, nesting, falsy values,
context names, existing-attribute merge, `column_invisible`, and unconvertible inputs. The XML
output of every corpus case is well-formed.

**Acceptance Scenarios**:

1. **Given** `attrs="{'invisible': [('state', '=', 'done')]}"`, **When** converted, **Then** the result is `invisible="state == 'done'"`.
2. **Given** `attrs="{'readonly': ['|', ('state', '=', 'done'), ('name', '=', False)]}"`, **When** converted in `falsy` mode, **Then** the result is `readonly="state == 'done' or not name"`.
3. **Given** an element with `invisible="a"` and `attrs` invisible `[('b','=',1)]`, **When** converted, **Then** the result is `invisible="(a) or (b == 1)"`.
4. **Given** `attrs` containing `('name', 'ilike', 'x')`, **When** converted, **Then** no edit is produced and the finding reason is `unsupported operator ilike`.
5. **Given** `states="draft,sent"` on a button, **When** converted, **Then** the result is `invisible="state not in ['draft', 'sent']"`, with no comment inside the tag.

---

### User Story 4 - JavaScript handled safely with or without a parser (Priority: P2)

With the JS adapter installed, rule authors get parse-tree spans and syntax validation. Without
it, detection still works (never matching inside strings or comments), but no JS edits are made
and results are flagged for review.

**Why this priority**: JS/OWL rules (feature 006) need spans; the stdlib cannot parse JS.

**Independent Test**: Run the same corpus with the adapter available and with it masked.

**Acceptance Scenarios**:

1. **Given** the adapter is unavailable, **When** a JS rule detects a construct, **Then** the finding is reported, no edit is planned, and the file result is `NEEDS_REVIEW`.
2. **Given** the adapter is available and an edit produces invalid JS, **When** validated, **Then** the edit is rejected.
3. **Given** `"odoo.define("` inside a string literal, **When** detection runs in fallback mode, **Then** nothing is reported.

### Edge Cases

- Edits on a file with mixed tabs/spaces: indentation for removed lines comes from the original line, never normalised.
- Attribute values using `&quot;` or single quotes containing double quotes: the converter emits values with a quote character not present in the expression, escaping `&`, `<`, and the chosen quote as XML entities.
- XML with a DOCTYPE or processing instructions: preserved.
- Multiple `attrs` attributes on one element (invalid XML): parse error finding, no edits.
- Zero-length insertions at the same offset: ordered deterministically.
- Very large files (>5 MB): processed, and a performance warning is reported if parsing exceeds the budget.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST represent every change as an Edit with ID, rule ID, file, span, before text, after text, step, and validation list, and MUST reject edits missing required fields. Traces: REQ-TRF-001.
- **FR-002**: The edit engine MUST detect overlapping spans and resolve them by the documented precedence, or reject both, recording `conflict:<other-edit>`. Traces: REQ-TRF-002.
- **FR-003**: The edit engine MUST reject edits whose `before` text does not match the current text at the span (`stale-span`). Traces: REQ-TRF-001, REQ-TRF-002.
- **FR-004**: Applying edits MUST preserve all bytes outside edit spans, including encoding, BOM, and newline style. Traces: REQ-TRF-004.
- **FR-005**: The system MUST provide an idempotence harness that re-runs a rule set on its output and fails on any new edit. Traces: REQ-TRF-003.
- **FR-006**: The Python parser MUST provide exact spans for modules, classes, functions, decorators, calls, keyword arguments, assignments, imports, and comments, using syntax-aware parsing. Traces: REQ-PY-001.
- **FR-007**: The system MUST provide Python edit helpers for whole-line decorator removal and comma-safe keyword-argument removal or rename that always produce compilable output on the corpus. Traces: REQ-PY-001, REQ-TRF-003.
- **FR-008**: Unparseable Python MUST produce a file-level parse finding and no edits. Traces: REQ-PY-004.
- **FR-009**: The XML parser MUST provide exact spans for elements, start tags, attributes (name, value, quotes), text, and comments, including multi-line attribute values. Traces: REQ-XML-001.
- **FR-010**: The system MUST convert `attrs` and `states` into `invisible`, `readonly`, `required`, and `column_invisible` Python expressions per [research.md R-5](research.md#r-5-attrsstates--modifier-expressions), merge with existing modifiers, and leave unconvertible inputs unchanged with a reason. Traces: REQ-XML-002.
- **FR-011**: The JS layer MUST use the parser adapter for spans and edits when available. When unavailable, it MUST be detect-only via a string/comment/regex-aware lexer and MUST mark results `NEEDS_REVIEW`. Traces: REQ-JS-001.
- **FR-012**: When the JS adapter is available, written JS MUST be rejected if the parse tree contains error nodes. When it is unavailable, the JS syntax validator MUST report `UNAVAILABLE`. Traces: REQ-JS-004.

### Key Entities

- **Document** (Python, XML, JS variants): see [data-model.md](data-model.md).
- **Span / Edit / EditBatchResult**: see [contracts/edit-engine.md](contracts/edit-engine.md).
- **ModifierConversion**: input attributes → output attributes or reason; see [contracts/modifier-converter.md](contracts/modifier-converter.md).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of corpus outputs pass the language syntax validator (Python compiles; XML is well-formed; JS is error-free with the adapter).
- **SC-002**: Byte preservation outside spans holds on 100 % of corpus files and on every golden fixture from feature 002.
- **SC-003**: Idempotence: a second pass yields 0 edits on 100 % of corpus files.
- **SC-004**: The converter corpus (≥ 60 cases) passes with no unexpected outputs; every unconvertible case has a reason.
- **SC-005**: Parsing and span location of a 5,000-line Python file and a 5,000-line XML file each complete in under 1 second on the reference machine.
- **SC-006**: The audit reproductions F-PY-1, F-PY-2, F-XML-1, and F-XML-2 cannot be reproduced through the new helpers (regression tests pass).

## Assumptions

- Phase P2 provides `core/contracts` (Edit, Finding, Document base), `core/engine` skeleton, and validator registry.
- D-02 is approved as proposed. If it is rejected, US4 delivers only the fallback lexer and FR-012 always reports `UNAVAILABLE`.
- Converter modes (`literal`/`falsy`) are configurable per rule. The default is chosen in feature 006 after G-R-20.
- OWL template XML (`static/src/**/*.xml`) is handled by the XML layer; OWL-specific rules are feature 006.
