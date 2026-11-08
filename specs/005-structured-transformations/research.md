# Research: Structured Transformations (Feature 005 / Phase P4)

## R-1 Python spans: `ast` + `tokenize` (ADR-004)
- **Decision:** Build `PythonDocument` with an `ast.Module` (all nodes carry
  `lineno/col_offset/end_lineno/end_col_offset`, available since Python 3.8) and a token list
  from `tokenize.generate_tokens`. Convert (line, UTF-8 column) to absolute character offsets
  through a precomputed line-start table. Note: `col_offset` is a **UTF-8 byte** offset; the
  converter must decode per line.
- **Decorator spans** come from `FunctionDef.decorator_list` nodes; a whole-line removal span
  covers the line's leading indentation through its newline, plus following comment-only lines
  that belong to the decorator (audit F-PY-1).
- **Call-argument spans** (e.g. removing a keyword argument) use the `ast.keyword` node span plus
  token-level comma handling: remove the following comma when the argument is not last,
  otherwise the preceding comma (audit F-PY-2).
- **Alternatives:** `libcst` (format-preserving CST, MIT): rejected for core per ADR-002;
  revisit only through a new ADR. `lib2to3`/`parso`: deprecated or third-party; rejected.

## R-2 XML spans: expat locator + attribute lexer (ADR-005)
- **Decision:** `xml.parsers.expat` start/end element handlers record
  `parser.CurrentByteIndex` for each element start. A dedicated lexer then scans the raw start
  tag from that index to find attribute name/value spans, including quote style, entity-encoded
  content, and newlines inside values. Expat reports byte indexes; the document keeps a
  byte→char map for non-ASCII files.
- `xml.etree.ElementTree` (with `TreeBuilder(insert_comments=True)` where useful) is used for
  structure queries and well-formedness only, never for writing.
- RNG validation is not in this feature (P7, optional `lxml`; EV-204 shows Odoo itself validates
  archs with `lxml.etree.RelaxNG`).
- **Alternatives:** `lxml` with `sourceline` gives line numbers only, not columns; re-serialising
  reorders or normalises attributes. Rejected for editing.

## R-3 JavaScript: optional tree-sitter adapter + stdlib detection lexer (ADR-006, D-02)
- **Decision:** `parsers/javascript/treesitter_adapter.py` wraps `tree_sitter` with the
  `tree_sitter_javascript` grammar (both MIT; versions pinned in the optional extra). When
  unavailable, `parsers/javascript/lexer.py` (stdlib) tokenises strings, template literals,
  comments, and regex literals so that detectors never match inside them. In fallback mode, JS
  rules are detect-only and the file result is `NEEDS_REVIEW` (REQ-JS-001).
- **JS syntax validation (REQ-JS-004):** with the adapter, a tree containing `ERROR` or `MISSING`
  nodes fails validation; without it, the validation layer reports `UNAVAILABLE`.
- **Alternatives:** esprima-python (ES2017 only, unmaintained); Node + acorn (Node dependency).
  Both rejected (see ADR-006).

## R-4 Edit engine semantics
- **Decision:** Edits are applied in descending `span.start` order on a single text buffer, after
  sorting and overlap detection. Adjacent edits (`a.end == b.start`) are not overlaps. Insertions
  (`start == end`) at the same offset are ordered by rule order and then edit ID.
- **Stale-span protection:** before applying, `text[start:end] == before` must hold; otherwise
  the edit is `REJECTED` with reason `stale-span`.
- **Idempotence check:** the harness applies the pipeline to its own output and asserts zero new
  edits (REQ-TRF-003).
- **Byte preservation:** the harness asserts that `output` outside the union of applied spans
  equals the input byte for byte, after mapping offsets (REQ-TRF-004). Encoding and newline
  style are detected and preserved; a BOM is preserved.

## R-5 `attrs`/`states` → modifier expressions
- **Official basis:** 17.0 rejects `attrs` and `states` view attributes (EV-109).
- **Target semantics:** in 17.0+ the modifier attributes `invisible`, `readonly`, `required`, and
  (list columns) `column_invisible` hold **Python expressions** evaluated against the record. The
  exact evaluation context (available names such as `parent`, `context`, `uid`) was **not
  verified at a pinned SHA during planning**. Gap **G-R-20** must be resolved before rule
  `16-17.xml.attrs-removed` becomes `FIX_ENABLED`. The converter can be built and unit-tested
  before then; its correctness against Odoo is proven in P5/P7.
- **Domain grammar handled:** prefix operators `&`, `|`, `!` with implicit AND between
  consecutive terms. Leaves are `(field_path, op, value)` with
  `op ∈ {=, ==, !=, <>, <, <=, >, >=, in, not in}`. Values may be literals (str, int, float,
  bool, None, lists/tuples of literals) or bare names from the evaluation context
  (`parent.x`, `context.get(...)`, `uid`, `active_id`), preserved as source text.
- **Mapping:**
  - `=`/`==` → `==`; `<>` → `!=`.
  - `in`/`not in` keep the list literal.
  - `(f, '=', False)` and `(f, '!=', False)` are emitted as `not f` and `f`.
  - This falsy shortcut is equivalent only if relational and empty values are falsy in the target
    evaluation context. That is part of G-R-20, so the converter has a `literal` mode
    (`f == False`) and a `falsy` mode.
  - **G-R-20 decision (T010, 2026-11-07): `literal`.** Pinned 17.0 SHA `9ef8d62331b128bcd288528e4639e0901d85fcc8`,
    baseline 16.0 SHA `9f40bf622c5531739321e59276c307319198e22b`:
    - Evaluation: `evaluateBooleanExpr` wraps the string in `bool()` (`addons/web/static/src/core/py_js/py.js:56-63`);
      form `_isInvisible` uses `evalContextWithVirtualIds` (`addons/web/static/src/model/relational_model/record.js:651`);
      the view compiler emits `!__comp__.evaluateBooleanExpr(...)` (`addons/web/static/src/views/view_compiler.js:235`).
    - Names: `getBasicEvalContext` (`addons/web/static/src/model/relational_model/utils.js:312-322`: `context`, `uid`,
      `allowed_company_ids`, `active_id`/`active_ids`/`active_model` marked deprecated for v18, `current_company_id`);
      record data plus `id` (`record.js:458-494`); `parent` getter (`record.js:57`).
    - Falsy: `bool()` treats `0`, `''`, `[]`, `None` as false (`addons/web/static/src/core/py_js/py_builtin.js:33-54`),
      and `not` uses it (`py_interpreter.js:45`). So `not f` is false-y for `''`, `[]` and `0`.
    - Equality: `==` uses `isEqual` (`py_interpreter.js:109-122`). `0 == False` is true there, but `'' == False`
      and `[] == False` are false. Literal `f == False` therefore matches NULL-like values and `0`, not `''`/`[]`.
    - Baseline: 16.0 attrs-derived modifiers were JSON evaluated by `evalDomain` (`addons/web/static/src/views/utils.js:135-139`)
      through `Domain.contains` and strict `fieldValue === value` (`addons/web/static/src/core/domain.js:91`, `:222`).
      Literal mode matches this except for numeric `0`. `falsy` also diverges for `''` and `[]`. Hence `literal`.
    - Merge: 17.0 combines `invisible` with `column_invisible` by `OR` (`addons/web/static/src/model/relational_model/utils.js:200`,
      `addons/web/static/src/views/utils.js:242`). That supports the `or` merge for `invisible` only. `readonly`/`required`
      combination was not traced to a 17.0 render path, so it stays an assumption.
    - Server: 17.0 rejects `attrs`/`states` (`odoo/addons/base/models/ir_ui_view.py:392-398`) and validates modifier
      strings as Python (`:1664-1667`).
    - Unresolved: numeric `0` diverges in literal mode (`0 == False` is true at 17.0, false in 16.0 strict). Not
      evaluated in a running client. Evidence records were **not** written (EV-354 to EV-359 were taken by another
      agent at write time). Rule `16-17.xml.attrs-removed` stays `DETECT_ONLY` until records and fixtures exist.
- **Unconvertible** (left unchanged, finding stays `OPEN` with reason):
  - operators `like`, `ilike`, `=like`, `child_of`, `parent_of`;
  - non-literal values that are function calls other than `context.get`;
  - malformed domains;
  - keys other than the four modifiers.
- **Merging with existing attributes:** if the element already has `invisible="X"` and `attrs`
  also defines `invisible`, combine the two as `(X) or (Y)`. Readonly and required are combined
  the same way. This matches the "any condition true" semantics of the old dict; it is a
  documented assumption to verify under G-R-20.
- **`states="a,b"`** → `invisible="state not in ['a', 'b']"`, merged with an existing
  `invisible` by `or`. If the view's model has no `state` field (not determinable statically
  without the model index), a `NEEDS_REVIEW` finding is added. Comments are never inserted
  inside tags (audit F-XML-1).

## R-6 Python-version parsing of customer code (REQ-PY-004)
- **Decision:** Parse with the tool interpreter (≥3.10). Odoo 12.0–16.0 minimums are 3.5–3.7
  (EV-125). Constructs valid there but invalid on 3.10+ (for example `async`/`await` as
  identifiers, valid only up to 3.6) produce a `SyntaxError` finding with
  `NEEDS_REVIEW`, and no edits to that file. The test corpus includes such a file.

## New research gaps

| ID | Gap | Blocks |
|---|---|---|
| G-R-20 | Evaluation context and semantics of 17.0+ view modifier expressions (names available; falsy handling of relational/empty values; combination with existing attributes) | `16-17.xml.attrs-removed`, `16-17.xml.states-attribute-removed` FIX_ENABLED |
