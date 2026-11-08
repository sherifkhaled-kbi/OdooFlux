# Human review fragment: workstream H

Nothing here records an approval.

## WSH-T020: failure-injection fix review (F-INJ-1)

- Task / requirement: 010 T020, T021, REQ-SAF-005. Certification: PENDING_HUMAN_REVIEW.
- Component: `src/odooflux/core/jobs/promote.py` (`_restore`), `tests/integration/hardening/test_failure_injection.py`.
- What to review: restore now skips unchanged files and blocks the module (with a rollback hint) when a restore write fails.
- Why: safety-path change in customer-file handling; only a human reviewer certifies it.
- Evidence and tests: `tests/regression/test_failure_injection_findings.py` (F-INJ-1); 13 injection tests.
- Reviewer qualifications: maintainer familiar with the promote and rollback contracts.
