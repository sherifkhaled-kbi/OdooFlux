# Fragment I: original human-gated tasks and automated-review findings (orchestrator)

Each entry is PENDING_HUMAN_REVIEW unless it says RESOLVED. Nothing here records a human decision.

## ORIG-006-T025: peer review of research records
- **Original ID:** 006 T025 (REQ-EVD-001, REQ-EVD-006). Packet: specs/006-version-compatibility-rules/T025-review-packet.md. Backlog: KB-006-T025r.
- **Component:** Knowledge Base research records, version steps 14-15 to 18-19.
- **Review:** peer-review the research records and set `peer_reviewed` / `RESEARCHED` where complete.
- **Why:** evidence-only rules need human-checked research before any rule is promoted past DETECT_ONLY.
- **Evidence and tests available:** 200 evidence records, `tools/verify_evidence.py` (verbatim check at pinned SHAs), `knowledge validate` clean, coverage test.
- **Risk if not approved:** research stays at RESEARCH_SEEDED; no step can reach RESEARCHED or be called supported.
- **Reviewer:** Odoo core developer familiar with the version histories, able to read upstream source at the pinned SHAs.
- **Certification impact:** blocks any "supported path" claim (SC-005 of 010). Mandatory for production certification of any path.

## ORIG-006-T035-T044: golden expected trees
- **Original ID:** 006 T035, T044 (REQ-TST-003). Tech parts: T035-prov (done, PROVISIONAL). T044 fully deferred (KB-006-T044r). Cases: knowledge/golden_corpus/review/ (42 cases, all PENDING_INDEPENDENT_REVIEW).
- **Component:** golden corpus and `tests/golden_fixtures/17.0/kbi_demo/expected/18.0` (PROVISIONAL).
- **Review:** independently confirm each expected output is correct Odoo migration truth, including the `tree` to `list` change inside a Python `view_mode` and the `group_operator` to `aggregator` edit.
- **Why:** the expected trees were produced by the engine itself, so they test mechanics only and prove nothing about accuracy.
- **Evidence and tests available:** byte-exact, idempotence, SC-005 and label-guard tests; evidence records cited by the rules.
- **Risk if not approved:** wrong edits could be treated as truth; migration accuracy stays unverified.
- **Reviewer:** senior Odoo developer who has migrated custom addons across 17 to 18, not the author of the rules.
- **Certification impact:** mandatory for any accuracy claim. Without it, reports keep the PROVISIONAL label.

## ORIG-006-T059: quickstart verification
- **Original ID:** 006 T059. Tech part: T059-prov (PROVISIONAL record in verification.md). Residual: KB-006-T059r.
- **Review:** confirm the quickstart outputs are what a correct migration should produce.
- **Risk / impact:** same as ORIG-006-T035-T044; depends on it.

## ORIG-008-T029: RUNTIME_VALIDATED data
- **Original ID:** 008 T029 (REQ-VAL-004, REQ-EVD-006). Generator part T029-gen done. Data: KB-008-T029r, register WSF-001.
- **Review:** decide which golden migration and step a runtime run record may cover, then run it and record the result.
- **Why:** the 9 runtime tests that passed use synthetic fixtures; a record would overclaim.
- **Evidence:** Docker 29.7.2, odoo 17/18/19 and postgres:16 images cached; 9 runtime tests passed once (159 s); generator tests (13).
- **Risk:** no path can be RUNTIME_VALIDATED, so none can be called supported. Behavioural comparison for 17.0 sources needs a source image (no official image for 17.0 at odoo/docker master; the local `odoo:17.0` image provenance is unverified).
- **Reviewer:** engineer with Docker and Odoo runtime experience.
- **Certification impact:** mandatory for "supported" status.

## ORIG-007-T029-T031: live provider contract tests
- **Original ID:** 007 T029, T030, T031. Register WSC-AI-1.
- **Review:** run `ODOOFLUX_AI_TESTS=1` live contract tests with real keys and an owner-chosen model id for Anthropic and an OpenAI-compatible endpoint.
- **Evidence:** offline contract tests with recorded responses (84 contract tests, 10 live skipped).
- **Risk:** adapters untested against real services; catalog endpoints, credential variable names and `anthropic_version` were written from general knowledge and are unverified (WSC-AI-4).
- **Reviewer:** engineer with provider accounts and security awareness.
- **Certification impact:** AI features must not be certified for production until done.

## ORIG-009-T025: mockup parity
- **Original ID:** 009 T025. Register WSD-01. Automated part: `tests/unit/reporting/test_mockup_checklist.py` (5 known deviations).
- **Review:** compare the rendered terminal and HTML reports with docs/planning/REPORTING_AND_UX.md.
- **Reviewer:** product owner or UX reviewer.
- **Certification impact:** UX acceptance only; not a safety gate.

## ORIG-010-T023: maintainer release sign-off
- **Original ID:** 010 T023 (REQ-TST-005). Register WSG-01. Checklist: docs/planning/RELEASE_CHECKLIST.md (all sign-off cells PENDING_HUMAN_REVIEW).
- **Review:** the maintainer reviews evidence for each checklist row and signs.
- **Risk:** none technical; it is the production gate.
- **Reviewer:** project maintainer.
- **Certification impact:** production certification is blocked until signed.

## ORIG-010-T002-T014: benchmark budgets
- **Original ID:** 010 T002, T014 (REQ-PRF-001, REQ-PRF-004). Register WSG-02.
- **Review:** approve budgets (measured medians with 1.5x headroom; every `approved_by` is PENDING_HUMAN_REVIEW).
- **Evidence:** serial 13.3 s, parallel 3.8 s, incremental 2.5 s on the 300x30 corpus; P2-corpus analysis 6.8 s versus the 1.07 s P2 baseline (about 6x slower since knowledge rules run).
- **Risk:** the 6x slowdown is accepted only if a human accepts it.
- **Certification impact:** performance acceptance.

## ORIG-002-T010-T028: feature 002 residuals
- **Original ID:** 002 T010 (v14 fixture move, left in place), T028 (SC-002 not met), T011-T016 (DEFERRED_KB: KB-002-FIX, KB-002-T015). Register FHR-A-001.
- **Review:** accept the reconciliation (specs/002-test-foundation/reconciliation.md), including that legacy-CLI characterisation was not redone (the legacy script is now a launcher).
- **Reviewer:** test architect.
- **Certification impact:** low; coverage statement only.

## AR-R2-1: legacy `--ai-fix` and the kill switch (RESOLVED technically)
- **Source:** automated review R2, finding 1.
- **Finding:** `--ai-fix` (legacy whole-file Anthropic path) ignored `ODOOFLUX_AI_DISABLE_EXTERNAL` and the `--ai-disable-external` flag.
- **Resolution:** `resolve_ai` now refuses `--ai-fix` while the kill switch is on (tests `LegacyAiFixKillSwitchTests`, red first). The legacy path still has no data-category authorization and no catalog; it sends whole files with `--api-key`/`ANTHROPIC_API_KEY`.
- **Human review:** decide whether the legacy `--ai-fix` path stays, is gated by D-08 authorization, or is removed. Also `ai/providers/legacy_anthropic.py:21` hardcodes `CLAUDE_MODEL = "claude-sonnet-4-6"`.
- **Reviewer:** security reviewer. **Impact:** mandatory before certifying AI safeguards for the legacy flag.

## AR-R3-1: manifest-less directory reported as clean (RESOLVED in output; exit code open)
- **Source:** automated review R3, defect 1.
- **Resolution:** the legacy terminal no longer prints "Module looks clean" when `__manifest__.py` is absent; it says L3 could not run and nothing was verified (regression test `tests/regression/test_no_manifest_not_clean.py`).
- **Still open:** under the default legacy exit-code mapping such a run exits 0. The v1 mapping (`--exit-codes v1`) gives BLOCKED = 4 but breaks two existing tests (see WSD-04). Owner decision on the default mapping.
- **Impact:** mandatory decision before production, because exit code 0 can be read as success by CI.

## AR-R3-2: support-statement in an installed package (RESOLVED technically)
- **Source:** automated review R3, defects 2 and 3.
- **Resolution:** the command now refuses outside a source checkout (exit 2) instead of writing a statement without PROVISIONAL labels. It is a release-process command.
- **Human review:** confirm that is the intended scope, or ask for the statement to be generated from data that ships in the wheel.

## AR-R3-3: minor behaviour oddities (open, technical)
- A second `--fix` on an already fixed copy reports 25 open findings versus 24 after the first fix.
- Repeating a rollback reports "conflict" three times with exit 1 instead of "already rolled back".
- `kbi_demo` keeps `expected/` inside the module directory, so a whole-directory copy also scans it (documented; use a copy of the input only).
- `--api-key` deprecation warning is printed twice.
- **Reviewer:** engineer. **Impact:** low; none block certification, but the first two should be fixed before release.

## AR-R1-1: test harness `sys.path` ordering (open, technical)
- **Source:** automated review R1, finding 1. `tests/_support/p0.py:22-24` puts the repo `src` first, so `PYTHONPATH=<copy>/src` is ignored when tests run from the real repo. Mutation checks are valid only on a full repo copy (tests and src).
- **Impact:** false assurance for anyone using the PYTHONPATH recipe. Fix before relying on mutation testing in CI.

## AR-R1-2: weakest test (open, technical)
- `tests/integration/ai/test_ai_disabled.py:54` asserts through a mock that raises `AssertionError`; it would pass if the pipeline swallowed that exception. Kill switch and review_required-plus-fixer rules are caught only at integration or rules level, not unit level.

## AR-R2-2: evidence tool and evidence coverage (open, technical)
- `tools/verify_evidence.py` with no arguments checks nothing and prints "FAILURES 0"; run it with explicit file arguments or an EV range.
- EV-540 to EV-547 point at a directory (`addons`) and cannot be verified by the tool (report 404 for a directory location). Review these by hand.
- Only 26 of the IDs in EV-500..559 exist (the rest of the range was reserved, not used).
- Seven shared rules carry empty evidence by the documented waiver (`not_applicable_reason`, all DETECT_ONLY).
- Evidence quotes were not re-read against upstream by the reviewer; a human check of a sample is advised.
- **Reviewer:** Odoo developer. **Impact:** part of T025 certification.

## AR-R2-3: owner approvals recorded as assertions (informational)
- ARCHITECTURE_DECISIONS.md lines for ADR-011, ADR-017, ADR-018 and ADR-019 say "approved by the project owner". They record the owner's messages in this project; no tool can verify them. ADR-019 defaults for OD-2, OD-4, OD-5, OD-6, OD-7, OD-8 were assumed by the orchestrator, not stated by the owner, and need confirmation.
- **Reviewer:** project owner. **Impact:** confirms scope decisions.

## AR-STALE: stale planning documents (open, documentation)
- docs/planning/EXECUTIVE_SUMMARY.md still shows the original phase table, "No functional code was written" and 55 evidence records. It predates implementation and is superseded by FRAMEWORK_COMPLETION_REPORT.md and IMPLEMENTATION_STATUS.md.
- **Reviewer:** maintainer. **Impact:** documentation accuracy only.

## Stabilization round 2 (2026-11-07): items opened or changed
All PENDING_HUMAN_REVIEW unless marked RESOLVED. Nothing here records a human decision.

### AR-R4-1: legacy retire rows (WSE-001) partly resolved
- **Done (technical):** 10 pre-12.0 retire rows now gated to source version 12+ (reporting only); the retired `Page Attrs` row no longer double-reports next to `Attrs Attribute` or its knowledge rule (tests `test_legacy_precedence.py`).
- **Open decisions:** (a) retire rows whose claimed window is contradicted by the disposition (HTML Field 17, attachment 18, `_auto_init` 19, Editable Form 17) still fire; (b) pre-12 fixers (openerp rewrites) still run on 12+ runs; (c) base `Manifest Version` INFO stays OPEN after `--fix` (broad regex in `rules/shared/legacy_rules.py`), and a `Version Mismatch` WARNING appears when `--from-version` is not changed after a fix; decide whether it should fire post-fix.
- **Reviewer:** maintainer with Odoo migration experience.

### AR-R4-2: rollback idempotency (RESOLVED technically)
- Repeated rollback now reports "already rolled back" (exit 0); files matching neither backup nor fixed state still report a conflict and keep the user's bytes. Tests `tests/regression/test_fix_rollback_idempotency.py`. The earlier "25 vs 24" open-findings oddity was not a counting defect (expected new WARNING after the manifest edit).

### AR-R4-3: AI grants versus evidence_excerpt (owner direction applied; certification open)
- **Owner direction (recorded from the project owner's message in this session):** keep explicit per-category authorization including `source_python` and `evidence_excerpt`; never widen a grant silently; an unauthorized required excerpt is denied safely and the missing permission reported; D-08 unchanged; no real rule marked `ai_eligible` without sufficient evidence.
- **Implemented:** the denial now names the missing category (`authorization:missing=evidence_excerpt`); `Authorizer.missing()` never widens a grant (test `test_missing_names_only_the_uncovered_categories`). Behaviour was already deny-by-default; a request carries `evidence_excerpt` only when its rule has evidence records.
- **Open for certification:** whether any real rule may be marked `ai_eligible` (needs evidence of safe, correct escalation from a live-provider run); live provider tests (ORIG-007-T029-T031). Provider endpoints: `docs/reviews/automated/C-provider-config-check.md`.

### AR-R4-4: exit-code default (WSD-04) unchanged
- Not changed this round: the default mapping is a D-10 owner decision.

### AR-R5-1: rollback after a path written twice (RESOLVED technically; end-to-end proof pending)
- Round-2 review found that a path written twice in one run (deterministic promote, then an AI edit) made rollback raise `RuntimeError` and leave the file changed. Fixed by collapsing repeated plain writes to the first `before` and last `after` (`rollback._collapse_rewrites`, tests `tests/regression/test_rollback_double_write.py`). Proof is unit level; no end-to-end run with a real AI edit after promote was executed.
- **Still open (technical):** rename rollback unlinks the renamed path before writing the source (`rollback.py`), so a crash between the two leaves the module without the file and a misreported conflict. Make it write-then-unlink.

### AR-R5-2: pre-12.0 retire rows (decision)
- The 10 rows gated to source 12+ no longer report on 12+ runs, but `--fix` still rewrites them (openerp rewrites) with no reporter. Decide: gate the fixers too, or restore reporting. Reviewer: maintainer.

### AR-R5-3: shared AST immutability convention (informational)
- Memoised `nodes_of` relies on detectors never mutating the shared tree. Add a guard test or freeze the tree before adding more caches.
