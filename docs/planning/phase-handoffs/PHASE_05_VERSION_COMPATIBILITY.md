# Phase Handoff — P5 Version Compatibility Rules

## 1. Phase ID
P5. Spec Kit feature: [specs/006-version-compatibility-rules](../../../specs/006-version-compatibility-rules/)

## 2. Phase title
Version Compatibility Rules: researched, evidence-backed, tested migration rules per step.

## 3. Objective
Turn seeded evidence into tested rules for steps 14-15…18-19 (D-04 default), with research
first where gaps block rules. Also deliver:
- manifest, dependency, reference, and security-data checks;
- a business-logic risk inventory;
- golden multi-step migrations;
- disposition of all 68 legacy rules.

## 4. Requirements covered
REQ-PY-002, REQ-PY-003, REQ-XML-002, REQ-XML-003, REQ-XML-005, REQ-JS-002, REQ-JS-003,
REQ-MAN-003, REQ-DEP-001, REQ-DEP-003, REQ-ACL-001, REQ-BIZ-001, REQ-TST-002, REQ-TST-003,
REQ-VAL-003 (static part), REQ-VER-005, REQ-EVD-001/003 (application). Spec FR-001…FR-016.

## 5. Repository context
- Knowledge base and evidence enforcement (P3).
- Parsers, edit engine, and converter (P4).
- Seed rule catalogue: [VERSION_COMPATIBILITY_MATRIX.md](../VERSION_COMPATIBILITY_MATRIX.md).
- Legacy dispositions: [MIGRATION_RULE_ENGINE.md](../MIGRATION_RULE_ENGINE.md#legacy-rule-disposition).
- Golden fixtures per source version (P1).

## 6. Prerequisites
- P3 and P4 exit met.
- D-04 (first-release source floor; default 14.0) and D-05 (Enterprise; default none) recorded.
- Network access for research agents to clone official repositories at pinned SHAs.

## 7. Dependencies
- Upstream: P3, P4.
- Downstream: P6 (AI handles ai-eligible leftovers), P7 (runtime confirmation → `VERIFIED`,
  `RUNTIME_VALIDATED`), P9.

## 8. Expected files and components
Per [plan.md](../../../specs/006-version-compatibility-rules/plan.md#source-code-repository-root):
- `rules/{python,xml,qweb,javascript,owl,assets,manifest,security}/**`
- `dependencies/{core_modules,references}.py`
- `analyzers/risk_inventory.py`
- `knowledge/compatibility/{<step>.rules.json, core_modules/*.json, legacy_disposition.json}`
- new `knowledge/evidence/EV-3NN.json`
- `tools/extract_core_modules.py`
- rule tests, per-rule fixtures, and golden expected trees

## 9. Interfaces and contracts
- [contracts/rule-catalogue.md](../../../specs/006-version-compatibility-rules/contracts/rule-catalogue.md)
- [data-model.md](../../../specs/006-version-compatibility-rules/data-model.md)
- Rule/Edit/Finding contracts in [architecture/CONTRACTS.md](../architecture/CONTRACTS.md)
- Maturity and ordering in [MIGRATION_RULE_ENGINE.md](../MIGRATION_RULE_ENGINE.md)

## 10. Official evidence requirements
- Every rule cites EV records. Research tasks T010–T025 create new records (EV-3NN) only from
  allow-listed official sources at pinned SHAs, with path:line, and are peer-reviewed (T025).
- Rules gated on unresolved gaps stay `DETECT_ONLY` and are recorded as such.
- No rule from memory, skills, or unofficial sources.

## 11. Detailed implementation tasks
[specs/006-version-compatibility-rules/tasks.md](../../../specs/006-version-compatibility-rules/tasks.md),
T001–T059, including the research-gate map in "Dependencies & Execution Order".

## 12. Acceptance criteria
SC-001…SC-006 in [spec.md](../../../specs/006-version-compatibility-rules/spec.md#success-criteria-mandatory),
and the roadmap exit:
1. Every rule has evidence, maturity, and tests.
2. Every step in scope has a research record.
3. The matrix shows `RULES_TESTED` only where true.
4. Golden migrations pass per source version.
5. Legacy rules are mapped with rationale.

## 13. Unit tests
TST-006-001…005, 007…014, 016…023, 025…033, plus per-rule tests. The rule-coverage test is
TST-006-001.

## 14. Integration tests
- TST-006-006 (golden harness).
- TST-006-015, 024 (golden migrations).
- TST-006-034 (add-a-version procedure).

## 15. Runtime tests where applicable
None in this phase. P7 re-runs the golden migrations in containers and promotes evidence/matrix status.

## 16. Negative test cases
Every rule has a negative fixture. In addition:
- constructs already in target form;
- string literals and comments containing patterns;
- `sudo(True/False)`;
- aliased imports with ambiguous resolution (no fix);
- Enterprise-like unknown dependencies (WARNING, not CRITICAL);
- `review_required` rules never producing edits (SC-005).

## 17. Security requirements
- The `*.python.sql-string-formatting` hygiene rule flags raw SQL built by string formatting.
- No customer code execution.
- `tools/extract_core_modules.py` reads git objects only; no shell interpolation.

## 18. Performance requirements
A ≥50-file module analysed in < 10 s (TST-006-035).

## 19. Backward compatibility
- Legacy rule behaviour is intentionally not preserved where it was wrong. Each difference is
  recorded in `legacy_disposition.json` and the change record.
- CLI options are unchanged.

## 20. Prohibited changes
- No fixers on `review_required` rules.
- No rules without evidence.
- No edits outside the edit engine.
- No changes to P4 contracts except additive helpers.
- No `VERIFIED` statuses (P7).
- No AI (P6).

## 21. Definition of Done
- T001–T059 checked, or explicitly deferred with recorded reasons in verification.md (research
  gates only).
- All TST-006-* passing.
- Matrix regenerated; `--check` passing.
- 68/68 legacy dispositions recorded.
- Roadmap exit met.

## 22. Implementation agent instructions
1. Set `.specify/feature.json` to `{"feature_directory": "specs/006-version-compatibility-rules"}`.
2. Read spec → plan → research → data-model → contracts → tasks.
3. Run `/speckit-implement`. Schedule the research tasks in parallel with evidence-complete rule
   tasks, as in the parallel example.
4. When research contradicts the catalogue, follow the evidence, update the catalogue and the
   matrix through data, and record it.
5. Stop and ask if a gate cannot be resolved from official sources ([IMPLEMENTATION_AGENT_GUIDE.md](../IMPLEMENTATION_AGENT_GUIDE.md)).

## 23. Expected verification evidence
`specs/006-version-compatibility-rules/verification.md` containing:
- the commit SHA;
- the rule-coverage report (`missing=0`);
- golden migration results;
- the generated matrix diff;
- the research record list with reviewers;
- the legacy disposition count;
- benchmark results;
- the list of rules left `DETECT_ONLY` due to gates, with gap IDs.

## 24. Handoff checklist
- [ ] P3 and P4 exit verified; D-04/D-05 recorded
- [ ] Research gates resolved or recorded
- [ ] Rule coverage test green
- [ ] Golden migrations 100 % match for in-scope pairs
- [ ] No review rule produces edits
- [ ] 68/68 legacy rules dispositioned
- [ ] Matrix regenerated, honest
- [ ] verification.md complete
- [ ] P6/P7 informed of ai-eligible rules and golden fixtures for runtime
