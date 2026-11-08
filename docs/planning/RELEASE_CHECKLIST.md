# Release Checklist

Status: TEMPLATE. Technical evidence links point at artefacts that exist today. **No item here is signed off.** Sign-off fields stay `PENDING_HUMAN_REVIEW` until a human fills them in the final review register ([FINAL_HUMAN_REVIEW_REGISTER.md](../reviews/FINAL_HUMAN_REVIEW_REGISTER.md), item WSG-01). Owners are roles, not named people.

| # | Gate | Requirement | Evidence (technical) | Command | Owner role | Human sign-off |
|---|---|---|---|---|---|---|
| 1 | Full default suite passes, 0 failures | REQ-TST-001 | final integration run, recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .` | Release engineer | PENDING_HUMAN_REVIEW |
| 2 | RTM complete: every REQ is TESTED, DEFERRED_KB (with backlog ID), or has a record | REQ-TST-005 | `tests/unit/release/rtm_tools.py`, [RTM](REQUIREMENTS_TRACEABILITY_MATRIX.md), [KB backlog](KNOWLEDGE_BASE_BACKLOG.md) | `PYTHONPATH=src python3 tests/unit/release/rtm_tools.py` | Release engineer | PENDING_HUMAN_REVIEW |
| 3 | Every resolved F-finding has a citing regression test | REQ-TST-005 | `tests/unit/release/test_regression_citations.py` | unittest on that module | Release engineer | PENDING_HUMAN_REVIEW |
| 4 | Benchmarks within budgets | REQ-PRF-001, REQ-PRF-004 | `tests/benchmarks/budgets.json` (approver field `PENDING_HUMAN_REVIEW`), `tests/benchmarks/results/` | `tests/benchmarks/run_benchmarks.py` | Performance owner | PENDING_HUMAN_REVIEW (WSG-02) |
| 5 | Secret scan: no canary in any artefact | REQ-SEC-003, REQ-AI-008 | `tests/integration/hardening/test_secret_scan.py` | unittest on that module | Security reviewer | PENDING_HUMAN_REVIEW |
| 6 | Audit log: one entry per action type, valid hash chain | REQ-SEC-005 | `tests/integration/hardening/test_audit_log.py`, `specs/010-hardening-release/contracts/audit-log.md` | unittest on that module | Security reviewer | PENDING_HUMAN_REVIEW |
| 7 | Failure injection: originals intact or restorable | REQ-SAF-005, REQ-SAF-008, REQ-SAF-009 | `tests/integration/hardening/test_failure_injection.py` (T020/T021) | unittest on that module | Safety reviewer | PENDING_HUMAN_REVIEW |
| 8 | Release gates: synthetic version needs no core edit; cross-renderer counts agree | REQ-ARC-003, REQ-REP-001 | `tests/integration/hardening/test_release_gates.py` | unittest on that module | Release engineer | PENDING_HUMAN_REVIEW |
| 9 | Support statement generated and current | REQ-VER-003 | [SUPPORT_STATEMENT.md](SUPPORT_STATEMENT.md) | `python -m odooflux support-statement --check` | Product owner | PENDING_HUMAN_REVIEW (WSG-04) |
| 10 | Wheel contains every runtime asset; clean-venv install works | FC amendment A-10 (no REQ) | `tests/integration/packaging/` (install test opt-in `ODOOFLUX_PACKAGING_INSTALL=1`) | unittest on that package | Release engineer | PENDING_HUMAN_REVIEW |
| 11 | Knowledge base valid; matrix up to date | REQ-EVD-002 | `knowledge validate`, `knowledge matrix --check` | both commands | Knowledge owner | PENDING_HUMAN_REVIEW |
| 12 | AI safeguards: zero calls when off, authorization, kill switch, no fallback | REQ-AI-001 to REQ-AI-008 | `tests/{unit,integration,contract}/ai` (live tests opt-in, not run) | unittest discover on `tests/*/ai` | AI/security reviewer | PENDING_HUMAN_REVIEW |
| 13 | Runtime validation run recorded (opt-in, Docker) | REQ-VAL-004 | `specs/008-runtime-behavioral-validation/quickstart.md` verification log | `ODOOFLUX_RUNTIME_TESTS=1 ...` | Runtime owner | PENDING_HUMAN_REVIEW |
| 14 | Provisional corpus reviewed (expected outputs are PROVISIONAL until then) | REQ-TST-003 | `tests/golden_fixtures/17.0/**/PROVISIONAL.md` | n/a (human) | Odoo migration expert | PENDING_HUMAN_REVIEW |
| 15 | Maintainer release sign-off | REQ-TST-005 | all items above | n/a (human) | Maintainer | PENDING_HUMAN_REVIEW (T023) |

Production certification stays blocked while any row above is PENDING_HUMAN_REVIEW and marked mandatory in the register.
