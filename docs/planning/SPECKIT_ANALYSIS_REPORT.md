# Spec Kit Cross-Artifact Analysis Report

Run date: 2026-11-06. Scope: constitution 2.0.0, all planning documents in this directory, and
features `specs/001` to `specs/010`. This is the `/speckit-analyze` step applied across features.
It was read-only, except that the inconsistencies listed under "Resolved" were corrected in the
planning artefacts themselves (no application code). Checks were run with a scripted pass (links,
anchors, IDs, placeholders, checklist state, task fields, handoff sections, traceability) plus
manual review.

## 1. Automated checks

| Check | Result |
|---|---|
| Features with spec, plan, research, data-model, quickstart, tasks, requirements checklist | 10 / 10 |
| Features with `contracts/` | 8 / 10 (001 and 002 reuse shared contracts; no new interfaces) |
| `[NEEDS CLARIFICATION]` markers in specs | 0 |
| Template placeholders left (`ACTION REQUIRED`, `[FEATURE NAME]`, `[DATE]`, `$ARGUMENTS`, `[e.g.,`) | 0 |
| Requirement checklists fully checked (the `/speckit-implement` gate) | 10 / 10 (16 / 16 items each) |
| Plans with a Constitution Check against v2.0.0 | 10 / 10 |
| Tasks | 366 |
| Tasks without a `REQ-…` reference | 0 |
| Tasks without a measurable "Done when" criterion | 0 (47 were added during this analysis) |
| References to undefined `REQ-…` IDs | 0 |
| Test IDs | 196 unique; every `TST-<feature>-…` defined in its own feature. Two P0 tests are deliberately re-run by 003:T053 |
| Product requirements without FR / task / test | 0 / 0 / 0 (see [REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md)) |
| Handoffs with all 24 required sections | 10 / 10 |
| Vague terms in specs (robust, intuitive, user-friendly, appropriate, etc.) | 0 |
| Broken relative links / anchors | 0 after fixes, rechecked when the last documents were added |

## 2. Inconsistencies found and resolved

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| AN-01 | High | Research gap IDs G-R-14/15/16 defined twice with different meanings (004 research vs 008 research) | 008-side gaps renumbered G-R-21/22/23 in all 008 files, PHASE_07, VALIDATION, and SECURITY docs; canonical list in [PLANNING_GAPS_AND_ASSUMPTIONS.md §2](PLANNING_GAPS_AND_ASSUMPTIONS.md#2-research-gaps) |
| AN-02 | High | Exit codes conflicted: P0/P2 used 3 for tool error and blocked; P8 used 3 for rejected edits and 4 for blocked | Unified on the P8 table (0 ok, 1 threshold, 2 usage, 3 rejected edits, 4 blocked or tool error; precedence 4>3>1>0) in 001 spec/tasks, PHASE_00, and 003 `contracts/cli.md`/`recovery.md` |
| AN-03 | Medium | TARGET_ARCHITECTURE §4.4 status summary disagreed with the normative decision table (unavailable adapter vs `--require`) | Summary rewritten in the normative order; table in VALIDATION_AND_TEST_STRATEGY remains normative |
| AN-04 | Medium | `ValidationResult` lacked `coverage` and `reason`, which the status table needs; 008:T009 planned a contract change during P7 | Fields added to contract v1 in [architecture/CONTRACTS.md](architecture/CONTRACTS.md#validator); 003:T008 tests them; 008:T009 became a verification task |
| AN-05 | Medium | MIGRATION_MAP proposed `--rollback/--resume` flags, `--min-severity`, `--legacy-json`, not present in specs | Aligned to the normative 003 CLI contract (subcommands `rollback`/`resume`); renames marked as D-10 proposals with no task |
| AN-06 | Medium | P0 plan reported Principle II as PASS although P0 writes in place | Recorded as a justified deviation in 001 `plan.md` Complexity Tracking (resolved in P2 by REQ-SAF-007) |
| AN-07 | Medium | P5 entry criteria omitted decisions D-04/D-05 required by its handoff | Added to [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) |
| AN-08 | Low | `tools/` and `docs/changes/` introduced by tasks but absent from PROJECT_STRUCTURE | Added as "planned, not scaffolded" with owners |
| AN-09 | Low | 47 test-writing tasks had no explicit "Done when" | Standard red-phase criterion appended |
| AN-10 | Low | Wrong relative path (006 rule catalogue → matrix) and wrong anchor (007 → AI benchmarks) | Fixed |
| AN-11 | Low | Evidence register listed gaps only to G-R-12 and did not index EV-2xx/EV-3xx | Index and pointer to the canonical gap list added |
| AN-17 | Low | Handoff Dependencies sections listed soft data dependencies absent from the roadmap | Added to the roadmap as soft dependencies with degradation behaviour |
| AN-12 | Low | `docs/planning/phase-handoffs/.gitkeep` left after handoffs were written | Removed (the only scaffold file removed) |

## 3. Remaining items (non-blocking, recorded)

| ID | Item | Owner |
|---|---|---|
| AN-13 | Matrix seed catalogue and 006 rule catalogue word the 14→15 `t-esc` ceiling differently ("FIX_ENABLED after P7 check" vs "Group B, deferred to P7"). Same meaning. | P3: the matrix becomes generated from data (REQ-EVD-006), which removes the duplication |
| AN-14 | REQ-SEC-003 is assigned to P0/P6 but also enforced by 008–010 tasks | Intentional reinforcement; visible in the RTM |
| AN-15 | 22 of 68 legacy rules are `needs-research` ([MIGRATION_RULE_ENGINE.md](MIGRATION_RULE_ENGINE.md)) | P5 research tasks precede rule implementation |
| AN-16 | Legacy data-model line range cited as 37–73 in some places; the constants start at 32 | Cosmetic; MIGRATION_MAP uses 32–73 |

## 4. Constitution alignment (v2.0.0)

| Principle | Status across features |
|---|---|
| I Dependency-light core | Aligned. Optional dependencies (tree-sitter, lxml, Docker, AI SDKs, rich) appear only in adapter tasks and plans' Complexity Tracking; all are pending D-02/D-03/D-07/D-08 |
| II Safe, reversible | Aligned, with one justified P0 deviation (AN-06) |
| III Deterministic first | Aligned. AI is off by default and limited to eligible findings (007) |
| IV Honest reporting | Aligned. Re-scan-based fix status from P0; status table normative (008) |
| V Test-backed | Aligned. Every requirement has a test ID |
| VI Official evidence | Aligned. Rules require EV records; unresearched areas are research tasks or DETECT_ONLY. 55 evidence records, 23 gaps |
| VII Layered validation | Aligned. Status capping is tested (008) |
| VIII Business logic | Aligned. Review-required findings; behavioural scope disclosed (008/009) |
| IX Extensibility | Aligned. Registries and contract versioning (003); "adding a version" procedure (MIGRATION_RULE_ENGINE) |
| X Phase delivery | Aligned. Entry and exit criteria consistent between roadmap, plans, and handoffs |

## 5. Dependency check

The phase graph in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) is acyclic. Each
handoff's **Prerequisites** section matches the roadmap's hard edges (checked for all 10 handoffs).
The **Dependencies** sections also name soft data dependencies (P7 on P3 knowledge data, P8 on
P6 usage data, P6 on P4 parsers). These were not in the roadmap and have been added there as
"soft dependencies" with their degradation behaviour (AN-17). No hard dependency points to a later
phase, except for explicitly documented re-runs of earlier tests (003:T053).
