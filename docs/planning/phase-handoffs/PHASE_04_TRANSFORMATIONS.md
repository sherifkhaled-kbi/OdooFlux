# Phase Handoff — P4 Structured Transformations

## 1. Phase ID
P4. Spec Kit feature: [specs/005-structured-transformations](../../../specs/005-structured-transformations/)

## 2. Phase title
Structured Transformations: syntax-aware span location, targeted edit engine, modifier converter.

## 3. Objective
Replace regex text rewriting with "parse to locate, splice to edit" (ADR-003):
- documents and exact span locators for Python, XML, and JavaScript (optional adapter);
- an edit engine with conflict and stale-span rejection, byte preservation, and an idempotence
  harness;
- language edit helpers;
- a correct `attrs`/`states` → modifier-expression converter, proven on corpora.

## 4. Requirements covered
REQ-TRF-001, REQ-TRF-002, REQ-TRF-003, REQ-TRF-004, REQ-PY-001, REQ-PY-004, REQ-XML-001,
REQ-XML-002, REQ-JS-001, REQ-JS-004 (plus REQ-TST-005 for audit regressions). Spec FR-001…FR-012.

## 5. Repository context
- After P2: `core/contracts` (Edit, Finding, Document base), `core/engine` skeleton,
  `validation/syntax` for Python/XML (from P0 logic), validator registry.
- Audit defects to make impossible: F-PY-1, F-PY-2, F-XML-1, F-XML-2, F-XML-3, F-XML-4
  ([audit](../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md)).
- Feature 002 golden fixtures are reused for the byte-preservation harness.

## 6. Prerequisites
- P2 exit met.
- D-02 decided (JS adapter: tree-sitter + lxml RNG; this phase uses only the JS part). If
  rejected, follow the fallback in tasks.md "Dependencies".

## 7. Dependencies
- Upstream: P2.
- Downstream: P5 (all fixers), P6 (AI edits go through the same engine).
- Parallel with P3 and P7.

## 8. Expected files and components
Per [plan.md](../../../specs/005-structured-transformations/plan.md#source-code-repository-root):
- `core/engine/{edits,documents}.py`
- `parsers/python/*`, `parsers/xml/*`, `parsers/javascript/*`
- `transformers/{python,xml,modifiers}.py`
- `validation/syntax/javascript.py`
- corpora under `tests/golden_fixtures/transformations/`
- tests under `tests/unit/{engine,parsers,transformers}/` and `tests/regression/`

## 9. Interfaces and contracts
- [contracts/edit-engine.md](../../../specs/005-structured-transformations/contracts/edit-engine.md)
- [contracts/span-locators.md](../../../specs/005-structured-transformations/contracts/span-locators.md)
- [contracts/modifier-converter.md](../../../specs/005-structured-transformations/contracts/modifier-converter.md)
- [data-model.md](../../../specs/005-structured-transformations/data-model.md)
- [architecture/CONTRACTS.md](../architecture/CONTRACTS.md) (Edit, Document, ParserAdapter, Validator)

## 10. Official evidence requirements
- The converter targets the 17.0 modifier change (EV-109).
- Evaluation semantics are gap G-R-20. The converter is built and tested here with both modes;
  the evidence-based mode choice is made in P5 (feature 006 T010) before any `FIX_ENABLED` use.
- No other Odoo claims are made in this phase.

## 11. Detailed implementation tasks
[specs/005-structured-transformations/tasks.md](../../../specs/005-structured-transformations/tasks.md), T001–T032.

## 12. Acceptance criteria
SC-001…SC-006 in [spec.md](../../../specs/005-structured-transformations/spec.md#success-criteria-mandatory),
and the roadmap exit:
1. Span locators exact on the corpus.
2. Edit engine handles conflicts, before-text checks, and idempotence.
3. Converter passes its corpus.
4. Byte preservation proven on golden fixtures.
5. JS adapter works, with detect-only fallback.

## 13. Unit tests
TST-005-001…003, 005, 006, 008, 009, 010, 012, 013, 014.

## 14. Integration tests
- TST-005-004 (preservation over all feature 002 golden fixtures).
- TST-005-007 and TST-005-011 (audit regressions).
- Whole-repo harness run (T031).

## 15. Runtime tests where applicable
None. Odoo acceptance of converted modifiers is verified in P7 through golden migrations.

## 16. Negative test cases
- Overlapping edits.
- Stale spans.
- Invalid edits.
- Unparseable Python (`async` identifier).
- Malformed XML / duplicate attributes.
- Unsupported domain operators (`ilike`, `child_of`).
- Malformed `attrs` dicts.
- Unknown `attrs` keys.
- JS strings/comments containing pattern text.
- JS edits producing error nodes.
- Adapter unavailable.

## 17. Security requirements
- Never `eval` customer content. Use only `ast.literal_eval` on placeholder-substituted text.
- Expat must not resolve external entities (disable DTD/external entity handling).
- Bound input sizes reported, not crashed on.

## 18. Performance requirements
5,000-line Python/XML parse + locate < 1 s each (TST-005-015).

## 19. Backward compatibility
- No CLI changes.
- P2 engine skeleton APIs keep their signatures. Extensions are additive.
- Legacy script untouched.

## 20. Prohibited changes
- No migration rules (P5).
- No whole-file re-serialisation.
- No non-stdlib imports in core (the JS adapter only, lazily imported).
- No `eval`/`exec`.
- No comments injected inside XML tags.

## 21. Definition of Done
- T001–T032 checked.
- All TST-005-* passing (adapter suite in its CI job).
- 0 preservation/idempotence violations recorded.
- verification.md complete.
- Roadmap exit met.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` to `{"feature_directory": "specs/005-structured-transformations"}`.
2. Read spec → plan → research → data-model → contracts → tasks.
3. Run `/speckit-implement`. Build the corpora before the code that they test.
4. If G-R-20 research becomes available early, do not change converter defaults here; record it for P5.
5. Stop and ask on any contract ambiguity ([IMPLEMENTATION_AGENT_GUIDE.md](../IMPLEMENTATION_AGENT_GUIDE.md)).

## 23. Expected verification evidence
`specs/005-structured-transformations/verification.md` containing:
- the commit SHA;
- test summaries (core and adapter jobs);
- the converter corpus result (`cases>=60 failures=0`);
- the preservation/idempotence harness report;
- benchmark numbers;
- the audit regression test list.

## 24. Handoff checklist
- [ ] P2 exit verified; D-02 decision recorded
- [ ] Corpora built (Python ≥25, XML ≥20, converter ≥60, JS ≥15)
- [ ] Tests first, observed failing
- [ ] Edit engine contract fully tested
- [ ] Audit regressions F-PY-1/2, F-XML-1/2/3/4 passing
- [ ] Core import-graph test passes without extras
- [ ] verification.md complete
- [ ] P5 informed of helper APIs and the converter modes
