# KAP future enhancements (not current-release blockers)

| ID | Enhancement | Why deferred | Notes |
|---|---|---|---|
| FE-1 | Approval identity: authenticated approver, identity verification, RBAC, human approval workflow for promoting a rule to FIX_ENABLED and for activating a knowledge release | Owner decision (this release): out of scope. No technical task, release activation or KAP completion depends on authenticated approval. | Today `knowledge rule promote` takes an approval reference that is recorded in the rule history for compatibility. It is metadata, **not authenticated approval**, and must not be presented as such in reports or documentation. The technical gates stay in force: provenance verification (gate 1), rule validation, conflict detection (gate 4), FIX_ENABLED eligibility and package integrity. Do not treat the recorded reference as human certification (ADR-019 register items stay PENDING (human)). |
