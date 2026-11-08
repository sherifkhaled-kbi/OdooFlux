# Phase Handoff P6 — Optional, Provider-Neutral AI Assistance

## 1. Phase ID
P6 — Spec Kit feature [`specs/007-ai-assistance`](../../../specs/007-ai-assistance/)

## 2. Phase title
Optional, Provider-Neutral AI Assistance

## 3. Objective
Escalate only AI-eligible findings without deterministic fixes to a configured provider. Send minimal regions with evidence, and accept results only as validated `Edit`s. Enforce budgets, cache verified results, and report usage. AI stays off by default.

## 4. Requirements covered
REQ-AI-001…008, REQ-SEC-003 (AI artefacts), REQ-SEC-004. Traceability: [spec.md](../../../specs/007-ai-assistance/spec.md) FR-001…FR-013.

## 5. Repository context
- The legacy AI path is `ai_fix_all_modules` in `odooflux.py` (whole-file bundle, single request). Its defects are F-AI-1…F-AI-7 in [../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md).
- Target code goes in `src/odooflux/ai/` ([PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md)).
- Design: [AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md](../AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md); contracts: [CONTRACTS.md § AIProvider](../architecture/CONTRACTS.md#aiprovider), [specs/007…/contracts/](../../../specs/007-ai-assistance/contracts/).

## 6. Prerequisites
P3 and P5 exit criteria met ([IMPLEMENTATION_ROADMAP.md](../IMPLEMENTATION_ROADMAP.md#p6--ai-assistance)). D-08 decided (default: AI off, no default provider, explicit consent flag). D-10 decided.

## 7. Dependencies
P2 engine (Edit, re-scan), P3 evidence records, P5 rule metadata (`ai_eligible`, `review_required`), P4 parsers (region selection).

## 8. Expected files and components
`src/odooflux/ai/providers/{types,registry,fake,transport,credentials,anthropic,openai_compatible}.py`, `ai/prompts/builder.py` + `templates/v1/`, `ai/caching/cache.py`, `ai/usage/{budgets,usage}.py`, `ai/escalation.py`, `cli/ai_options.py`; tests under `tests/{unit,contract,integration,regression,benchmarks}/ai/`.

## 9. Interfaces and contracts
`AIProvider`, `AIRequest`, `AIResponse` ([contracts/ai-provider.md](../../../specs/007-ai-assistance/contracts/ai-provider.md)); budgets and cache ([contracts/budget-and-cache.md](../../../specs/007-ai-assistance/contracts/budget-and-cache.md)); `Edit` and `Finding` from [CONTRACTS.md](../architecture/CONTRACTS.md).

## 10. Official evidence requirements
AI never creates rules or evidence (FR-013). Prompts include only evidence records that already exist in the knowledge base (`EV-…` with pinned SHA). No provider model IDs or prices may be hardcoded or asserted as facts. They are configuration.

## 11. Detailed implementation tasks
See [specs/007-ai-assistance/tasks.md](../../../specs/007-ai-assistance/tasks.md) (T001–T034).

## 12. Acceptance criteria
Spec SC-001…SC-005. Roadmap exit:
1. Provider contract tests pass for the fake provider and each shipped adapter.
2. Budgets, truncation, caching, and protected-identifier rejection are tested.
3. Benchmarks are recorded.
4. AI is off by default.

## 13. Unit tests
TST-007-002, -005, -006, -007, -008, -009, -011, -012, -014.

## 14. Integration tests
TST-007-003, -004, -010, -013; contract tests TST-007-001, -015 (opt-in live).

## 15. Runtime tests where applicable
Not applicable (AI edits are runtime-validated by P7 when enabled).

## 16. Negative test cases
Truncated response, schema mismatch, syntax-invalid patch, renamed field/`_name`/`_inherit`, removed import, changed XML ID, out-of-region edit, over-budget request, missing consent, contract-version mismatch, prompt-injection fixture, tampered cache entry.

## 17. Security requirements
Credentials only from environment or a secrets file outside scanned paths, and redacted everywhere. Customer code is delimited as data. AI output is never treated as instructions. Cache and debug files stay under the state dir. An explicit consent flag is required before sending code ([SECURITY_AND_SAFETY.md](../SECURITY_AND_SAFETY.md)).

## 18. Performance requirements
Zero provider calls when disabled. A cache hit makes no network calls. Budgets are checked before sending. Baseline metrics are recorded (T032); targets come from that baseline.

## 19. Backward compatibility
The legacy `--ai-fix`/`--api-key`/`--ai-verbose` options are mapped or deprecated per D-10. `--api-key` keeps working with a warning during the window (removed in P9). `ANTHROPIC_API_KEY` env var continues to work through the Anthropic adapter's credential config.

## 20. Prohibited changes
No provider imports in `core/`. No whole-file AI rewrites. No AI-created rules or evidence. No changes to validation layers to accommodate AI. No default provider without D-08 approval.

## 21. Definition of Done
All tasks checked with "Done when" evidence. All TST-007-* pass (live tests may skip with reason). The quickstart is recorded. The benchmark baseline is committed. The RTM is updated for REQ-AI-*.

## 22. Implementation agent instructions
1. Confirm `.specify/feature.json` contains `{"feature_directory": "specs/007-ai-assistance"}`. Set it only when starting this phase.
2. Read spec.md, plan.md, research.md, data-model.md, contracts/, and tasks.md in that order.
3. Execute with the installed Spec Kit command `/speckit-implement` (do **not** run during planning). Follow tasks in order, tests first.
4. Stop and request clarification if a task requires changing contracts owned by P2 or rule metadata owned by P5.

## 23. Expected verification evidence
Test run logs (offline suite), opt-in live contract results or skip reasons, benchmark baseline report `docs/planning/reports/AI_BENCHMARK_BASELINE.md`, quickstart results, and RTM rows for REQ-AI-001…008 and REQ-SEC-004 with test IDs.

## 24. Handoff checklist
- [ ] Prerequisites P3, P5 verified; D-08 and D-10 decided
- [ ] feature.json points at 007
- [ ] All TST-007-* written first and failing before implementation
- [ ] All tasks done with evidence
- [ ] AI off by default verified (TST-007-003)
- [ ] Benchmark baseline recorded
- [ ] RTM and SPECKIT_READINESS updated
