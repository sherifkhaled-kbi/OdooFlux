# Human review fragment: workstream G (feature 010 hardening and release readiness)

Register IDs are proposed (`WSG-nn`); the orchestrator assigns final IDs when consolidating. Nothing here records an
approval. Every item is `PENDING_HUMAN_REVIEW` under ADR-019. Reviewer qualifications are for a human reviewer.

## WSG-01: T023 release checklist sign-off

- Task / requirement: 010 T023, REQ-TST-005. Certification: PENDING_HUMAN_REVIEW. T023 stays unchecked.
- Component: `docs/planning/RELEASE_CHECKLIST.md` (T008, not written yet), `tests/unit/release/rtm_tools.py`.
- What to review: every checklist item with its evidence link, then sign. A sign-off needs the evidence for T020 to T022 and T024, which are open.
- Why: only a maintainer can certify a release. No agent writes a signer or marks an item `done`.
- Evidence and tests: RTM gate passes; benchmark PASS; secret scan 0 matches; support statement generated. Failure-injection suite not built.
- Risk if unapproved: no release; production certification stays blocked while any mandatory register item is open.
- Reviewer qualifications: project maintainer with release authority.
- Certification impact: blocks the framework release gate (FC-E2E), not the framework implementation.

## WSG-02: Budgets approver and headroom

- Task / requirement: 010 T002, REQ-PRF-001, REQ-PRF-004.
- Component: `tests/benchmarks/budgets.json`, `baseline.json`, `REFERENCE_MACHINE.md`.
- What to review: the headroom factor (1.5 on wall time and peak RSS, 1.0 on files parsed), the reference machine, and whether CI uses the same runner class. `approved_by` is `PENDING_HUMAN_REVIEW` on every row.
- Why: budgets come from measured medians of this machine, not from the P2 baseline: the P2 baseline (1.07 s) used a different corpus and predates the knowledge rules, and analysis is still about 6 times slower on that corpus (10.9 s before T014, 6.8 s after). Whether that is acceptable is a product decision.
- Evidence and tests: `tests/benchmarks/test_run_benchmarks.py`; 300-module run PASS; `results/profile-summary-2026-11-07.md`.
- Risk: budgets set too loose hide regressions; too tight fail on other runners.
- Reviewer qualifications: maintainer who owns CI and performance goals.
- Certification impact: blocks declaring OBJ-007 scale requirement certified.

## WSG-03: D-10 removal window for `--api-key`

- Task / requirement: 010 T017, T019, REQ-AI-008, FR-008.
- Component: `src/odooflux/cli/deprecations.py` (`API_KEY_REMOVED_IN = "0.3.0"`), `cli/main.py`.
- What to review: D-10 is not recorded as decided in the ADRs; the spec assumes one minor release. Confirm the window and the release that removes the option. Today (0.2.0) the option still warns. Removal means bumping `odooflux.__version__` to 0.3.0.
- Why: removing a CLI option breaks scripts; the owner chooses the release.
- Evidence and tests: `tests/unit/cli/test_api_key_removed.py` (exit 2, no echo in all argument forms, simulated version).
- Risk if unapproved: the credential-leak risk stays open until the version is bumped.
- Reviewer qualifications: project owner; a security reviewer for the no-echo behaviour.
- Certification impact: blocks FR-008 being met by default behaviour.

## WSG-04: Support statement

- Task / requirement: 010 T006, T007, REQ-VER-003, REQ-EVD-006, SC-005; FC A-9.
- Component: `src/odooflux/cli/support_statement.py`, `docs/planning/SUPPORT_STATEMENT.md` (generated).
- What to review: the rule is unchanged: supported only when every step is `RULES_TESTED` and the target is `RUNTIME_VALIDATED`. No path is supported today; 17.0 to 18.0 is `experimental`, labelled PROVISIONAL. ADR-019 default OD-7 expected the provisional path to be called supported; the SC-005 rule forbids it while the matrix shows no `RULES_TESTED` step and no runtime run. Confirm this reading, and the definition of `experimental` (research and runnable rules on every step).
- Evidence and tests: `tests/unit/release/test_support_statement.py`; the committed file matches the generator.
- Risk: users may read `experimental` as endorsement; the section "Not yet supported (knowledge pending)" lists every unsupported path and its backlog IDs.
- Reviewer qualifications: maintainer who owns the support policy.
- Certification impact: none on mechanics; blocks any public support claim.

## WSG-05: RTM gaps and gate semantics

- Task / requirement: 010 T003 to T005, A-8.
- Component: `docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md` (sections "Release gate data", "Verification records"), `tests/unit/release/rtm_tools.py`.
- What to review: (1) "mapped passing test" means a test file cites the TST id or the REQ id; whether it passes is the suite result, not proved per requirement. (2) Six requirements carry a partial `DEFERRED_KB` row (REQ-TST-003, REQ-TST-002, REQ-EVD-001, REQ-EVD-006, REQ-VAL-004, REQ-VER-003) with their KB-* ids. (3) Requirements whose mapped tests are all opt-in or skippable are printed as warnings (use `--strict` to fail them). (4) No verification-record rows exist.
- Why: the gate must not be papered over; gaps stay visible.
- Evidence: `python tests/unit/release/rtm_tools.py`; F-WALK-1 had no citing test and now has `tests/regression/test_walk_findings.py`.
- Reviewer qualifications: maintainer or QA lead.
- Certification impact: blocks SC-001 sign-off if the reading in (1) is rejected.

## WSG-06: Contract changes in P9

- Audit log path is `log/audit.jsonl` (TST-003-030 limits analysis runs to `state.json` and `log/`); action `module_blocked` added; the last line of a chain is not tamper-evident.
- Parallel mode covers analysis and dry run only; fix mode stays serial; it needs `fork` (Linux, macOS).
- `--incremental` serves analysis and dry run only; it never serves a fix run.
- Reviewer: maintainer of the orchestrator. Certification impact: none unless rejected.

## Open technical items (not human review)

T008 release checklist, T020/T021 failure injection, T022 release gates, T024 quickstart record are not done.
