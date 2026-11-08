# R1 spec-conformance review (automated, independent; not a human approval)

Scope: sampled [X] tasks of 002, 006 (T079-T091, T035-prov, T059-prov), 007, 008 (T029-gen), 009, 010 against Done-when, tests and contracts.

## Findings (by severity)
1. MEDIUM - Harness defeats the stated mutation method. `tests/_support/p0.py:22-24` rewrites `sys.path` to put the repo's own `src` first, so `PYTHONPATH=<copy>/src` is ignored when tests run from the real repo. A mutated copy of only `src` is silently NOT exercised (my first 5 mutations all "passed" for that reason). Mutations are valid only on a full repo copy (tests plus src). Not a product defect, but any reviewer using the PYTHONPATH recipe gets false assurance.
2. LOW-MEDIUM - 010 T002 is `[X]` but its Done-when needs "an approver". `tests/benchmarks/budgets.json` has `approved_by: "PENDING_HUMAN_REVIEW"` on every metric (lines 4-64; WSG-02). Honest, and no approval is faked, but under ADR-019 item 3 this should be split into a technical [X] part and an unchecked certification part. Same shape for 010 T014 (budgets "met", but about 6x the P2 figure, per tasks.md:51 note).
3. LOW - 010 T011/T014/T027, 008 runtime fixtures: the real checks are opt-in (`ODOOFLUX_BENCH=1`, `ODOOFLUX_PACKAGING_INSTALL=1`, `ODOOFLUX_RUNTIME_TESTS=1`). Default suite only runs logic tests. Evidence is recorded as "ran once" in `tests/benchmarks/results/2026-11-07-c9914e6.json`, `docs/reviews/fragments/ws-b-human-review.md:24`, `specs/008*/quickstart.md`. Claims are labelled as such; the results are not reproducible by the default suite.
4. LOW - `tests/integration/ai/test_ai_disabled.py:54` (never-constructed gateway) only asserts via a mock `AssertionError("gateway built")`. It would pass if the pipeline swallowed that exception. Not mutation-tested.
5. LOW - `src/odooflux/knowledge/runtime_runs.py:~60` `valid_runs` does `kb.runtime_runs.get(...)` after `(kb.runtime_runs or {})`; if `runtime_runs` is None it raises AttributeError. The loader likely always supplies a dict, and no test covers None.
6. INFO - `tests/integration/hardening/test_failure_injection.py:142` can `skipTest` if a fixture promotes fewer than k files. Currently the suite runs without a skip for this, but a fixture change could silently reduce coverage.

## Verified OK
- Unchecked as required: 010 T023, 006 T025/T035/T044/T059, 008 T029, 009 T025, 007 T029-T031. Each human-gated one carries a "Certification: PENDING_HUMAN_REVIEW (FHR-/WSG- id)" line. 006 T035-prov and T059-prov follow ADR-019 item 3. No [X] task marks a human-review requirement satisfied (grep of [X] lines for approve/sign-off/peer-review found only T002 and the "PROVISIONAL, not approved" T019).
- 008 T029-gen: `runtime_runs.py`, schema, shipped-empty `compatibility/runtime_runs.json` exist. 13 tests cover absent, failing, later failure, malformed, no source image and a hand-edited cell refused (`OverclaimError`). Implementation matches the claim (only a valid PASS record marks).
- 006 T079-T091: files exist; tests drive the real CLI and pipeline (not bind-only); SC-005 is enforced twice (loader rejects review_required plus fixer, pipeline fixer only for FIX_ENABLED).
- 010 T015-T020, T025-T027: audit chain, secret scan, failure injection and wheel assets tests assert real outcomes. `test_release_gates.py` fails on skipped or empty gates. Wheel install was run once and recorded.
- 009 T026 quickstart results table is recorded, with non-run human items listed explicitly. Note: 009 has no `verification.md`; results live in `quickstart.md:11`.
- 002: harness tests, sensitivity test (T021, guards against vacuous comparison) and the opt-in runtime placeholder (run with the flag; recorded in verification.md:17) are real.
- A scan of all test functions without an assert-like token found 21. All I opened delegate to asserting helpers (`_blocked_clean`, `_gate`, schema-checker helpers); no always-true asserts found (`assertTrue(True)` grep: none).

## Mutation spot-check (full repo copies in /tmp, mutation applied there; all FAILED as desired)
1. audit_log `verify_chain` prev_hash check disabled -> `test_audit_log` 1 failure.
2. gateway kill switch disabled (`if False and ...`) -> unit/ai: 123 OK (NOT caught at unit level); integration/ai 4 failures (caught only by integration `test_kill_switch` and others).
3. runtime_runs `_latest` max->min -> 1 failure (later-failure test).
4. knowledge_rules: every rule gets a fixer (DETECT_ONLY would edit) -> `test_knowledge_rules_pipeline` 1 failure.
5. output_paths `_inside` check disabled -> 6 failures and 1 error.
6. loader review_required plus fixer allowed -> unit/rules 2 failures (the `unit` glob alone did not catch it).
7. L3 integrity `missing_group` suppressed -> 1 failure.
8. incremental tool-version digest constant -> 1 failure.
Behaviours lacking a failing test at the lowest level: kill switch (only integration; unit gateway tests do not assert it); ai-disabled "never construct gateway" (finding 4).

## Not verified (limits)
Did not run full suite or opt-in suites. Sampled about 4 tasks per feature; did not re-read every contract line in specs/*/contracts. 007 sampled lightly (T023/T025/T035/T044 tasks read; gateway and kill switch mutation-tested only).
