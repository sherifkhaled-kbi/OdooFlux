# Owner option note: version-prefix fix opt-out (REQ-MAN-002, F-MAN-1)

Status: input for the owner. No decision is taken here. D-A3 remains NOT APPROVED (ADR-018). Detect-only (D-A2, FR-019) stays the current state.

## Facts from repo documents

- REQ-MAN-002 (`docs/planning/PRODUCT_REQUIREMENTS.md`): version bumps MUST preserve the module's own version suffix unless the user opts out. Example: `14.0.2.3.1` to `19.0.2.3.1` by default.
- F-MAN-1 (`docs/planning/CURRENT_ARCHITECTURE_AUDIT.md`): suffix discarded, CONFIRMED_CURRENT by RUN, code at `odooflux.py:763-782`.
- FR-019 (`spec.md`): promotion to FIX_ENABLED needs a separate owner decision on the REQ-MAN-002 opt-out. No Odoo-series evidence exists or is claimed.
- SC-005 / FR-022: review_required rules make no automatic edits.

## Options

**A. Detect-only, no opt-out (status quo, D-A2).** Flag the prefix mismatch as review_required; the user edits the manifest.
- Pro: no edits to user code; no semantic-versioning assumptions; matches FR-019 today.
- Con: does not meet REQ-MAN-002's default-preserve wording; users do the bump by hand.

**B. Opt-in fix (per run).** A run parameter (e.g. `--rewrite-version-prefix`) promotes the rule to FIX_ENABLED for that run only. Default stays detect-only.
- Pro: explicit consent per run; the default never edits; an opt-out is not needed because nothing is on by default.
- Con: REQ-MAN-002 says "unless the user opts out", which implies default-on. Owner must confirm that opt-in satisfies the requirement, or amend REQ-MAN-002.
- Needs FR-017 run_params (already D-A1) and a new FIX_ENABLED gate.

**C. Default-on fix with opt-out (literal REQ-MAN-002).** Rewrite unless the user disables it.
- Pro: matches REQ-MAN-002 wording exactly.
- Con: automatic manifest edits on review-required evidence; conflicts with FR-019 and D-A3; highest risk of wrong versions for custom modules.

## Risks

- Semantic versioning of custom modules: the suffix is the module's own scheme. Whether every custom version follows `<series>.<x.y.z>` is unknown. A rewrite that assumes it can silently produce a wrong version. (To verify on a sample of real custom manifests.)
- OCA and third-party conventions: whether OCA modules use the same `<series>.<suffix>` form, and whether their upgrade practice expects bumps, is not established in repo documents. (To verify against OCA contribution docs; not cited here.)
- Version ordering: a rewritten version may be lower or equal to an installed version, which can block upgrades. (To verify in Odoo's upgrade behaviour; not established here.)
- No Odoo-series evidence exists for the prefix rule (FR-019); a fixer would ship without official evidence.

## Recommendation

Keep Option A now, consistent with D-A3 (not approved). If reconsidered, Option B is the only candidate: opt-in per run, never default, and the owner first resolves whether REQ-MAN-002 "opts out" is satisfied by opt-in. Option C should not be pursued without a new owner decision.

## Evidence and golden tests required before reconsidering

1. Official or pinned evidence for the version format per series, with SHA and line match (FR-022).
2. A sample of real custom manifests (synthetic plus at least one anonymised real set) classified by pattern: matches, ambiguous, non-standard. Decision rule: fix only the unambiguous pattern; everything else stays review_required.
3. Golden fixtures: suffix preserved for `14.0.2.3.1` to `19.0.2.3.1`; no-prefix and non-standard versions produce a finding, not an edit; idempotence (second run is a no-op); opt-in off means no edit.
4. Non-regression: T061 and T072 tests pass; coverage test (FR-002/SC-001) covers the new rule; SC-005 holds when the flag is absent.
5. Owner sign-off on D-A3 and on the REQ-MAN-002 opt-out wording.
