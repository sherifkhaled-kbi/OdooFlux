# Framework Completion Report

Date: 2026-11-07. Basis: ADR-019 (framework-first, non-blocking human review), [FRAMEWORK_COMPLETION_PLAN.md](FRAMEWORK_COMPLETION_PLAN.md), [KNOWLEDGE_BASE_BACKLOG.md](KNOWLEDGE_BASE_BACKLOG.md). Nothing is committed or pushed.

**Headline:** the framework's technical work is implemented and passes its automated gates. **No human review or certification has occurred, and production certification is not granted.** All migration expected outputs rest on a PROVISIONAL corpus and prove framework mechanics, not migration accuracy.

## 1. Implementation completion

| Feature | Technical state | Open items |
|---|---|---|
| 001 Safety, 003 Core, 004 Sources, 005 Transformations | IMPLEMENTED, VERIFIED (all tasks `[X]`) | none |
| 002 Test foundation | 20 of 28 `[X]` (reconciled, see specs/002-test-foundation/reconciliation.md) | T011-T016 DEFERRED_KB; T010 (v14 fixture left in place), T028 (SC-002 seven fixtures not met, by design) |
| 006 Version rules | rules, run parameters, DETECT_ONLY families, view index, wiring (T079-T091) done | T025, T035, T044, T059, T084, T092 pending human review |
| 007 AI assistance (incl. D-08 scope) | 47 of 50 `[X]`; offline-verified with fake provider and recorded transport | T029-T031 need live provider runs (pending human review) |
| 008 Runtime/behavioural | all `[X]` except T029; T029-gen done | T029-data pending (needs a recorded run decision) |
| 009 Reporting | 25 of 26 `[X]` | T025 mockup parity pending human review |
| 010 Hardening | 26 of 27 `[X]` (T001-T022, T024-T027; T008 and T022 completed by the orchestrator) | T023 maintainer sign-off pending |

Cross-cutting work added in this phase:
- Knowledge rules (91) now execute in the real `migrate` pipeline, per step, with overlap dedup against legacy rules. Before this, only legacy rules ran.
- Planner `target` and the dependency scanner reach the report; the version-prefix rule is opt-in (`--enable-rule`) and detect-only.
- Wheel carries every runtime asset (246 JSON files); clean-venv install verified once.
- `--dry-run --diff` computes edits in memory; its patch equals the write-mode result.
- Run provisional label (`--provisional-corpus` or a `PROVISIONAL.md` marker) shown in every renderer.
- Process-pool analysis (`--jobs`), incremental index (`--incremental`), audit log with hash chain, canary-secret scan, `--api-key` removal mechanism, failure-injection suite (defect F-INJ-1 found and fixed in promote restore).
- Review fixes: legacy `--ai-fix` now honours the external-transmission kill switch; a manifest-less directory is no longer reported "clean"; `support-statement` refuses outside a source checkout; a runtime-runs null guard.

## 2. Automated test and runtime validation

| Check | Result |
|---|---|
| Full default suite | 1734 tests, OK, 34 opt-in skips, about 42 s (round 2) |
| `knowledge validate` | records=200 rules=91 errors=0 warnings=0 |
| `knowledge matrix --check`, `support-statement --check` | up to date |
| RTM completeness (`rtm_tools.py`) | PASS (six requirements carry partial DEFERRED_KB rows) |
| Benchmarks (opt-in, run once) | PASS; serial 13.3 s, parallel 3.8 s, incremental 2.5 s (300x30 corpus); report digests identical across modes |
| Wheel build and asset test | 246 JSON assets; install test (opt-in) passed once |
| Runtime suite (opt-in, Docker 29.7.2, cached images) | 9 tests passed once, 159 s, no leaked containers. Fixtures are synthetic; no run record added |
| Failure injection | 13 injection tests OK |
| Live AI provider tests | **not run** (no keys); offline contract tests only |
| Independent automated review | R1 spec conformance, R2 safety/provenance, R3 end-to-end from wheel: reports in docs/reviews/automated/ |

R1 ran eight mutations on full repo copies; all failed a test as expected. Review reports are automated and are not human approval.

## 3. Outstanding technical issues

- **Performance:** (round 2: ~5% gained, see D-performance.md) analysis is about 6x slower than the P2 baseline on the P2 corpus (6.8 s versus 1.07 s) since knowledge rules run. Budgets are met but unapproved.
- **Legacy and knowledge rules overlap:** 35 legacy rows marked `retire` still fire; some fire outside their real version window and win over the better-evidenced knowledge rules (WSE-001). `legacy_disposition.json` indices do not map to the tables.
- **Exit code mapping:** the default (legacy) mapping exits 0 for a manifest-less or L3-unavailable module; `--exit-codes v1` gives 4 but breaks two existing tests (WSD-04).
- **Minor:** second `--fix` reports 25 open findings versus 24; repeated rollback prints "conflict"; `--api-key` warning printed twice; `tests/_support/p0.py` puts the repo `src` first on `sys.path` (mutation checks only valid on full repo copies); one weak test (`test_ai_disabled.py:54`).
- **AI:** no knowledge rule is `ai_eligible`, so a real run escalates nothing; catalog endpoints and `anthropic_version` unverified; legacy `--ai-fix` hardcodes a model name and has no data-category authorization.
- **Knowledge gaps (deferred):** see the KB backlog. 234 of 236 removed modules have no evidenced successor; `acquirer_id` field and table renames are unmapped; research gaps G-R-01, 04, 18, 21, 22 are open.
- **Documentation:** EXECUTIVE_SUMMARY.md is stale (AR-STALE).
- **Leftovers:** scratch directories under /tmp from review agents; run state under ~/.cache/odooflux/runs.

### Stabilization round 2 (bounded agents A, B1, C, D; ledger in the session)
- A: 10 pre-12.0 retire rows gated to source 12+; retired `Page Attrs` no longer double-reports. B1: repeated rollback now "already rolled back" (exit 0), conflicts still detected. C: AI escalation wiring verified offline (5 tests), provider config checked against official docs (docs/reviews/automated/C-provider-config-check.md), D-08 unchanged, denial names the missing category. D: two behaviour-preserving optimisations, about 5% (report identical); 2x needs a design change. B2 (exit-code default) deliberately unchanged. Register items AR-R4-1..4.

## 4. Final human review register

[docs/reviews/FINAL_HUMAN_REVIEW_REGISTER.md](../reviews/FINAL_HUMAN_REVIEW_REGISTER.md) (fragments in docs/reviews/fragments/).

## 5. Production certification readiness

**Status: NOT READY, certification not granted.** Technical gates pass; human certification is outstanding.

Blocking items (mandatory in the register):
1. T025 research peer review and T035/T044/T059 golden review. Until then every 17.0 to 18.0 result is PROVISIONAL.
2. 008 T029 data: no path is `RUNTIME_VALIDATED`, so the support statement lists **0 supported**, 16 experimental, 12 unsupported of 28 paths.
3. 010 T023 maintainer sign-off and budget approval.
4. AI: live provider tests not run; data-authorization policy and catalog sign-off; legacy `--ai-fix` decision.
5. Exit-code default decision (WSD-04).

What may be said today: the framework runs a migration end-to-end from an installed wheel, applies detect-only and evidenced fix rules safely with backup, rollback and resume, reports unsupported cases explicitly, and keeps AI off unless authorized. What may **not** be said: that migrations are accurate, that any path is supported, or that behaviour is equivalent after migration (source-side runtime validation is unavailable for 17.0).

## 6. Next steps

1. A human works through the register (start with group A: certification gates).
2. After T025 and T035, record a real runtime run for the validation path and regenerate the matrix and support statement.
3. Knowledge Base expansion proceeds from the backlog, independently of framework files.
