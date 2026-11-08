# Phase Handoff — P3 Official Source Intelligence

## 1. Phase ID
P3. Spec Kit feature: [specs/004-official-source-intelligence](../../../specs/004-official-source-intelligence/)

## 2. Phase title
Official Source Intelligence: evidence registry, version knowledge base, refresh workflow, and generated matrix.

## 3. Objective
Make official evidence a machine-enforced precondition for every migration rule. Deliver:
- validated JSON knowledge data (versions 12.0–19.0, pinned revisions, allow-list, evidence,
  step research, gaps, rule-metadata schema);
- loader enforcement (no evidence → no rule; weak evidence → detect-only);
- an offline refresh tool;
- a deterministic Version Compatibility Matrix generator;
- migration of all planning seed evidence (EV-001…EV-015, EV-101…EV-125, EV-201…EV-212) and
  gaps (G-R-01…G-R-19).

## 4. Requirements covered
REQ-EVD-001, REQ-EVD-002, REQ-EVD-003, REQ-EVD-004, REQ-EVD-005, REQ-EVD-006, REQ-VER-001
(data), REQ-VER-005 (procedure documentation), REQ-ARC-003. See
[spec.md](../../../specs/004-official-source-intelligence/spec.md) FR-001…FR-010.

## 5. Repository context
- Package `src/odooflux/` exists after P2: contracts in `core/contracts/`, rule loader skeleton
  in `rules/shared/loader.py`, CLI entry in `cli/`.
- Planning evidence:
  [research/OFFICIAL_EVIDENCE_REGISTER.md](../research/OFFICIAL_EVIDENCE_REGISTER.md) and
  [specs/004…/research.md](../../../specs/004-official-source-intelligence/research.md).
- Policy: [OFFICIAL_SOURCES_STRATEGY.md](../OFFICIAL_SOURCES_STRATEGY.md).
- Current matrix: [VERSION_COMPATIBILITY_MATRIX.md](../VERSION_COMPATIBILITY_MATRIX.md) (hand-written; becomes generated).
- Legacy `odooflux.py` is not involved.

## 6. Prerequisites
- P2 exit criteria met ([IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#p2--core-architecture)).
- Data drafting (T013, T017, T018) may begin after P1 exit; validation needs T006/T009.
- `git` available locally; network only for maintainers cloning official repositories.

## 7. Dependencies
- Upstream: P2 (code), P1 (data drafting).
- Downstream: P5 (rules need evidence enforcement and the registry), P6 (evidence retrieval for
  prompts), P7 (sets `VERIFIED` via `runtime_test_ref`).

## 8. Expected files and components
As listed in [plan.md §Source Code](../../../specs/004-official-source-intelligence/plan.md#source-code-repository-root):
- `src/odooflux/knowledge/{__init__,validator,refresh,matrix,seed_migration}.py`
- `src/odooflux/knowledge/{schemas,official_sources,evidence,compatibility}/**`
- `src/odooflux/knowledge/gaps.json`
- `src/odooflux/cli/knowledge.py`
- `src/odooflux/rules/shared/loader.py` (extension)
- tests under `tests/{unit,integration,golden_fixtures,benchmarks}/knowledge/`
- `docs/planning/research/RESEARCH_PROCEDURE.md`
- generated `docs/planning/VERSION_COMPATIBILITY_MATRIX.md`

## 9. Interfaces and contracts
- Data shapes: [data-model.md](../../../specs/004-official-source-intelligence/data-model.md).
- CLI: [contracts/knowledge-cli.md](../../../specs/004-official-source-intelligence/contracts/knowledge-cli.md).
- `OdooVersion`, `Rule`: [architecture/CONTRACTS.md](../architecture/CONTRACTS.md).

## 10. Official evidence requirements
- Every record cites an allow-listed URL and an immutable revision (40-hex SHA or catalogued tag).
- Migrated seed records keep status `DOCUMENTED_NOT_TESTED`. No record may be set `VERIFIED` in this phase.
- No new Odoo claims are required in this phase. Any new claim follows the research workflow and needs peer review.

## 11. Detailed implementation tasks
[specs/004-official-source-intelligence/tasks.md](../../../specs/004-official-source-intelligence/tasks.md),
T001–T026. Execute in the order given in its "Dependencies & Execution Order" section.

## 12. Acceptance criteria
SC-001…SC-006 in [spec.md](../../../specs/004-official-source-intelligence/spec.md#success-criteria-mandatory),
and the roadmap exit:
1. Schema validator and allow-list enforced.
2. Registry 12.0–19.0 present with status.
3. All seed records migrated.
4. Matrix generated from data.
5. Refresh demonstrated on two SHAs.
6. Gaps recorded as data.

## 13. Unit tests
TST-004-001 (schema checker), TST-004-002 (evidence validation), TST-004-003 (rule evidence and
maturity cap), TST-004-005 (registry), TST-004-006 (seed reconciliation), TST-004-007 (seed
migration idempotence), TST-004-009 (matrix).

## 14. Integration tests
TST-004-004 (validate CLI), TST-004-008 (refresh against local fixture git repositories),
TST-004-010 (committed matrix check).

## 15. Runtime tests where applicable
None. Runtime confirmation of evidence happens in P7.

## 16. Negative test cases
- Non-allow-listed URL.
- Branch-name revision.
- Duplicate ID.
- Unknown status.
- Rule without evidence.
- Unknown evidence ID.
- UNVERIFIED evidence on a FIX_ENABLED rule (capped).
- Duplicate version major.
- `SUPPORTED` version without preconditions.
- Matrix over-claim.
- Refresh with a missing clone (`unavailable` ≠ `missing`).

## 17. Security requirements
- The refresh tool runs `git` with fixed arguments (no shell, no user-controlled refspecs
  passed to a shell).
- No network access from core tests.
- Knowledge files contain no secrets.

## 18. Performance requirements
Full validation < 5 s (TST-004-011). Refresh of all records < 60 s with local clones.

## 19. Backward compatibility
- Legacy `odooflux.py` is untouched.
- The P2 rule loader keeps working for rules without evidence only in the test fixtures that
  P2 used. Those fixtures must be updated to cite evidence or marked as shared hygiene rules.

## 20. Prohibited changes
- No migration rules (P5).
- No edits to the legacy script.
- No third-party dependencies (YAML, `jsonschema`) in core.
- Do not set any evidence `VERIFIED`.
- Do not hand-edit the generated matrix after T023.
- Do not cite unofficial sources.

## 21. Definition of Done
- All tasks T001–T026 checked.
- All TST-004-* passing in CI.
- `odooflux knowledge validate` reports errors=0.
- `matrix --check` passes.
- `verification.md` filled.
- Roadmap exit criteria met.
- PR reviewed against the constitution check in plan.md.

## 22. Implementation agent instructions
1. Point `.specify/feature.json` to `specs/004-official-source-intelligence` (`{"feature_directory": "specs/004-official-source-intelligence"}`).
2. Read spec.md, plan.md, research.md, data-model.md, contracts/, and tasks.md in that order.
3. Implement with `/speckit-implement` (do not redesign; stop and ask on ambiguity per [IMPLEMENTATION_AGENT_GUIDE.md](../IMPLEMENTATION_AGENT_GUIDE.md)).
4. Write tests first; mark tasks `[X]` only when their "Done when" criterion is shown.
5. Do not change files outside the paths in §8 except to fix P2 fixtures as noted in §19.

## 23. Expected verification evidence
`specs/004-official-source-intelligence/verification.md` containing:
- the commit SHA;
- the full test run summary;
- `knowledge validate` output;
- `matrix --check` output;
- the refresh dry-run report on two official SHAs;
- the seed reconciliation count (52 EV, 19 gaps).

## 24. Handoff checklist
- [ ] P2 exit verified and recorded
- [ ] feature.json points at feature 004
- [ ] Tests written first and observed failing
- [ ] All TST-004-001…011 passing
- [ ] Seed reconciliation: 52 evidence records, 19 gaps
- [ ] No record `VERIFIED`; no unofficial URL
- [ ] Matrix generated and `--check` in CI
- [ ] RESEARCH_PROCEDURE.md peer-checked
- [ ] verification.md complete
- [ ] Next phase (P5) informed of registry/loader API
