# Final human review register

**Date:** 2026-11-07
**Source:** consolidated from `docs/reviews/fragments/ws-a` to `ws-i` under ADR-019 (`docs/planning/ARCHITECTURE_DECISIONS.md`).

## 1. Purpose and rules

This register collects every item that needs a human review before production certification. It records what is pending, why, and what evidence exists. It does not record any approval.

- Agents cannot approve anything in this register. Only a named human reviewer can record a decision, and only here.
- Every item's Decision field is `PENDING (human)`. Reviewer name and review date are empty.
- Automated checks and tests are evidence for a reviewer. They do not replace review.
- `PENDING_HUMAN_REVIEW` is not a failure, not an approval, and not certification (ADR-019 rule 2).
- Production certification stays blocked while any mandatory item is open (ADR-019 rule 6). Framework implementation may be declared complete without it.

**Work-state vocabulary (ADR-019, rule 1):**

1. `IMPLEMENTED`: technical work done.
2. `VERIFIED`: required automated checks passed.
3. `PENDING_HUMAN_REVIEW`: technical work and available automation done; human sign-off outstanding.
4. `BLOCKED_TECHNICAL`: a genuine technical dependency.
5. `DEFERRED_KB`: Knowledge Base expansion postponed, backlog ID required.

**Columns used in this register:**

- **Mandatory for production certification:** `Yes` means the fragment states production certification is blocked while open (or ADR-019 rule 6 applies). `No` means the fragment states no production certification impact. `Decision` means the fragment blocks a narrower claim, or leaves the blocking status to the owner or to a human; a human must decide. These values are the consolidator's reading of the fragment text, not approvals.
- **State:** `PENDING_HUMAN_REVIEW`; `RESOLVED-technically-review-wanted` (technical fix in place, a human review point remains); `OPEN-technical` (technical work or a finding still open, no human sign-off needed to close it).

## 2. Summary table

| ID | Original task/requirement | Component | Mandatory | State | Source |
|---|---|---|---|---|---|
| **A. Certification gates** | | | | | |
| ORIG-006-T025 | 006 T025 (REQ-EVD-001, REQ-EVD-006) | KB research records 14-15 to 18-19 | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-006-T035-T044 | 006 T035, T044 (REQ-TST-003) | Golden expected trees, 17.0 to 18.0 | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-006-T059 | 006 T059 | Quickstart verification | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-008-T029 | 008 T029 (REQ-VAL-004, REQ-EVD-006) | RUNTIME_VALIDATED data | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-007-T029-T031 | 007 T029, T030, T031 | Live AI provider contract tests | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-009-T025 | 009 T025 | Mockup parity (terminal and HTML) | No | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-010-T023 | 010 T023 (REQ-TST-005) | Maintainer release sign-off | Yes | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-010-T002-T014 | 010 T002, T014 (REQ-PRF-001, REQ-PRF-004) | Benchmark budgets | Decision | PENDING_HUMAN_REVIEW | ws-i |
| ORIG-002-T010-T028 | 002 T010, T028, T011-T016 | Feature 002 residuals | No | PENDING_HUMAN_REVIEW | ws-i |
| WSG-01 | 010 T023 (REQ-TST-005) | RELEASE_CHECKLIST.md sign-off | Yes | PENDING_HUMAN_REVIEW | ws-g |
| **B. Safety and security decisions** | | | | | |
| WSC-AI-1 | 007 T029, T041, T032; REQ-AI-001, FR-015 | AI providers, live contract tests | Yes | PENDING_HUMAN_REVIEW | ws-c |
| WSC-AI-2 | 007 T036, T037, T043, T044; FR-019, FR-020, ADR-017 | AI data-authorization policy | Yes | PENDING_HUMAN_REVIEW | ws-c |
| WSC-AI-3 | 007 T016, T024, T037, T040, T046; REQ-SEC-004, REQ-AI-008 | AI prompt injection and secrets | Decision | PENDING_HUMAN_REVIEW | ws-c |
| WSC-AI-4 | 007 T035, T042, T047; FR-018, ADR-017 | AI catalog, models, prices, endpoints | No | PENDING_HUMAN_REVIEW | ws-c |
| WSC-AI-5 | 007 T012, T026, T034; FR-003, FR-013, REQ-AI-006 | AI items surfaced in implementation | No | OPEN-technical | ws-c |
| WSD-04 | 009 T016; FR-006, REQ-REP-005, SC-005 | Exit-code default (D-10) | Decision | PENDING_HUMAN_REVIEW | ws-d |
| WSD-06 | 009 T020, T021, T022; REQ-REP-003, REQ-SEC-004 | Offline HTML and untrusted content | Decision | PENDING_HUMAN_REVIEW | ws-d |
| WSG-03 | 010 T017, T019; REQ-AI-008, FR-008 | D-10 removal window for `--api-key` | Decision | PENDING_HUMAN_REVIEW | ws-g |
| WSH-T020 | 010 T020, T021; REQ-SAF-005 | Failure-injection fix (F-INJ-1) | Decision | PENDING_HUMAN_REVIEW | ws-h |
| **C. Data and knowledge decisions** | | | | | |
| FHR-A-001 | 002 T010, T017, T019, T020, T028; KB-002-FIX, KB-002-T015 | 002 reconciliation scope (A-11) | No | PENDING_HUMAN_REVIEW | ws-a |
| FHR-A-002 | 006 T035 | PROVISIONAL expected tree and report, 17.0 to 18.0 | Yes | PENDING_HUMAN_REVIEW | ws-a |
| FHR-A-003 | 006 T059 | PROVISIONAL quickstart record | Decision | PENDING_HUMAN_REVIEW | ws-a |
| FHR-A-004 | ADR-019 rule 4 | Provisional corpus labelling guard | No | PENDING_HUMAN_REVIEW | ws-a |
| FHR-A-005 | 002 T026 | Rule coverage report scope | No | PENDING_HUMAN_REVIEW | ws-a |
| WSE-001 | 006 T086, T089, T092; FR-017, SC-005 | Legacy and knowledge rules overlap | Decision | PENDING_HUMAN_REVIEW | ws-e |
| WSE-002 | 006 T091; T035, T059; ADR-019 rule 4 | Regenerated PROVISIONAL expected output | Yes | PENDING_HUMAN_REVIEW | ws-e |
| WSF-001 | 008 T029; REQ-VAL-004, REQ-EVD-006 | Runtime run records, RUNTIME_VALIDATED | Yes | PENDING_HUMAN_REVIEW | ws-f |
| WSF-002 | ADR-019 rule 4; 009 US3 | Provisional label rule and report | No | PENDING_HUMAN_REVIEW | ws-f |
| WSG-04 | 010 T006, T007; REQ-VER-003, REQ-EVD-006, SC-005 | Support statement | Decision | PENDING_HUMAN_REVIEW | ws-g |
| WSG-05 | 010 T003 to T005, A-8 | RTM gaps and gate semantics | Decision | PENDING_HUMAN_REVIEW | ws-g |
| **D. Product, UX, packaging and performance decisions** | | | | | |
| WSB-001 | 006 T084; FR-019, REQ-MAN-002, OD-4 | REQ-MAN-002 wording, version-prefix opt-out | No | PENDING_HUMAN_REVIEW | ws-b |
| WSB-002 | 010 T025-T027; FC A-10, OD-5 | Wheel contents and size | No | PENDING_HUMAN_REVIEW | ws-b |
| WSB-003 | 006 T082; FR-020, REQ-DEP-001, FR-022 | Dependency scanner default on | No | PENDING_HUMAN_REVIEW | ws-b |
| WSB-004 | 006 T080; FR-017, FR-019 | CLI option `--enable-rule` | No | PENDING_HUMAN_REVIEW | ws-b |
| WSD-01 | 009 T025; REQ-REP-002, REQ-REP-006 | Mockup parity | No | PENDING_HUMAN_REVIEW | ws-d |
| WSD-02 | 009 T012, T015; REQ-REP-004, SC-001 | SARIF consumer acceptance | No | PENDING_HUMAN_REVIEW | ws-d |
| WSD-03 | 009 T007, T010, T011; REQ-REP-002, F-REP-2 | Terminal rendering on real terminals | No | PENDING_HUMAN_REVIEW | ws-d |
| WSD-05 | 009 T019; REQ-REP-004, SC-003 | Diff export limits (dry run) | No | RESOLVED-technically-review-wanted | ws-d, ws-f |
| WSD-07 | 009 T008; FR-007, REQ-BIZ-003; ADR-019 rule 4 | Verification wording and provisional label | Decision | PENDING_HUMAN_REVIEW | ws-d |
| WSE-003 | 006 SC-006, T090; 003 SC-007 | Performance cost of knowledge rules | No | PENDING_HUMAN_REVIEW | ws-e |
| WSF-003 | 009 T019, T026; REQ-REP-004, FR-001, SC-005 | Dry-run computes edits in memory | No | PENDING_HUMAN_REVIEW | ws-f |
| WSG-02 | 010 T002; REQ-PRF-001, REQ-PRF-004 | Budgets approver and headroom | Decision | PENDING_HUMAN_REVIEW | ws-g |
| WSG-06 | not numbered in fragment (010 P9 contract changes) | Audit log, parallel mode, incremental | No | PENDING_HUMAN_REVIEW | ws-g |
| **E. Open technical issues from automated review** | | | | | |
| AR-R2-1 | not stated in fragment (automated review R2, finding 1) | Legacy `--ai-fix` and kill switch | Yes | RESOLVED-technically-review-wanted | ws-i |
| AR-R3-1 | not stated in fragment (automated review R3, defect 1) | Manifest-less run exit code | Yes | RESOLVED-technically-review-wanted | ws-i |
| AR-R3-2 | not stated in fragment (automated review R3, defects 2 and 3) | Support statement in installed package | Decision | RESOLVED-technically-review-wanted | ws-i |
| AR-R3-3 | not stated in fragment (automated review R3) | Minor behaviour oddities | No | OPEN-technical | ws-i |
| AR-R1-1 | not stated in fragment (automated review R1, finding 1) | Test harness `sys.path` ordering | Decision | OPEN-technical | ws-i |
| AR-R1-2 | not stated in fragment | Weakest test, `test_ai_disabled.py` | Decision | OPEN-technical | ws-i |
| AR-R2-2 | part of ORIG-006-T025 (automated review R2, finding 2) | Evidence tool and evidence coverage | Yes | OPEN-technical | ws-i |
| AR-R2-3 | ADR-011, ADR-017, ADR-018, ADR-019 approval lines; OD-2, OD-4 to OD-8 | Owner approvals recorded as assertions | Decision | PENDING_HUMAN_REVIEW | ws-i |
| AR-STALE | not stated in fragment | Stale planning documents | No | OPEN-technical | ws-i |

Totals: 52 items. Mandatory: Yes 15, Decision 16, No 21.

## 3. Detailed entries

Each entry lists the nine required fields. `not stated in fragment` means the source fragment does not give that field.

### A. Certification gates (original human-gated tasks)

Fragment ws-i and ws-g. These entries are the original tasks that stay unchecked until a human signs (ADR-019 rule 3).

#### ORIG-006-T025: peer review of research records
- **Original task/requirement ID:** 006 T025 (REQ-EVD-001, REQ-EVD-006); backlog KB-006-T025r; packet `specs/006-version-compatibility-rules/T025-review-packet.md`.
- **Component:** Knowledge Base research records, version steps 14-15 to 18-19.
- **What needs human review:** peer-review the research records and set `peer_reviewed` / `RESEARCHED` where complete.
- **Why:** evidence-only rules need human-checked research before any rule is promoted past DETECT_ONLY.
- **Evidence and test results available:** 200 evidence records; `tools/verify_evidence.py` verbatim check at pinned SHAs; `knowledge validate` clean; coverage test.
- **Risk if not approved:** research stays RESEARCH_SEEDED; no step can reach RESEARCHED or be called supported.
- **Recommended reviewer qualifications:** Odoo core developer familiar with version histories, able to read upstream source at the pinned SHAs.
- **Production certification impact:** mandatory for production certification of any path; blocks any "supported path" claim (SC-005 of 010).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-006-T035-T044: golden expected trees
- **Original task/requirement ID:** 006 T035, T044 (REQ-TST-003). T035-prov is done (PROVISIONAL). T044 fully deferred (KB-006-T044r).
- **Component:** golden corpus `knowledge/golden_corpus/review/` (42 cases, all PENDING_INDEPENDENT_REVIEW); `tests/golden_fixtures/17.0/kbi_demo/expected/18.0` (PROVISIONAL).
- **What needs human review:** independently confirm each expected output is correct Odoo migration truth, including the `tree` to `list` change inside a Python `view_mode` and the `group_operator` to `aggregator` edit.
- **Why:** the expected trees were produced by the engine itself, so they test mechanics only and prove nothing about accuracy.
- **Evidence and test results available:** byte-exact, idempotence, SC-005 and label-guard tests; evidence records cited by the rules.
- **Risk if not approved:** wrong edits could be treated as truth; migration accuracy stays unverified.
- **Recommended reviewer qualifications:** senior Odoo developer who has migrated custom addons across 17 to 18, and is not the author of the rules.
- **Production certification impact:** mandatory for any accuracy claim; without it, reports keep the PROVISIONAL label.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-006-T059: quickstart verification
- **Original task/requirement ID:** 006 T059. Technical part T059-prov (PROVISIONAL record in `verification.md`). Residual KB-006-T059r.
- **Component:** not stated in fragment (the quickstart record is FHR-A-003).
- **What needs human review:** confirm the quickstart outputs are what a correct migration should produce.
- **Why:** not stated in fragment.
- **Evidence and test results available:** T059-prov record (see FHR-A-003).
- **Risk if not approved:** same as ORIG-006-T035-T044; depends on it.
- **Recommended reviewer qualifications:** not stated in fragment.
- **Production certification impact:** same as ORIG-006-T035-T044 (per fragment).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-008-T029: RUNTIME_VALIDATED data
- **Original task/requirement ID:** 008 T029 (REQ-VAL-004, REQ-EVD-006). Generator part T029-gen done. Data residual KB-008-T029r. Register item WSF-001.
- **Component:** runtime run records (see WSF-001).
- **What needs human review:** decide which golden migration and step a runtime run record may cover, then run it and record the result.
- **Why:** the 9 runtime tests that passed use synthetic fixtures; a record would overclaim.
- **Evidence and test results available:** Docker 29.7.2; odoo 17/18/19 and postgres:16 images cached; 9 runtime tests passed once (159 s); 13 generator tests. No official 17.0 source image at odoo/docker master; the local `odoo:17.0` image provenance is unverified.
- **Risk if not approved:** no path can be RUNTIME_VALIDATED, so none can be called supported.
- **Recommended reviewer qualifications:** engineer with Docker and Odoo runtime experience.
- **Production certification impact:** mandatory for "supported" status.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-007-T029-T031: live AI provider contract tests
- **Original task/requirement ID:** 007 T029, T030, T031. Register item WSC-AI-1.
- **Component:** `src/odooflux/ai/providers/` adapters; `tests/contract/ai/test_live_providers.py`.
- **What needs human review:** run `ODOOFLUX_AI_TESTS=1` live contract tests with real keys and an owner-chosen model id for Anthropic and an OpenAI-compatible endpoint.
- **Why:** adapters were verified only against recorded or hand-written responses (see WSC-AI-1).
- **Evidence and test results available:** offline contract tests with recorded responses (84 contract tests, 10 live skipped).
- **Risk if not approved:** adapters untested against real services; catalog endpoints, credential variable names and `anthropic_version` unverified (WSC-AI-4).
- **Recommended reviewer qualifications:** engineer with provider accounts and security awareness.
- **Production certification impact:** AI features must not be certified for production until done.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-009-T025: mockup parity
- **Original task/requirement ID:** 009 T025 (stays unchecked). Register item WSD-01.
- **Component:** terminal and HTML reports against `docs/planning/REPORTING_AND_UX.md`.
- **What needs human review:** compare the rendered terminal and HTML reports with the mockups (see WSD-01).
- **Why:** not stated in fragment (see WSD-01).
- **Evidence and test results available:** `tests/unit/reporting/test_mockup_checklist.py` (5 known deviations).
- **Risk if not approved:** not stated in fragment (see WSD-01).
- **Recommended reviewer qualifications:** product owner or UX reviewer.
- **Production certification impact:** UX acceptance only; not a safety gate.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-010-T023: maintainer release sign-off
- **Original task/requirement ID:** 010 T023 (REQ-TST-005). Register item WSG-01.
- **Component:** `docs/planning/RELEASE_CHECKLIST.md` (all sign-off cells PENDING_HUMAN_REVIEW).
- **What needs human review:** the maintainer reviews the evidence for each checklist row and signs.
- **Why:** only a maintainer can certify a release.
- **Evidence and test results available:** see WSG-01.
- **Risk if not approved:** no technical risk stated; it is the production gate.
- **Recommended reviewer qualifications:** project maintainer with release authority.
- **Production certification impact:** production certification is blocked until signed.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-010-T002-T014: benchmark budgets
- **Original task/requirement ID:** 010 T002, T014 (REQ-PRF-001, REQ-PRF-004). Register item WSG-02.
- **Component:** `tests/benchmarks/budgets.json`, `baseline.json`, `REFERENCE_MACHINE.md`.
- **What needs human review:** approve budgets (measured medians with 1.5x headroom; every `approved_by` is PENDING_HUMAN_REVIEW).
- **Why:** the P2 baseline (1.07 s) used a different corpus and predates the knowledge rules; analysis is about 6x slower (10.9 s before T014, 6.8 s after).
- **Evidence and test results available:** serial 13.3 s, parallel 3.8 s, incremental 2.5 s on the 300x30 corpus; 300-module run PASS; `results/profile-summary-2026-11-07.md`.
- **Risk if not approved:** the 6x slowdown is accepted only if a human accepts it; budgets too loose hide regressions, too tight fail on other runners.
- **Recommended reviewer qualifications:** maintainer who owns CI and performance goals.
- **Production certification impact:** performance acceptance; blocks declaring the OBJ-007 scale requirement certified.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### ORIG-002-T010-T028: feature 002 residuals
- **Original task/requirement ID:** 002 T010 (v14 fixture move, left in place), T028 (SC-002 not met), T011-T016 (DEFERRED_KB: KB-002-FIX, KB-002-T015). Register item FHR-A-001.
- **Component:** `specs/002-test-foundation/reconciliation.md`.
- **What needs human review:** accept the reconciliation, including that legacy-CLI characterisation was not redone (the legacy script is now a launcher).
- **Why:** not stated in fragment (see FHR-A-001).
- **Evidence and test results available:** reconciliation table (see FHR-A-001).
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** test architect.
- **Production certification impact:** low; coverage statement only.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-01: T023 release checklist sign-off
- **Original task/requirement ID:** 010 T023 (REQ-TST-005). T023 stays unchecked. Related ORIG-010-T023.
- **Component:** `docs/planning/RELEASE_CHECKLIST.md` (T008, not yet written); `tests/unit/release/rtm_tools.py`.
- **What needs human review:** every checklist item with its evidence link, then sign. Sign-off needs evidence for T020 to T022 and T024, which are open.
- **Why:** only a maintainer can certify a release; no agent writes a signer or marks an item `done`.
- **Evidence and test results available:** RTM gate passes; benchmark PASS; secret scan 0 matches; support statement generated. Failure-injection suite not built.
- **Risk if not approved:** no release; production certification stays blocked while any mandatory item is open.
- **Recommended reviewer qualifications:** project maintainer with release authority.
- **Production certification impact:** blocks the framework release gate (FC-E2E), not the framework implementation; production certification blocked (ORIG-010-T023).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

### B. Safety and security decisions (AI, kill switch, D-10, exit codes)

Fragments ws-c, ws-d, ws-g, ws-h. Legacy `--ai-fix` and the exit-code default also appear as automated-review items in section E (AR-R2-1, AR-R3-1).

#### WSC-AI-1: live provider contract tests not run
- **Original task/requirement ID:** 007 T029, T041 (live variants), T032 (real-provider half); TST-007-015, TST-007-024; REQ-AI-001, FR-015.
- **Component:** `src/odooflux/ai/providers/{anthropic,openai_compatible}.py`; `tests/contract/ai/test_live_providers.py`.
- **What needs human review:** run the opt-in suite against each claimed provider (Anthropic, OpenAI, DeepSeek, Z.ai, one local endpoint) and read the results: `ODOOFLUX_AI_TESTS=1 <KEY_VAR>=... ODOOFLUX_AI_<PROVIDER>_MODEL=<id> python3 -m unittest tests.contract.ai.test_live_providers`. Sends only a trivial synthetic prompt.
- **Why:** adapters were verified only against recorded or hand-written bodies; real endpoints may differ (error bodies, cached-token usage, structured output, `max_tokens` naming, DeepSeek and Z.ai specifics).
- **Evidence and test results available:** offline `tests.contract.ai.test_gateway_providers` (84 contract tests, 10 live skipped). Live: NOT RUN (no network, no keys, no owner-chosen model ids).
- **Risk if not approved:** Medium. A wrong mapping gives wrong usage, cost or truncation handling, or a hard error; it cannot send unauthorized data (gateway checks run before any adapter).
- **Recommended reviewer qualifications:** engineer with API access and budget for each provider; able to read provider API docs.
- **Production certification impact:** blocks any statement "provider X is supported" or "tested live"; does not block framework completion. Until run, describe adapters as "offline-verified". Linked to ORIG-007-T029-T031.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSC-AI-2: data-authorization policy sign-off
- **Original task/requirement ID:** 007 T036, T037, T043, T044; FR-019, FR-020, FR-001; ADR-017.
- **Component:** `src/odooflux/ai/authorization.py`, `gateway.py`; `src/odooflux/cli/ai_options.py`.
- **What needs human review:** (1) allowed categories are exactly `source_python`, `source_xml`, `evidence_excerpt`; credentials, secrets, dumps and customer data cannot be granted. (2) both `--ai-consent-send-code` (every `--ai` run) and a per-provider `--ai-authorize` grant (external only) are required; the kill switch (`--ai-disable-external`, `ODOOFLUX_AI_DISABLE_EXTERNAL`) beats a grant. (3) `local` and fake providers need no grant; the code does not verify that `local` is loopback. (4) a region matching the sensitive-content filter is excluded whole, never redacted and sent. (5) external endpoints must be `https://`. (6) whether "external default type, AI still off until `--ai`" matches owner intent (ADR-017 says confirmed 2026-11-07).
- **Why:** source transmission to a third party is irreversible; this policy is the control.
- **Evidence and test results available:** `tests.unit.ai.test_authorization`, `test_minimisation`, `test_cli_options`; `tests.integration.ai.test_kill_switch`, `test_no_fallback`, `test_consent`. All pass offline.
- **Risk if not approved:** High if wrong: unauthorized disclosure of customer code. Known gaps: the filter is pattern-based (WSC-AI-3); `local` trust is declarative.
- **Recommended reviewer qualifications:** data-protection or security lead with authority over customer-data handling; has read the customer contracts covering source code.
- **Production certification impact:** production certification of AI use stays blocked until signed off (ADR-019 item 6). The default-off behaviour needs no sign-off to ship.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSC-AI-3: prompt-injection and secret-handling review
- **Original task/requirement ID:** 007 T016, T024, T037, T040, T046; REQ-SEC-004, FR-010, FR-011, FR-021, REQ-AI-008.
- **Component:** `src/odooflux/ai/prompts/{builder.py,templates/v1}`, `protected.py`, `providers/credentials.py`, `providers/transport.py`, `gateway.py`.
- **What needs human review:** template v1 wording; delimiter rule (a region containing `<code>` or `</code>` is skipped, not escaped); model output becomes only an `Edit` for one region and must pass syntax, region-shape, protected-identifier, L1, L2 re-scan and L3 checks; the sensitive-content regex set for false negatives (generic high-entropy strings, non-literal secrets) and false positives; the XML guard (DOCTYPE and ENTITY refused); the `Secret` wrapper and secrets-file rules (outside scanned paths, owner-only permissions on POSIX); logging is metadata only and error bodies are never read into diagnostics; TLS uses stdlib default verification.
- **Why:** customer code is attacker-controlled text; secrets in customer repositories are common; a miss is a leak or a bad edit. Tests use canary values, which only prove anticipated patterns.
- **Evidence and test results available:** `tests.unit.ai.test_prompt_injection`, `test_secret_redaction`, `test_minimisation`, `test_no_prompt_logging`, `test_protected_identifiers`, `test_response_handling`; `tests.regression.test_ai_findings` (F-AI-1,2,4,5,6,7). All pass offline. No penetration test, no fuzzing, no review of a real customer repository.
- **Risk if not approved:** High for filter coverage; medium for injection. Known limits: methods and classes may be renamed in a statement-kind region; behaviour changes inside a function body are not detected beyond syntax and the re-scan.
- **Recommended reviewer qualifications:** application-security engineer familiar with LLM prompt injection and secret scanning; an Odoo developer to judge the protected-identifier set.
- **Production certification impact:** blocks a security claim for AI assistance. `review_required` rules cap modules at `NEEDS_REVIEW` even for accepted AI edits (kept as designed).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSC-AI-4: model and pricing configuration needing owner input
- **Original task/requirement ID:** 007 T035, T042, T047; FR-018, FR-015; ADR-017.
- **Component:** `src/odooflux/ai/catalog/providers.json` (packaged); user catalogs via `--ai-catalog`.
- **What needs human review:** the packaged catalog lists no models and no prices (owner configuration; Principle VI). The owner must supply a catalog per provider before real use. Unverified defaults (written from general knowledge): four external base URLs; `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY` names; `options.anthropic_version`. Also decide: default budgets (none set; job budget is mandatory with no default); model-by-complexity tiers (not implemented); per-model `max_tokens_param` for newer OpenAI models (default `max_tokens`); whether DeepSeek and Z.ai accept `response_format` (sent only when the model declares `structured_output`).
- **Why:** names, prices and endpoints change and are provider facts; code must not assert them.
- **Evidence and test results available:** `tests.unit.ai.test_catalog` (source scan fails on model names or prices in `src/odooflux/ai`); `tests.contract.ai.test_gateway_providers`. Test catalogs use invented names.
- **Risk if not approved:** low to medium. A wrong endpoint or header gives clean `auth` or `invalid_request` errors, never a silent provider switch. Wrong pricing gives wrong cost reports and cost budgets.
- **Recommended reviewer qualifications:** project owner or billing-aware engineer with access to each provider's current documentation and account.
- **Production certification impact:** none for the framework. Blocks "ready to use with provider X out of the box" and any cost claim.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSC-AI-5: items surfaced during implementation
- **Original task/requirement ID:** 007 T012, T026, T034; FR-003, FR-013, REQ-AI-006.
- **Component:** Knowledge Base rule metadata; report model schema; packaging.
- **What needs human review:** (a) no KB rule has `ai_eligible = true`, so a real run escalates nothing; choosing eligible rules with evidence is KB work (DEFERRED_KB; backlog ID to be assigned by the owner) and was not done. (b) the AI pass writes `state["ai_usage"]` in the report model's shape and the schema check passes; whether the extra detail fields should be added to the schema is the reporting owner's call. (c) `odooflux/ai/catalog/providers.json` needs a `package-data` entry in `pyproject.toml` (the wheel-assets test fails until then).
- **Why:** without (a) the feature is inert by design; without a schema decision on (b) the extra fields are unspecified; without (c) a built wheel breaks `--ai`.
- **Evidence and test results available:** `tests.integration.packaging.test_wheel_assets` (fails on (c) at the time of writing); verification log scenario 3.
- **Risk if not approved:** low (all fail closed).
- **Recommended reviewer qualifications:** project owner (a); reporting owner (b); packaging owner (c).
- **Production certification impact:** none stated for production. (a) limits claims about AI value; (c) blocks framework completion for 007 until fixed; (b) is a documentation and schema nicety.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-04: exit-code default and legacy mapping (D-10)
- **Original task/requirement ID:** 009 T016; FR-006, REQ-REP-005, SC-005.
- **Component:** `src/odooflux/cli/exit_codes.py`, `cli/report_outputs.py`; option `--exit-codes {legacy,v1}`.
- **What needs human review:** decide when the default flips from the characterised legacy mapping to the documented v1 table. Under v1 a module that cannot run L3 (for example no manifest) is `BLOCKED`, exit 4; legacy returns 0 or 3. Two existing tests encode the legacy result: `tests.regression.test_p0_reporting.ExitCodeTests.test_fail_on_thresholds` and `tests.contract.test_plugin_kinds.PluginKindsTests.test_validator_effect_rejects_the_edit`.
- **Why:** FR-006 says exit codes follow the table; D-10 says the legacy mapping stays for one minor release. Flipping the default needs an owner decision and test updates.
- **Evidence and test results available:** `tests/unit/cli/test_exit_codes.py` (full table, `--fail-on` matrix, precedence); `tests/integration/reporting/test_cli_exports.py` (default legacy, v1 opt-in); `tests/regression/test_reporting_findings.py` (F-REP-3, F-VER-4).
- **Risk if not approved:** CI users get the old mapping by default; users of `--fail-on-status` or `--exit-codes v1` get the new table. See AR-R3-1.
- **Recommended reviewer qualifications:** project owner (policy); CI maintainer for impact.
- **Production certification impact:** blocks declaring FR-006 fully met by default behaviour.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-06: offline HTML in real browsers and untrusted-content handling
- **Original task/requirement ID:** 009 T020, T021, T022; REQ-REP-003, REQ-SEC-004.
- **Component:** `src/odooflux/reporting/html/html.py`.
- **What needs human review:** open the file offline (network disabled) in current Chrome, Firefox or Safari; print it; check sections, `<details>` collapsing and the PROVISIONAL banner; review escaping against payloads from your own corpus.
- **Why:** tests parse HTML with the stdlib and do not render it or run browser parser quirks. No CSP header can be set on a file; it relies on escaping alone.
- **Evidence and test results available:** `test_html.py` (no scripts, no external resources, only https evidence anchors); `test_html_escaping.py` (seven payload classes in every text field); cross-renderer count test.
- **Risk if not approved:** a browser-specific parsing quirk could make an escaped payload active; layout may differ on print.
- **Recommended reviewer qualifications:** web security reviewer for escaping; any developer for layout.
- **Production certification impact:** blocks certification of the HTML report as safe for untrusted module content.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-03: D-10 removal window for `--api-key`
- **Original task/requirement ID:** 010 T017, T019; REQ-AI-008, FR-008.
- **Component:** `src/odooflux/cli/deprecations.py` (`API_KEY_REMOVED_IN = "0.3.0"`); `cli/main.py`.
- **What needs human review:** D-10 is not recorded as decided in the ADRs; the spec assumes one minor release. Confirm the window and the release that removes the option. Today (0.2.0) the option still warns. Removal means bumping `odooflux.__version__` to 0.3.0.
- **Why:** removing a CLI option breaks scripts; the owner chooses the release.
- **Evidence and test results available:** `tests/unit/cli/test_api_key_removed.py` (exit 2, no echo in all argument forms, simulated version).
- **Risk if not approved:** the credential-leak risk stays open until the version is bumped.
- **Recommended reviewer qualifications:** project owner; security reviewer for the no-echo behaviour.
- **Production certification impact:** blocks FR-008 being met by default behaviour.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSH-T020: failure-injection fix review (F-INJ-1)
- **Original task/requirement ID:** 010 T020, T021; REQ-SAF-005.
- **Component:** `src/odooflux/core/jobs/promote.py` (`_restore`); `tests/integration/hardening/test_failure_injection.py`.
- **What needs human review:** restore now skips unchanged files and blocks the module (with a rollback hint) when a restore write fails.
- **Why:** safety-path change in customer-file handling; only a human reviewer certifies it.
- **Evidence and test results available:** `tests/regression/test_failure_injection_findings.py` (F-INJ-1); 13 injection tests.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** maintainer familiar with the promote and rollback contracts.
- **Production certification impact:** not stated in fragment (fragment marks it `Certification: PENDING_HUMAN_REVIEW`).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

### C. Data and knowledge decisions (provisional corpus, legacy rule overlap, evidence)

Context from ws-e: the 91 knowledge rules keep DETECT_ONLY 78, FIX_ENABLED 10, DRAFT 3 (asserted by a test). Context from ws-f and ws-a: no rule, evidence record or maturity was added or changed by these workstreams. The provisional 17.0 to 18.0 corpus is labelled PROVISIONAL in every marker file.

#### FHR-A-001: 002 reconciliation scope (A-11)
- **Original task/requirement ID:** 002 T010, T017, T019, T020, T028; backlog KB-002-FIX, KB-002-T015.
- **Component:** `specs/002-test-foundation/reconciliation.md`, `tasks.md`.
- **What needs human review:** the disposition of each of the 28 tasks; the reduced Done-when for T017, T019, T020 (two INDEX fixtures instead of seven); T010 left unmoved; T015 note about `17.0/kbi_demo`.
- **Why:** A-11 is a spec amendment proposal; only the owner can narrow a Done-when.
- **Evidence and test results available:** `reconciliation.md` table (file and test per task); `tests/integration/test_fixture_validity.py`; `tests/regression/test_regression_index.py`.
- **Risk if not approved:** 002 stays at 20 of 28 tasks `[X]`; the P1 gate in the phase closure matrix cannot be declared met.
- **Recommended reviewer qualifications:** project owner or maintainer who owns the spec.
- **Production certification impact:** none on migration correctness; affects phase P1 closure only.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### FHR-A-002: PROVISIONAL expected tree and report, 17.0 to 18.0 (006 T035)
- **Original task/requirement ID:** 006 T035 (original stays unchecked); technical part T035-prov `[X]`.
- **Component:** `tests/golden_fixtures/17.0/kbi_demo/` (input module, `expected/18.0/tree`, `expected/18.0/report.json`); `tools/update_expectations.py`.
- **What needs human review:** whether the input module represents realistic custom-addon constructs for 17.0; every line of the expected tree against what a correct 17.0 to 18.0 migration should produce. Current expected edits are only: manifest version prefix, `tree` to `list` (tags and `view_mode`).
- **Why:** the expected output was generated by the current engine, so it proves reproducibility, not correctness. The KB `17-18.*` rules (for example `group_operator` to `aggregator`, DETECT_ONLY rules) are not applied by the `migrate` pipeline yet; after wiring, the tree and report change and need re-review.
- **Evidence and test results available:** `tests/integration/test_golden_migrations.py`; `tests/integration/test_provisional_corpus.py` (byte match, input digest, idempotence, SC-005, unsupported target, marker guard).
- **Risk if not approved:** the corpus remains a mechanics test only; it cannot support any statement that 17.0 to 18.0 migration is correct. Any report or support statement using it must say "provisional".
- **Recommended reviewer qualifications:** Odoo 17 and 18 developer who has migrated custom modules; independent of the person who wrote the rules.
- **Production certification impact:** blocks certification of 006 T035 and SC-003 for the validation path; production certification stays blocked while open.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### FHR-A-003: PROVISIONAL quickstart record (006 T059)
- **Original task/requirement ID:** 006 T059 (original stays unchecked); technical part T059-prov `[X]`.
- **Component:** `specs/006-version-compatibility-rules/verification.md`, heading "PROVISIONAL: quickstart against the 17.0 to 18.0 validation path".
- **What needs human review:** the recorded outputs and four unmet expectations: knowledge rules not applied by `migrate`; fixture lacks `_sql_constraints` and `@api.returns`; in-place scan includes `expected/`; SC-002 and SC-003 full scope. Decide whether T059's Done-when is accepted after the wiring work lands.
- **Why:** the quickstart smoke expectation is not met by the current pipeline.
- **Evidence and test results available:** command outputs in `verification.md`; `tests/integration/test_provisional_corpus.py`.
- **Risk if not approved:** T059 stays open; the P5 completion gate is not met.
- **Recommended reviewer qualifications:** maintainer able to run the quickstart and judge the unmet items.
- **Production certification impact:** blocks P5 closure; no effect on safeguards (SC-005, L3, D-08 unchanged). Not stated as a production blocker here; ORIG-006-T059 states the same impact as ORIG-006-T035-T044.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### FHR-A-004: provisional corpus labelling guard
- **Original task/requirement ID:** supports ADR-019 rule 4 (provisional corpus never presented as approved).
- **Component:** `PROVISIONAL.md` in `17.0/`, `17.0/kbi_demo/expected/`, `17.0/kbi_demo/expected/18.0/`; `INDEX.json` `"authority": "PROVISIONAL"`; `tests/integration/test_provisional_corpus.py::ProvisionalMarkerTests`.
- **What needs human review:** that the marker wording is acceptable, and that any later promotion of the corpus (removing a marker) is a recorded human decision.
- **Why:** the guard fails the suite if a marker or the authority label is removed or changed to an approval, which prevents silent promotion.
- **Evidence and test results available:** `test_marker_and_authority_present`; `test_relabelling_as_approved_is_detected`.
- **Risk if not approved:** none for safety; labels stay in force.
- **Recommended reviewer qualifications:** maintainer.
- **Production certification impact:** none; documents that the corpus is not approved.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### FHR-A-005: rule coverage report scope (002 T026)
- **Original task/requirement ID:** 002 T026.
- **Component:** `tests/unit/test_rule_coverage_report.py`, `tests/rule_coverage.txt`.
- **What needs human review:** the decision to read legacy categories from `src/odooflux/rules/shared/legacy_rules.py` (the tables left `odooflux.py` in the P2 cut-over) and the `rule:<category>:<kind>` docstring tag convention.
- **Why:** the task text names `odooflux.py`, which no longer holds the tables; the report is report-only and every cell is empty because no tests carry tags.
- **Evidence and test results available:** the test file and generated report.
- **Risk if not approved:** coverage enforcement (REQ-TST-002, P5) has no agreed tag format.
- **Recommended reviewer qualifications:** maintainer.
- **Production certification impact:** none.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSE-001: legacy tables and knowledge rules run side by side; overlap decisions
- **Original task/requirement ID:** 006 T086, T089, T092 (certification part); FR-017; `legacy_disposition.json` (keep/correct/retire); SC-005.
- **Component:** `src/odooflux/rules/shared/legacy_overlap.py`; `core/orchestrator/knowledge_rules.py` (`deduplicate`); `rules/shared/legacy_rules.py`.
- **What needs human review:** (1) before this work `migrate` ran only the legacy tables; the 91 knowledge rules now run per plan step. (2) the disposition marks many legacy rows `retire` or `correct`, but they were NOT retired or changed, because that would alter existing results. Where both report the same construct on the same file line, only the legacy finding is emitted (15 knowledge rules are mapped to legacy categories). (3) where the disposition says a legacy row is wrong for some versions (`Attrs Attribute` and `Deprecated Decorator` apply to every target), the legacy finding still appears and the knowledge rule's version window is not applied. Decide whether to retire or correct those rows and whether the knowledge finding should win.
- **Why:** retiring or correcting legacy rows changes reported results and fix behaviour; it needs a person who can judge migration correctness.
- **Evidence and test results available:** `tests/unit/test_knowledge_rule_selection.py`; `tests/integration/test_knowledge_rules_pipeline.py::test_each_construct_is_reported_once`.
- **Risk if not approved:** MEDIUM. Reports can carry an over-broad legacy finding in place of the better-evidenced knowledge finding. Lines with two different constructs are not merged. Existing behaviour is unchanged.
- **Recommended reviewer qualifications:** Odoo migration engineer familiar with the 12 to 19 changes and the legacy script's rule table.
- **Production certification impact:** none on framework completion; open retire or correct decisions limit any claim that report content is migration-correct.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSE-002: regenerated PROVISIONAL expected output for 17.0 to 18.0
- **Original task/requirement ID:** 006 T091; T035 and T059 (certification parts stay open); FHR-A-002, FHR-A-003; ADR-019 rule 4.
- **Component:** `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json` and `tree/` (written only by `PYTHONPATH=src python3 tools/update_expectations.py --force`).
- **What needs human review:** the diff against the previous provisional output. `report.json`: findings 5 to 17; module status `STATIC_VALIDATED` to `NEEDS_REVIEW` (`open_review_findings`). New DETECT_ONLY findings, not edited, `NEEDS_REVIEW`: `17-18.xml.cron-numbercall-removed`, `17-18.python.name-get-removed`, `17-18.python.name-search-to-search-display-name`, `17-18.python.user-has-groups-removed`, `17-18.python.model-renamed-mail-canned-response`, `17-18.csv.model-renamed-mail-canned-response`, `17-18.js.rpc-service-removed`, `17-18.xml.kanban-box-deprecated`. FIXED by FIX_ENABLED rules: `17-18.python.group-operator-renamed` (2) and `17-18.xml.tree-to-list` (2, the `view_mode` strings in `models/demo.py` and `views/demo_views.xml`). `tree/models/demo.py` changed: `group_operator=` became `aggregator=`, `'tree,form'` became `'list,form'`; no other file changed. `INDEX.json` input digest unchanged.
- **Why:** the expected output pins what the engine does now; it is not migration truth. Whether these edits are correct for a real 17.0 to 18.0 module (for example the `view_mode` string inside a Python action dict) needs a human.
- **Evidence and test results available:** `tests/integration/test_golden_migrations.py`; `tests/integration/test_provisional_corpus.py` (byte match, idempotence, DETECT_ONLY constructs survive, markers). Evidence IDs are those of the rule rows; none were added.
- **Risk if not approved:** MEDIUM. A wrong rule would be baked into a byte-exact expectation. The corpus is labelled PROVISIONAL in every marker file.
- **Recommended reviewer qualifications:** Odoo 17/18 developer with an independent 17.0 and 18.0 reference.
- **Production certification impact:** blocks any statement that the 17.0 to 18.0 path is certified; provisional label stays.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSF-001: runtime run records and the RUNTIME_VALIDATED mark (T029-data)
- **Original task/requirement ID:** 008 T029 (stays unchecked; T029-gen is the technical part); REQ-VAL-004, REQ-EVD-006; plan A-6.
- **Component:** `src/odooflux/knowledge/runtime_runs.py`; `knowledge/schemas/runtime_runs.schema.json`; `knowledge/compatibility/runtime_runs.json` (shipped with `runs: []`); `knowledge/matrix.py`; `docs/planning/VERSION_COMPATIBILITY_MATRIX.md`.
- **What needs human review:** (1) the record schema and the rule that a step is marked only when its latest valid record passes. (2) which golden migration and step a record may cover. The opt-in runtime suite passed once on 2026-11-07 (9 tests, odoo:18.0 and 19.0, postgres:16) but exercises synthetic framework fixtures, so no record was written. (3) whether `RUN_FAILED` and the `Behavioural verified` column wording are acceptable matrix vocabulary.
- **Why:** a `RUNTIME_VALIDATED` mark is a support claim; only a person can decide that a recorded run supports it, and the run must really have executed.
- **Evidence and test results available:** `tests/unit/knowledge/test_matrix_runtime_runs.py`; `tests/integration/knowledge/test_matrix_committed.py`; opt-in `tests/runtime/*` (008 quickstart verification log).
- **Risk if not approved:** MEDIUM. A hand-written record would be trusted by the generator; the schema checks shape and consistency, not the truth of the run.
- **Recommended reviewer qualifications:** maintainer of the runtime layer with access to Docker and the Odoo images.
- **Production certification impact:** blocks any statement that a transition is runtime validated; framework completion is unaffected. Linked to ORIG-008-T029 (mandatory for "supported" status).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSF-002: provisional label rule and regenerated provisional report
- **Original task/requirement ID:** ADR-019 rule 4; 009 US3 follow-up; FHR-A-002, FHR-A-003.
- **Component:** `src/odooflux/core/orchestrator/provisional.py`; `--provisional-corpus` in `cli/main.py` and `cli/migrate.py`; `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json`.
- **What needs human review:** (1) the label wording and trigger: the flag, or a `PROVISIONAL.md` in the module directory or any parent; a provisional corpus copied elsewhere loses the marker and needs the flag. (2) the regenerated expected report: only `provisional: {active: true, labels: [...]}` was added; it stays PROVISIONAL and unreviewed.
- **Why:** reports and SARIF must not let provisional results look like approved migration truth.
- **Evidence and test results available:** `tests/integration/reporting/test_provisional_cli.py` (JSON, SARIF, HTML, terminal); `tests/integration/test_provisional_corpus.py`.
- **Risk if not approved:** LOW. A run on an unmarked copy without the flag would carry no label.
- **Recommended reviewer qualifications:** maintainer who owns the report model and support statements.
- **Production certification impact:** none for framework completion.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-04: support statement
- **Original task/requirement ID:** 010 T006, T007; REQ-VER-003, REQ-EVD-006, SC-005; FC A-9.
- **Component:** `src/odooflux/cli/support_statement.py`; `docs/planning/SUPPORT_STATEMENT.md` (generated).
- **What needs human review:** the rule is unchanged: supported only when every step is `RULES_TESTED` and the target is `RUNTIME_VALIDATED`. No path is supported today; 17.0 to 18.0 is `experimental`, labelled PROVISIONAL. ADR-019 default OD-7 expected the provisional path to be called supported; the SC-005 rule forbids it while the matrix shows no `RULES_TESTED` step and no runtime run. Confirm this reading and the definition of `experimental` (research and runnable rules on every step).
- **Why:** not stated in fragment (the conflict between OD-7 and SC-005 is stated in the What field).
- **Evidence and test results available:** `tests/unit/release/test_support_statement.py`; the committed file matches the generator.
- **Risk if not approved:** users may read `experimental` as endorsement; the section "Not yet supported (knowledge pending)" lists every unsupported path and its backlog IDs.
- **Recommended reviewer qualifications:** maintainer who owns the support policy.
- **Production certification impact:** none on mechanics; blocks any public support claim.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-05: RTM gaps and gate semantics
- **Original task/requirement ID:** 010 T003 to T005; A-8.
- **Component:** `docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md` ("Release gate data", "Verification records"); `tests/unit/release/rtm_tools.py`.
- **What needs human review:** (1) "mapped passing test" means a test file cites the TST or REQ id; whether it passes is the suite result, not proved per requirement. (2) six requirements carry a partial `DEFERRED_KB` row (REQ-TST-003, REQ-TST-002, REQ-EVD-001, REQ-EVD-006, REQ-VAL-004, REQ-VER-003) with their KB ids. (3) requirements whose mapped tests are all opt-in or skippable are printed as warnings (`--strict` fails them). (4) no verification-record rows exist.
- **Why:** the gate must not be papered over; gaps stay visible.
- **Evidence and test results available:** `python tests/unit/release/rtm_tools.py`; F-WALK-1 had no citing test and now has `tests/regression/test_walk_findings.py`.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** maintainer or QA lead.
- **Production certification impact:** blocks SC-001 sign-off if the reading in (1) is rejected.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

### D. Product, UX, packaging and performance decisions

#### WSB-001: REQ-MAN-002 wording and the version-prefix opt-out
- **Original task/requirement ID:** 006 T084 (certification part); FR-019; REQ-MAN-002; OD-4.
- **Component:** `specs/001-safety-stabilization/spec.md` (REQ-MAN-002 text); rule `*.manifest.version-prefix`; `src/odooflux/core/orchestrator/run_inputs.py`.
- **What needs human review:** REQ-MAN-002 reads "unless opts out" while the rule is opt-in and DETECT_ONLY. Decide the wording (opt-in matches current behaviour) and whether any FIX_ENABLED promotion is wanted. The wording was NOT changed by this workstream.
- **Why:** the wording and the shipped behaviour disagree; only the owner can settle which governs. Automatic prefix rewriting (D-A3) is not approved (ADR-018).
- **Evidence and test results available:** `tests/integration/test_planner_wiring.py` (the target reaches the rule through the CLI only with `--enable-rule`; the written manifest is byte-identical with and without the opt-in under `--fix`; missing run input yields an INFO gap); `tests/unit/rules/test_bind_run_params.py`.
- **Risk if not approved:** LOW. Detect-only INFO finding, opt-in, no fixer is bound on this path.
- **Recommended reviewer qualifications:** project owner or maintainer with authority over requirement text.
- **Production certification impact:** none on release readiness while it stays opt-in; a change to FIX_ENABLED would need a new decision, evidence and golden tests.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSB-002: wheel contents and size
- **Original task/requirement ID:** 010 T025 to T027 (certification part); FC A-10; OD-5.
- **Component:** `pyproject.toml` (`package-data`); `MANIFEST.in`; `tests/integration/packaging/`.
- **What needs human review:** the choice to ship all knowledge data in the wheel: 246 JSON files; `odooflux-0.2.0-py3-none-any.whl` is 1,382,820 bytes (405 entries; `src/odooflux/knowledge` is about 6.7 MB on disk, mostly 200 evidence records). Alternatives: ship evidence separately or trim it.
- **Why:** the loaders read these files at runtime; before the fix 244 assets were missing from the wheel, so an installed tool could not load its own knowledge.
- **Evidence and test results available:** `tests/integration/packaging/test_wheel_assets.py` (offline build; red before the fix with 244 missing, green after); `test_wheel_install.py` (opt-in `ODOOFLUX_PACKAGING_INSTALL=1`; ran once, 4 tests OK: fresh venv, offline install, imports from site-packages, `odooflux --help`, `knowledge validate` exit 0, analysis of the p0 fixture from outside the repo with a JSON report).
- **Risk if not approved:** LOW to MEDIUM. Distribution size, and whether evidence text may be redistributed under upstream licences (not assessed here).
- **Recommended reviewer qualifications:** maintainer with packaging and licensing responsibility.
- **Production certification impact:** none for framework completion; a licensing finding could block publication of the wheel.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSB-003: dependency scanner runs by default in every migrate run
- **Original task/requirement ID:** 006 T082; FR-020; REQ-DEP-001; FR-022.
- **Component:** `src/odooflux/dependencies/scan.py`; `core/orchestrator/run.py` (`build_run_context`).
- **What needs human review:** the scanner is on by default. It adds `*.deps.unknown-dependency` and `*.deps.removed-with-successor` findings (DETECT_ONLY, never an edit) next to the L3 `integrity.missing_module` finding for the same dependency, so one unresolved dependency can appear twice. Decide whether to de-duplicate or keep both. Successor data comes from two evidence-backed entries only (EV-520, EV-521); every other removed module reports "no successor known".
- **Why:** changes visible report content (more findings) for modules with unresolved dependencies. The 17.0 provisional corpus is unaffected (no finding).
- **Evidence and test results available:** `DependencyScannerWiringTests` in `tests/integration/test_planner_wiring.py`.
- **Risk if not approved:** LOW. Findings only.
- **Recommended reviewer qualifications:** maintainer familiar with the report model and the L3 integrity checker.
- **Production certification impact:** none stated for production; report-count expectations in the final golden set must include these findings.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSB-004: new CLI option `--enable-rule`
- **Original task/requirement ID:** 006 T080; FR-017; FR-019.
- **Component:** `src/odooflux/cli/main.py`; `cli/migrate.py`; `builtins.py` (registers `run_rule_binder`).
- **What needs human review:** the opt-in mechanism and name (`--enable-rule RULE_ID`, repeatable; an id that is not a run-input rule is a usage error, exit 2). It is a contract addition to `contracts/cli.md`, not yet documented there.
- **Why:** the requirement says version-prefix stays opt-in, and the CLI had no opt-in channel.
- **Evidence and test results available:** `VersionPrefixWiringTests`; `tests/integration/test_cli_contract.py` passes (legacy options unchanged).
- **Risk if not approved:** LOW.
- **Recommended reviewer qualifications:** CLI contract owner.
- **Production certification impact:** none stated for production; the CLI contract document needs a matching line before release.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-01: mockup parity
- **Original task/requirement ID:** 009 T025 (stays unchecked); REQ-REP-002, REQ-REP-006.
- **Component:** `src/odooflux/reporting/terminal/ansi.py`; `src/odooflux/reporting/html/html.py`; mockups in `docs/planning/REPORTING_AND_UX.md` sections 3 and 4.
- **What needs human review:** run the CLI with `--ui ansi` and `--html` on a real module and compare each mockup with the output. Decide whether each documented deviation is acceptable: (1) plan line shows no per-step research status; (2) progress is derived from the final model, with no live detect or fix counters; (3) verification scope lists layers, not sub-validators such as the RNG check; (4) recovery has no backup path and no resume line; (5) layer outcomes are words (`L1 PASS`), not check marks; (6) widths below 110 columns use a stacked per-module layout.
- **Why:** parity with a design mockup is a judgement about usability and wording, not something a test can certify.
- **Evidence and test results available:** `tests/unit/reporting/test_mockup_checklist.py` (required sections and labels); `tests/unit/reporting/test_terminal_snapshots.py` (60 snapshots, 10 golden models, colour and plain, widths 60/80/120); `tests/unit/reporting/test_html.py`.
- **Risk if not approved:** the output may be correct and still not match what the owner wants; wording or layout rework after sign-off.
- **Recommended reviewer qualifications:** project owner or maintainer who owns the UX design; one daily CLI user of the tool.
- **Production certification impact:** blocks certification of 009 T025 only (UX acceptance); no effect on counts, schema or exit codes.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-02: SARIF consumer acceptance
- **Original task/requirement ID:** 009 T012, T015 (technical part done); REQ-REP-004; SC-001.
- **Component:** `src/odooflux/reporting/exporters/sarif.py`.
- **What needs human review:** upload a SARIF file produced by `--sarif` to the code-scanning UI the team uses (for example GitHub code scanning) and confirm results appear with the right level, file and line, and that rule help links work. Confirm two modules with the same relative file name and line do not collapse, and that `kind: pass` results with `--sarif-include-fixed` are shown or ignored sensibly.
- **Why:** validity against the SARIF 2.1.0 schema does not prove a consumer accepts or displays the file. Consumer limits (result caps, size caps, required fields such as `endLine`) are not tested. The exporter omits `endLine`/`endColumn` and rule `properties.step` because the model carries no such data.
- **Evidence and test results available:** `tests/unit/reporting/test_sarif.py` validates every golden model against the vendored SARIF 2.1.0 schema (retrieved 2026-11-07, sha256 in `PROVENANCE.json`) with an in-repo stdlib validator; level mapping, fingerprints, URI encoding and exit code asserted. No upload to any consumer was tested.
- **Risk if not approved:** CI users may see rejected uploads, missing annotations or truncated results.
- **Recommended reviewer qualifications:** CI or DevSecOps engineer who operates the code-scanning platform.
- **Production certification impact:** blocks any claim of "accepted by code-scanning UIs"; does not affect the JSON report or exit codes.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-03: terminal rendering on real terminals
- **Original task/requirement ID:** 009 T007, T010, T011; REQ-REP-002; F-REP-2.
- **Component:** `src/odooflux/reporting/terminal/ansi.py`, `rich_adapter.py`, `options.py` (`display_width`, `sanitize_text`).
- **What needs human review:** view colour and plain output in at least one Linux terminal, macOS Terminal or iTerm, Windows Terminal, and a CI log viewer; with `NO_COLOR=1`, at 60, 80 and 120 columns; with East Asian and combining characters in module names; and with `--ui rich` when `rich` is installed. Check that colours are readable on light and dark themes and that nothing relies on colour alone.
- **Why:** snapshots prove the bytes, not how a terminal draws them. Wide-character width uses `unicodedata.east_asian_width`, which can differ from a terminal's own tables. Rich output was tested only with a throwaway install.
- **Evidence and test results available:** `test_terminal_snapshots.py` (layout identical in colour and plain; every line within width); `test_terminal_escaping.py` (ANSI and control-character injection neutralised); `test_terminal_rich.py` (rich 5/5 when installed; fallback when absent).
- **Risk if not approved:** misaligned columns or unreadable colours on some terminals; hostile-terminal behaviour beyond the tested escape classes is unknown.
- **Recommended reviewer qualifications:** developer who uses the CLI on the target platforms; for the escaping part, a security reviewer familiar with terminal injection.
- **Production certification impact:** blocks certification of terminal UX on real terminals (009 T007, T010); none on data.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-05: diff export limits (RESOLVED-technically per WSF-003)
- **Original task/requirement ID:** 009 T019; REQ-REP-004; SC-003.
- **Component:** `src/odooflux/reporting/exporters/diff.py`; `--diff`.
- **What needs human review:** original concern: a dry run exported an empty patch because the orchestrator computed edits only in mode `fix`. Resolved technically by WSF-003 (dry run now computes edits in memory and reports `planned_files`). Residual review points, kept from the original fragment: (a) confirm no consumer treated an empty dry-run `edits` list as meaningful (WSF-003); (b) the patch is built from the pre-run backup, so `--fix --no-backup --diff` is refused; (c) a module with rejected edits or a blocked module is excluded as a whole and listed in the index; (d) a rename is exported as delete plus create.
- **Why:** US3 acceptance wording says "Given a dry-run", which the pipeline could not satisfy before WSF-003.
- **Evidence and test results available:** `tests/integration/reporting/test_diff_apply.py` (`patch -p1`, byte-for-byte, LF, CRLF, no final newline, rename, every corpus fixture including the provisional 17.0 one); `tests/integration/reporting/test_dry_run_diff.py` (WSF-003); quickstart record.
- **Risk if not approved:** reviewers cannot get a diff before writing (reduced by WSF-003).
- **Recommended reviewer qualifications:** maintainer of the orchestrator; a reviewer who reads patches daily.
- **Production certification impact:** none stated for production; the original blocker on US3 acceptance scenario 1 (dry run) is resolved technically per WSF-003, with the residual points above.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSD-07: verification wording and provisional label
- **Original task/requirement ID:** 009 T008; FR-007; REQ-BIZ-003; ADR-019 rule 4.
- **Component:** terminal and HTML scope blocks; `provisional` model field.
- **What needs human review:** the "Why not verified" and Limit wording (does it avoid over-claiming); that UNAVAILABLE reads differently from FAIL; and that a run using a provisional corpus is labelled. The label appears only when the producer of the model supplies `provisional`; the orchestrator does not set it yet.
- **Why:** honesty of claims is a judgement call, and the provisional wiring is outside workstream D.
- **Evidence and test results available:** `test_terminal_sections.py`; `test_html.py`; `test_model_extensions.py` (unrun layers never PASS; a module blocked before analysis shows L1 and L2 SKIPPED).
- **Risk if not approved:** a provisional run could be shown without the label.
- **Recommended reviewer qualifications:** project owner; QA reviewer.
- **Production certification impact:** any support statement based on the provisional corpus must say so; blocks removal of the provisional label.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSE-003: performance cost of running the knowledge rules
- **Original task/requirement ID:** 006 SC-006, T090; 003 SC-007 (benchmark baseline).
- **Component:** parse caches in `parsers/python/document.py`, `parsers/xml/document.py`, `parsers/python/spans.py` (`all_nodes`); `rules/python/generic.py`.
- **What needs human review:** the analysis benchmark (300 generated modules, 9,000 files, 14.0 to 19.0; `tests/benchmarks/bench_analyze.py`) rose from the recorded P2 baseline of about 1.1 s to about 10 to 11 s on this machine (101 s before the parse and AST caches). The largest golden module analyses in well under 1 s (SC-006 limit 10 s). The caches keep the most recent 16 parses by `(path, text)`; parsed documents are treated as read-only.
- **Why:** each of about 60 bound rules re-reads every file of its kind; P9 sets the enforced budgets.
- **Evidence and test results available:** `test_largest_golden_module_analysis_is_fast`; benchmark is opt-in (`ODOOFLUX_BENCH=1`, passes).
- **Risk if not approved:** LOW to MEDIUM for large repositories; not a correctness risk unless a detector mutates a parsed tree (none does).
- **Recommended reviewer qualifications:** maintainer who owns performance budgets.
- **Production certification impact:** none for framework completion; a P9 budget could require further optimisation.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSF-003: dry run computes edits in memory (WSD-05 follow-up)
- **Original task/requirement ID:** 009 T019, T026 follow-up; REQ-REP-004; FR-001 (dry run writes nothing); SC-005 unchanged.
- **Component:** `RunOptions.computes_edits` in `src/odooflux/core/orchestrator/run.py`; `cli/report_outputs.py` (note now only for analyze).
- **What needs human review:** that a dry run now runs the transforming rule step in memory only and reports `planned_files`; fix and write behaviour, backups and promotion are unchanged and still gated on `writes`. Confirm no consumer treated an empty dry-run `edits` list as meaningful.
- **Why:** this changes what a dry run does internally, although it writes nothing.
- **Evidence and test results available:** `tests/integration/reporting/test_dry_run_diff.py` (non-empty, module untouched, patch equals write-mode patch, applies with `patch -p1` to a pristine copy, analyze still empty); `tests/regression/test_p0_safety_readonly.py`.
- **Risk if not approved:** LOW.
- **Recommended reviewer qualifications:** maintainer familiar with the orchestrator and the P0 safety guarantees.
- **Production certification impact:** none.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-02: budgets approver and headroom
- **Original task/requirement ID:** 010 T002; REQ-PRF-001, REQ-PRF-004.
- **Component:** `tests/benchmarks/budgets.json`, `baseline.json`, `REFERENCE_MACHINE.md`.
- **What needs human review:** the headroom factor (1.5 on wall time and peak RSS, 1.0 on files parsed), the reference machine, and whether CI uses the same runner class. `approved_by` is `PENDING_HUMAN_REVIEW` on every row.
- **Why:** budgets come from measured medians of this machine, not from the P2 baseline (different corpus, predates knowledge rules); whether the remaining slowdown is acceptable is a product decision (see ORIG-010-T002-T014).
- **Evidence and test results available:** `tests/benchmarks/test_run_benchmarks.py`; 300-module run PASS; `results/profile-summary-2026-11-07.md`.
- **Risk if not approved:** budgets set too loose hide regressions; too tight fail on other runners.
- **Recommended reviewer qualifications:** maintainer who owns CI and performance goals.
- **Production certification impact:** blocks declaring the OBJ-007 scale requirement certified.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### WSG-06: contract changes in P9 (bullet group; no sub-ID in fragment)
- **Original task/requirement ID:** not stated in fragment (010 P9 contract changes).
- **Component:** audit log; parallel mode; `--incremental`.
- **What needs human review:** (a) audit log path is `log/audit.jsonl` (TST-003-030 limits analysis runs to `state.json` and `log/`); action `module_blocked` added; the last line of a chain is not tamper-evident. (b) parallel mode covers analysis and dry run only; fix mode stays serial; it needs `fork` (Linux, macOS). (c) `--incremental` serves analysis and dry run only; it never serves a fix run.
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** maintainer of the orchestrator.
- **Production certification impact:** none unless rejected.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

### E. Open technical issues found by automated review (AR-*)

Each AR item is listed as the fragment states it. "Resolved" entries still carry a human review point where the fragment says so.

#### AR-R2-1: legacy `--ai-fix` and the kill switch (RESOLVED technically)
- **Original task/requirement ID:** not stated in fragment. Source: automated review R2, finding 1.
- **Component:** `resolve_ai` (legacy `--ai-fix` path); `ai/providers/legacy_anthropic.py:21`.
- **What needs human review:** decide whether the legacy `--ai-fix` path stays, is gated by D-08 authorization, or is removed. Also `legacy_anthropic.py:21` hardcodes `CLAUDE_MODEL = "claude-sonnet-4-6"`.
- **Why:** finding: `--ai-fix` (legacy whole-file Anthropic path) ignored `ODOOFLUX_AI_DISABLE_EXTERNAL` and `--ai-disable-external`. Resolution: `resolve_ai` now refuses `--ai-fix` while the kill switch is on. The legacy path still has no data-category authorization and no catalog; it sends whole files with `--api-key` or `ANTHROPIC_API_KEY`.
- **Evidence and test results available:** tests `LegacyAiFixKillSwitchTests` (written red first).
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** security reviewer.
- **Production certification impact:** mandatory before certifying AI safeguards for the legacy flag.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R3-1: manifest-less directory reported as clean (RESOLVED in output; exit code open)
- **Original task/requirement ID:** not stated in fragment. Source: automated review R3, defect 1.
- **Component:** legacy terminal output; default legacy exit-code mapping (see WSD-04).
- **What needs human review:** the owner's decision on the default exit-code mapping. Still open: under the default legacy mapping, a manifest-less run exits 0. The v1 mapping (`--exit-codes v1`) gives BLOCKED = 4 but breaks two existing tests (WSD-04).
- **Why:** the legacy terminal no longer prints "Module looks clean" when `__manifest__.py` is absent; it says L3 could not run and nothing was verified (regression test `tests/regression/test_no_manifest_not_clean.py`).
- **Evidence and test results available:** `tests/regression/test_no_manifest_not_clean.py`.
- **Risk if not approved:** exit code 0 can be read as success by CI.
- **Recommended reviewer qualifications:** project owner (policy decision on the default mapping).
- **Production certification impact:** mandatory decision before production, because exit code 0 can be read as success by CI.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R3-2: support statement in an installed package (RESOLVED technically)
- **Original task/requirement ID:** not stated in fragment. Source: automated review R3, defects 2 and 3.
- **Component:** support-statement command (a release-process command).
- **What needs human review:** confirm that refusing outside a source checkout is the intended scope, or ask for the statement to be generated from data that ships in the wheel.
- **Why:** the command previously wrote a statement without PROVISIONAL labels when run from an installed package; it now refuses (exit 2).
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** not stated in fragment.
- **Production certification impact:** not stated in fragment.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R3-3: minor behaviour oddities (open, technical)
- **Original task/requirement ID:** not stated in fragment. Source: automated review R3.
- **Component:** not stated in fragment (second `--fix`, rollback, `kbi_demo`, `--api-key` warning).
- **What needs human review:** (a) a second `--fix` on an already fixed copy reports 25 open findings versus 24 after the first fix; (b) repeating a rollback reports "conflict" three times with exit 1 instead of "already rolled back"; (c) `kbi_demo` keeps `expected/` inside the module directory, so a whole-directory copy also scans it (documented; use a copy of the input only); (d) the `--api-key` deprecation warning is printed twice.
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** low.
- **Recommended reviewer qualifications:** engineer.
- **Production certification impact:** none block certification; the first two should be fixed before release.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R1-1: test harness `sys.path` ordering (open, technical)
- **Original task/requirement ID:** not stated in fragment. Source: automated review R1, finding 1.
- **Component:** `tests/_support/p0.py:22-24`.
- **What needs human review:** `tests/_support/p0.py` puts the repo `src` first, so `PYTHONPATH=<copy>/src` is ignored when tests run from the real repo. Mutation checks are valid only on a full repo copy (tests and src).
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** false assurance for anyone using the `PYTHONPATH` recipe.
- **Recommended reviewer qualifications:** not stated in fragment.
- **Production certification impact:** not stated in fragment; fix before relying on mutation testing in CI.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R1-2: weakest test (open, technical)
- **Original task/requirement ID:** not stated in fragment.
- **Component:** `tests/integration/ai/test_ai_disabled.py:54`.
- **What needs human review:** the test asserts through a mock that raises `AssertionError`; it would pass if the pipeline swallowed that exception. The kill switch and the review_required-plus-fixer rules are caught only at integration or rules level, not unit level.
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** not stated in fragment.
- **Production certification impact:** not stated in fragment.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R2-2: evidence tool and evidence coverage (open, technical)
- **Original task/requirement ID:** part of ORIG-006-T025 certification. Source: automated review R2, finding 2.
- **Component:** `tools/verify_evidence.py`; evidence IDs EV-500 to EV-559.
- **What needs human review:** (a) `tools/verify_evidence.py` with no arguments checks nothing and prints "FAILURES 0"; run it with explicit file arguments or an EV range. (b) EV-540 to EV-547 point at a directory (`addons`) and cannot be verified by the tool (report 404 for a directory location); review these by hand. (c) only 26 of the IDs in EV-500..559 exist. (d) seven shared rules carry empty evidence by the documented waiver (`not_applicable_reason`, all DETECT_ONLY). (e) evidence quotes were not re-read against upstream by the reviewer; a human check of a sample is advised.
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** Odoo developer.
- **Production certification impact:** part of T025 certification (ORIG-006-T025 is mandatory for production certification of any path).
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-R2-3: owner approvals recorded as assertions (informational)
- **Original task/requirement ID:** ADR-011, ADR-017, ADR-018, ADR-019 approval lines; ADR-019 defaults OD-2, OD-4, OD-5, OD-6, OD-7, OD-8.
- **Component:** `docs/planning/ARCHITECTURE_DECISIONS.md`.
- **What needs human review:** the ADR lines for ADR-011, 017, 018 and 019 say "approved by the project owner". They record the owner's messages in this project; no tool can verify them. The ADR-019 defaults for OD-2, OD-4, OD-5, OD-6, OD-7 and OD-8 were assumed by the orchestrator, not stated by the owner, and need confirmation.
- **Why:** not stated in fragment (no tool can verify these approvals).
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** project owner.
- **Production certification impact:** confirms scope decisions.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

#### AR-STALE: stale planning documents (open, documentation)
- **Original task/requirement ID:** not stated in fragment.
- **Component:** `docs/planning/EXECUTIVE_SUMMARY.md`.
- **What needs human review:** the file still shows the original phase table, "No functional code was written" and 55 evidence records. It predates implementation and is superseded by `FRAMEWORK_COMPLETION_REPORT.md` and `IMPLEMENTATION_STATUS.md`.
- **Why:** not stated in fragment.
- **Evidence and test results available:** not stated in fragment.
- **Risk if not approved:** not stated in fragment.
- **Recommended reviewer qualifications:** maintainer.
- **Production certification impact:** documentation accuracy only.
- **Decision:** `PENDING (human)` | **Reviewer name:** | **Review date:**

## 4. Production certification status

**Production certification is NOT granted.** Nothing in this register is approved. Framework implementation may be declared complete without it (ADR-019 rule 6). Production certification remains blocked while any mandatory item is open.

- **Mandatory for production certification (Yes): 15 items.**
  - ORIG-006-T025, ORIG-006-T035-T044, ORIG-006-T059, ORIG-008-T029, ORIG-007-T029-T031, ORIG-010-T023
  - WSG-01, WSC-AI-1, WSC-AI-2, FHR-A-002, WSE-002, WSF-001
  - AR-R2-1, AR-R3-1, AR-R2-2
- **Decision (fragment leaves the blocking status to a human or the owner): 16 items.**
- **No production certification impact stated: 21 items.**
- **Open technical items (not human review), carried from ws-g and not register items:** T008 release checklist; T020 and T021 failure injection; T022 release gates; T024 quickstart record. These must be completed before the Yes items in WSG-01 can be signed.
- **Resolved technically, review still wanted:** AR-R2-1, AR-R3-1, AR-R3-2, WSD-05.
- **Open technical (no sign-off needed to close):** WSC-AI-5, AR-R1-1, AR-R1-2, AR-R2-2, AR-R3-3, AR-STALE.

Reviewer name and review date fields are empty for every item. No reviewer has signed.

---

## Appendix: stabilization round 2 items (2026-11-07)

Full text in `docs/reviews/fragments/ws-i-orchestrator.md`. All decisions below are **PENDING (human)**; reviewer name and date are empty. No agent recorded approval.

| ID | Item | Mandatory for production | Decision |
|---|---|---|---|
| AR-R4-1 | Legacy retire rows: remaining WSE-001 decisions; `Manifest Version` INFO stays open after `--fix`; `Version Mismatch` after a fix | Yes | PENDING (human) |
| AR-R4-2 | Rollback idempotency accepted | No | PENDING (human) |
| AR-R4-3 | AI: no real rule `ai_eligible` until live-provider evidence; owner direction on per-category grants applied | Yes | PENDING (human) |
| AR-R4-4 | Exit-code default (D-10, WSD-04) | Yes | PENDING (human) |
| AR-R5-1 | Rollback after double write: end-to-end proof; write-then-unlink for renames | No | PENDING (human) |
| AR-R5-2 | Pre-12.0 retire rows: gate fixers too? | No | PENDING (human) |
| AR-R5-3 | Shared AST immutability convention | No | PENDING (human) |
| AR-R4-5 | Performance: about 6x slower than P2 baseline; round 2 gained about 5%; shared per-file AST/XML index needed for 2x (docs/reviews/automated/D-performance.md) | No | PENDING (human) |

### Appendix addendum: documentation round (2026-11-07)
Code defects found while documenting (tracebacks for `plan` with bad versions, `rollback` unknown run ID or `--no-backup` run, missing `--addons-path`; planner not blocking RESEARCH_SEEDED; FIX_ENABLED rules citing review-only evidence; L4/L5 not wired into `migrate`) are listed in `docs/reviews/automated/DOC-verification.md`. All are PENDING (human) triage; none was changed in this round.

## Appendix: KAP (feature 011)

Full text for each item is in [`docs/reviews/fragments/kap.md`](fragments/kap.md). Every item is **PENDING (human)**; reviewer name and review date are empty. No agent recorded approval, and nothing here is certified or production-ready. Owner-decision defaults are assumed recommendations (ADR-020, research.md), not decisions.

| ID | Item | Mandatory for production | Decision |
|---|---|---|---|
| KAP-OD-K1 | kb-home location and `ODOOFLUX_KB_HOME` (OD-K1) | Decision | PENDING (human) |
| KAP-OD-K2 | Package container: ZIP, DEFLATE vs stored (OD-K2) | Decision | PENDING (human) |
| KAP-OD-K3 | Unverified FIX_ENABLED on import: refuse or downgrade (OD-K3) | Decision | PENDING (human) |
| KAP-OD-K4 | Report schema bump and built-in release in reports (OD-K4; note 45, 60) | Decision | PENDING (human) |
| KAP-OD-K5 | Package authenticity: digest pin only (OD-K5) | Decision | PENDING (human) |
| KAP-OD-K6 | Enterprise and OCA/OpenUpgrade scope (OD-K6; note 35) | Decision | PENDING (human) |
| KAP-OD-K7 | Audit log reuse (OD-K7; note 3) | Decision | PENDING (human) |
| KAP-OD-K8 | Named benchmark sets for recall (OD-K8) | Decision | PENDING (human) |
| KAP-OD-K9 | Redaction module (OD-K9; note 57) | Decision | PENDING (human) |
| KAP-OD-K10 | Activating PARTIAL releases (OD-K10) | Decision | PENDING (human) |
| KAP-OD-K11 | Rule history sidecar; built-in duplicate checks opt-in (OD-K11) | Decision | PENDING (human) |
| KAP-OD-K12 | Revisit SQLite and the threshold (OD-K12) | Decision | PENDING (human) |
| KAP-OD-K13 | Built-in FIX_ENABLED rules in a built release (notes 4, 32) | Decision | PENDING (human) |
| KAP-M8 | Weakest declared step for release completeness (contracts/coverage-and-gates.md) | Decision | PENDING (human) |
| KAP-AI-AUDIT | Audit trail for AI proposals (note 55) | Decision | PENDING (human) |
| KAP-DEACTIVATE | Meaning of `deactivate` (note 6) | Decision | PENDING (human) |
| KAP-TRUST-ORIGIN | Trusted-origin limit and external trust anchor (notes 14, 16, 36, 50) | Decision | PENDING (human) |
| KAP-AUTO-ACCEPT | Pipeline auto-accepts verified candidates without human review | Decision | PENDING (human) |
| KAP-CORPUS-CERT | SC-005-style certification of the first real-corpus build (not yet run) | Yes | PENDING (human) |
| KAP-LIVE-TESTS | Opt-in live and Docker tests never run (`ODOOFLUX_KAP_*`) | Decision | PENDING (human) |
| KAP-JS-ADAPTER | JS structural extractor: tree-sitter branch unverified | Decision | PENDING (human) |
| KAP-GIT-IDENTITY | `insteadOf` identity gap; git versions other than 2.43.0 (notes 50, 51) | Decision | PENDING (human) |
| KAP-ROOT-GUARD | Sign-off on the 21-module knowledge-root guard allow-list (notes 38, 63) | Decision | PENDING (human) |
| KAP-FE-1 | Approval identity deferred (FE-1; not a blocker) | No | PENDING (human) |

Totals: 24 items. Mandatory: Yes 1, Decision 23, No 1.

### KAP closure additions (feature 011)
Full text in `docs/reviews/fragments/kap.md`. All PENDING (human); no agent recorded a decision.

| ID | Item | Mandatory for production | Decision |
|---|---|---|---|
| KAP-CL-1 | Mistyped or empty `--kb-home` runs the built-in release (contract-consistent; report names it) | No | PENDING (human) |
| KAP-CL-2 | Unofficial evidence cannot be packaged; registry schema lacks `repository` | No | PENDING (human) |
| KAP-CL-3 | Smaller KAP behaviours to confirm (show re-hash, extract exit, generate refusals, resume, downgrade id, conflicts history) | No | PENDING (human) |
