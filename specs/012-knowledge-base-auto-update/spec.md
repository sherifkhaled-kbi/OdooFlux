# Feature Specification: Knowledge Base Auto-Update

**Feature Branch**: `012-knowledge-base-auto-update` (no git branch; work is uncommitted in the working tree of `main`)
**Created**: 2026-11-09
**Status**: Implemented in the working tree; verification pending. Final regression and the acceptance matrix are owned by [verification.md](verification.md) (written by the feature owner after the final regression run).
**Plan**: [plan.md](plan.md) (sections 1 to 8 and Addenda A to E; Addendum B is the unified-knowledge-base decision, Addendum D records a design BLOCK)
**Task ledger**: [tasks.md](tasks.md)
**Predecessor**: [Feature 011, Knowledge Acquisition Pipeline](../011-knowledge-acquisition-pipeline/spec.md) (its contracts are changed only where listed in [Trust-model changes](#trust-model-changes))
**Input**: Keep the offline-first knowledge base current with the official Odoo Community and Enterprise sources. An operator checks for new upstream revisions, acquires them, builds a new knowledge release, and activates it only when the release passes the trust and capability checks. Enterprise knowledge is optional, never leaves the machine, and is carried forward honestly when credentials are absent.

## Scope and vocabulary

| Term | Meaning |
|---|---|
| Source | One official repository at one branch (`<major>.0`), for one family: `community` (`odoo/odoo`) or `enterprise` (`odoo/enterprise`). Entries of [catalog.json](../../src/odooflux/knowledge/update/catalog.json). |
| Source family | `community` or `enterprise`. A family is a source identity label, not a separate knowledge base. |
| Unified knowledge base | One active Knowledge Release that may contain Community and Enterprise sources. One active pointer, one release id and digest, one rule registry, one `migrate` pipeline (plan Addendum B). |
| Installed release | The release named by the active pointer in the kb-home. `none` means built-in knowledge only. |
| Planning fingerprint | The fingerprint of the inputs an update would build, from remote metadata. It proves nothing about acquired bytes. |
| Build fingerprint | The fingerprint including the verified snapshot digest of every acquired or carried source. Only this form is persisted as a build record. |
| Carry-forward | Re-using an installed Enterprise source's verified snapshot, unchanged, in a new release, when credentials are missing or the source cannot be read. |
| Internal release | A release with `confidentiality: "internal"` in `release.json`. Derived from the sources, never self-declared. It is never exported. |
| Public release | A release with no Enterprise-derived source. Keeps the Feature 011 rules. |
| Fix certification | A machine-checked record (`odooflux.fix-certification/1`) that a fix template's transformation reproduces its expected outputs. It is not a human approval. |
| `auto-cert:` reference | The approval label of an automatically certified row: `auto-cert:<policy_version>:<record_digest>`. |
| kb-home | Local directory holding releases, the active pointer, the audit log, the update history (`updates/history.jsonl`), the managed cache and the staging directory. |

Non-goals: see [Non-goals](#non-goals).

## User Scenarios and Testing

### US1 - Operator checks for upstream changes without changing anything (P1)
An operator runs `odooflux knowledge check`. The command asks the official remotes which branch heads exist (`git ls-remote`, nothing is downloaded), compares them with the installed release and reports per-source status. It writes nothing to the kb-home.
Independent test: `tests/unit/knowledge/update/test_check_cli.py`, `test_discovery.py`.
1. Given `--offline` or `ODOOFLUX_OFFLINE=1`, When `check` runs, Then no remote is contacted, every source is `SKIPPED_OFFLINE`, and the command exits 4 (`CHECK_UNAVAILABLE`).
2. Given a new branch head for an installed Community source, When `check` runs online, Then the source is reported as changed and the adjacent transitions are listed as affected.
3. Given a new numeric major branch (for example `20.0`), When `check` runs, Then it is reported as `NEW_VERSION_DISCOVERED` and is never a supported migration target (`TRANSITION_NOT_YET_SUPPORTED`).

### US2 - Operator applies an update (P1)
An operator runs `odooflux knowledge update`. The run discovers upstream state, acquires only what changed, builds a candidate release with the unchanged 17-step pipeline, evaluates activation and, only when every rule passes, swaps the active pointer once.
Independent test: `tests/integration/kap/test_update_orchestrator.py`.
1. Given no installed release and only Community credentials, When `update` runs, Then a Community-only release is built and activated and the Enterprise sources are reported as skipped.
2. Given an unchanged upstream and an installed release, When `update` runs again, Then the outcome is `NOOP`, no release is built, and the history records a NOOP with the same build inputs.
3. Given a candidate that loses a capability (a detection rule disappears without an explicit replacement), When `update` runs, Then the outcome is `BLOCKED`, the previous release stays active and the reason names the blocking code.
4. Given a failure while the pointer is swapped, When `update` runs, Then the outcome is `ROLLED_BACK` (or `FAILED` when the pointer cannot be read back) and the previous release stays active.

### US3 - Enterprise knowledge without credentials (P1)
An operator without Enterprise access runs `update` or `check`. Community knowledge is updated normally. Enterprise sources are reported as skipped for lack of credentials, and the installed Enterprise knowledge (when present) is carried forward unchanged and reported as stale and unverified, never as fresh and never as removed.
Independent test: `tests/integration/kap/test_update_orchestrator.py` (community-only update carries the Enterprise release byte-identically; rejected token is carried and reported).
1. Given no token, When `update` runs, Then the Enterprise source status is `SKIPPED_NO_CREDENTIALS` and no Enterprise fetch is attempted.
2. Given `--require-enterprise` and no token, When `update` runs, Then the outcome is `BLOCKED` and nothing is installed.
3. Given a rejected token, When `update` runs, Then the source status is `AUTH_FAILED` (distinct from `UNAVAILABLE` and from `SKIPPED_NO_CREDENTIALS`), the installed Enterprise source is carried, and Community is not blocked.

### US4 - Migration uses the unified release offline (P1)
An engineer without network runs `odooflux migrate` with an activated unified release. Dependencies of custom modules are resolved against the inventories of the source and target versions. An unresolved dependency is reported as an explicit finding and withholds fixes; it is never silently treated as Community-only.
Independent test: `tests/integration/kap/test_migrate_unified_inventory.py`.

### US5 - Enterprise content stays inside the machine (P1)
An operator who holds an internal release can read validation, refresh and ledger output, but Enterprise-derived content (evidence excerpts, paths, descriptions of Enterprise-cited evidence) does not appear in any rendered or serialised output. An internal release can never be exported, and an internal package is refused on import.
Independent test: `tests/integration/kap/test_report_confidentiality.py`, `tests/unit/knowledge/kap/test_internal_release_export.py`.

### Edge cases
- Interrupted update before activation leaves the previous pointer in force (`tests/unit/knowledge/update/test_activation.py`, fault points `verify`, `pointer`, `audit`).
- A second update run while one holds the update lock is refused (`BLOCKED` with `CONCURRENT_UPDATE`, nothing recorded).
- A tampered or truncated-by-edit history line breaks the chain at that line; `status`, `history` and `update` refuse to extend or print it (exit 1 for the read verbs).
- A retained Enterprise snapshot that is missing or whose digest no longer matches fails closed; the previous release stays active.
- A dry run reads remote metadata only (unless `--offline`), writes nothing, and takes no lock.

## Requirements

Identifiers are introduced by this spec. Each requirement names what is implemented. A requirement is not "verified" by this file; verification status is recorded in [verification.md](verification.md).

### Functional requirements

| ID | Requirement | Implemented by |
|---|---|---|
| FR-001 | The shipped source catalog lists one Community and one Enterprise entry for each of 12.0 to 19.0. The catalog is validated fail-closed and its digest is computed from the parsed document. | `knowledge/update/catalog.py`, `catalog.json` |
| FR-002 | Catalog entries never store a commit SHA. Revisions are resolved at acquisition time. | `catalog.py`, `planner.py` |
| FR-003 | Discovery issues one `git ls-remote --heads --refs` per distinct repository. Only `^[0-9]+\.0$` branches are versions. Nothing is downloaded. | `knowledge/update/discovery.py`, `remote_git.py` |
| FR-004 | `check` is read-only. It writes nothing to the kb-home and performs no network call when `--offline` or `ODOOFLUX_OFFLINE=1` is set. | `discovery.py`, `cli/kap_update.py` |
| FR-005 | A discovered version is reported as `NEW_VERSION_DISCOVERED` and is never a migration target. | `discovery.py` (`TRANSITION_NOT_YET_SUPPORTED`) |
| FR-006 | `update --dry-run` reads remote metadata like `check` (none with `--offline`) and reports the plan. It acquires, builds, installs, activates, appends history and takes no lock. | `orchestrator.py` (`_execute`, `run_update`), `cli/kap_update.py` |
| FR-007 | Remote git fetches are by commit SHA into a managed cache, with a verified commit, a fixed argv, a hardened environment (no global or system config, no credential helper, no prompts, hooks disabled, https allow-listed origins only, no submodules), a timeout and an output bound. | `knowledge/update/remote_git.py` |
| FR-008 | Enterprise credentials are attached only to calls whose validated identity is the Enterprise origin. Community calls never receive the token. The token never appears in argv, URLs, git configuration, cache files, reports, history or exceptions. | `remote_git.py`, `credentials.py`, `acquire.py` |
| FR-009 | Enterprise token sources are `ODOOFLUX_ENTERPRISE_TOKEN` or a regular, owner-only, non-symlink file named by `ODOOFLUX_ENTERPRISE_TOKEN_FILE`. No user-configured credential helper is executed. | `credentials.py` |
| FR-010 | Acquisition statuses are distinct per source: `ACQUIRED`, `CARRIED`, `SKIPPED_NO_CREDENTIALS`, `SKIPPED_OFFLINE`, `AUTH_FAILED`, `UNAVAILABLE`, `REVISION_UNAVAILABLE`, `NOT_REQUIRED`, `NOT_ATTEMPTED`. A failed Enterprise acquisition never removes installed knowledge and blocks Community only under `--require-enterprise`. | `knowledge/update/acquire.py`, `planner.py`, `orchestrator.py` |
| FR-011 | Carry-forward re-extracts a carried source from its retained verified snapshot (`RetainedSnapshotAdapter`). The snapshot is used only when its digest equals the digest recorded by the installed release and its blobs re-verify. | `knowledge/acquisition/adapters/retained.py`, `acquire.py`, `pipeline.py` |
| FR-012 | The update builds with the unchanged 17-step pipeline. Multiple source pairs per transition are allowed through `pair key` values that are unique and deterministic. | `knowledge/pipeline.py` (`BuildPlan.pairs`, `pair_key`, `_pair_keys`) |
| FR-013 | Activation is release-level and happens only through the existing atomic pointer swap, under the kb-home lock. A failed swap is recorded as `ROLLED_BACK` or `FAILED`. | `knowledge/update/activation.py` (`activate_release`), `cli/kap_release.activate` |
| FR-014 | Activation is refused on any of: `COMPLETENESS_FAILED`, `CAPABILITY_LOST`, `CAPABILITY_DOWNGRADED`, `FIX_NOT_TRUSTED`, `ENTERPRISE_COMPAT`, `INTEGRITY`. `PARTIAL` completeness activates only when none of these apply. | `activation.py` (`BLOCKING_CODES`, `evaluate`) |
| FR-015 | Capability comparison is per rule id on the executable fields (maturity, detector and fixer references and parameters, scope and execution gates). A rule removed or retired without an approved replacement is lost. | `knowledge/update/capability.py` |
| FR-016 | Semantic supersede: a removed rule may be approved for removal only when a replacement with equal semantics exists and has equal or higher maturity. The approval is recorded as `semantic-replacement/1`. | `capability.py` (`semantic_supersede_policy`, `POLICY_NAME`), `pipeline.py` (`supersede_policy`) |
| FR-017 | Trust for a `FIX_ENABLED` row is decided by one predicate used by the loader, the build, the importer and activation: a byte-identical shipped row (inherited trust, D3), or gates 1 to 5, plus its certification record when one governs the row. | `knowledge/release/safety.py` (`fix_row_trusted`, `package_fix_findings`) |
| FR-018 | A certification record is recomputed, never trusted: the verifier regenerates fixtures, runs the real primitives through the engine and compares every stored digest. A stored pass flag is refused. | `knowledge/update/certification.py`, `transformers/certify_exec.py`, `transformers/fix_templates.py` |
| FR-019 | An `auto-cert:` reference is never accepted as a human approval by `promote`. | `knowledge/authoring/promote.py` |
| FR-020 | Internal releases are never exported. `export_package` has no override option. An internal package is refused on import (P12) and by `package validate`. | `knowledge/package/confidentiality.py`, `package/builder.py`, `package/validate.py`, `cli/kap_package.py` |
| FR-021 | Enterprise source provenance entries carry `confidentiality`, `licence_id` and `licence_access` in addition to the Feature 011 fields. Enterprise classification is derived from the source kind, never from a record field. | `knowledge/release/provenance.py`, `knowledge/acquisition/sources.py` |
| FR-022 | Dependencies of custom modules are resolved over the inventories of both versions (`inventory/<version>.json`). An unresolved, conflicted or cyclic dependency is a finding, and fixes are withheld for that module. | `knowledge/update/inventory.py`, `dependencies/unified.py`, `cli/migrate.py` |
| FR-023 | Reports and command output show Enterprise-derived records by id and source id only. Stored bytes are never modified by the view. | `knowledge/release/confidentiality_view.py`, `cli/knowledge.py`, `cli/kap_rule.py`, `cli/kap_extract.py` |
| FR-024 | Update history is an append-only, hash-chained log under the kb-home lock. A broken chain blocks further appends and makes the read verbs exit 1. | `knowledge/update/history.py` |
| FR-025 | `knowledge status` and `knowledge history` read the kb-home only. They do not use the network and do not create directories. | `cli/kap_update.py`, `knowledge/update/report.py` |

### Non-functional requirements

| ID | Requirement | Implemented by |
|---|---|---|
| NFR-001 | Stdlib only for the update manager (`knowledge/update/`). Import-graph guard unchanged: the core package does not import adapters or toolkits; `builtins.py` attaches them. | `knowledge/update/*.py`, `builtins.py` |
| NFR-002 | Offline is zero network: the network gate runs before any credential or CA-bundle handling. `migrate` never networks. | `remote_git.network_allowed`, `acquire.py`, `cli/migrate.py` |
| NFR-003 | Secrets are scrubbed from every message, report, history record and audit text. `Token` never reveals its value through `repr`, `str`, pickling or copying. | `credentials.py`, `utils/redaction.py`, `report.py`, `orchestrator.py` |
| NFR-004 | Deterministic outputs: the same inputs give the same fingerprint, plan and JSON (keys sorted, canonical bytes). | `fingerprint.py`, `planner.py`, `report.py` |
| NFR-005 | Concurrency: one update at a time (`<kb-home>/updates/.update.lock`, bounded wait 5 seconds, `BLOCKED CONCURRENT_UPDATE`); fetches are serialised per identity. | `orchestrator.py` (`_update_lock`), `remote_git.py` |
| NFR-006 | Fail closed. A corrupt active release, an unreadable inventory, an unverifiable certification record or a missing provenance index stops the operation or withholds the record. Known exception: see [Residual risks](#residual-risks). | throughout |

## Architecture: one unified knowledge base

Addendum B of the plan replaced the earlier two-line design (Addendum A1). There is **one** knowledge base:

- one active pointer, one release id and digest, one rule registry, one `migrate` pipeline;
- Community and Enterprise are two source families that feed the same release;
- the release is the unit of activation; a release that holds Enterprise-derived records is internal;
- confidentiality is derived, never declared: a record is Enterprise-derived when its `source_id` is an Enterprise source in the verified provenance index.

The update flow (`knowledge/update/orchestrator.py`, `run_update`):

1. Acquire the update lock (not for a dry run). Verify the update history chain and the installed state. Nothing is fetched before this check passes.
2. Discovery (`check`): read-only remote metadata; per-source statuses.
3. Planning (`planner.plan_update`, pure): ACQUIRE, CARRY_FORWARD, SKIP per source; the pairs to build; the planning fingerprint.
4. NOOP test: the plan says NOOP **and** the build inputs equal those of the last ACTIVE or NOOP record. Otherwise build. A plan NOOP alone never skips a build.
5. Acquisition (`acquire.acquire`): fetch by SHA; carry failed non-required sources at their installed revision; SKIP and offline statuses are recorded.
6. Build: `pipeline.run_build` in `<kb-home>/staging/update/`, with `adapter_by_source` for carried sources, `emit_inventory=True`, the semantic supersede policy and the composed extract toolkit. Gate codes stop the build as `BLOCKED`; other stops are `FAILED`.
7. Activation evaluation (`activation.evaluate`): completeness, capability comparison, FIX_ENABLED trust, carried Enterprise compatibility (`inventory.carry_forward_compat`), integrity.
8. Activation (`activation.activate_release`): one atomic pointer swap through `cli/kap_release.activate`; the outcome is recorded in history.
9. Report: `UpdateResult` (schema `odooflux.knowledge-update/1`) in human or canonical JSON form.

Outcomes: `NOOP`, `ACTIVE`, `DRY_RUN`, `BLOCKED`, `FAILED`, `ROLLED_BACK`. Every outcome other than `ACTIVE` leaves the previous pointer as it was.

## Trust-model changes

These are the changes to Feature 011 contracts. Each was owner-approved in the plan (Addenda B2, C3, D3 and the certification and supersede decisions) and is pinned by the tests listed. Where the implementation differs from a planned detail, the difference is listed under [Deviations](#deviations-from-the-plan).

| # | Feature 011 contract | Change in Feature 012 | Code | Tests |
|---|---|---|---|---|
| TM-1 | Only `GIT_COMMUNITY` (and `DOCS`) are official source kinds in the registry. | `GIT_ENTERPRISE` is an official kind, with the same identity rules as `GIT_COMMUNITY` plus a licence. `ENTERPRISE_LOCAL` is refused in the catalog (retired). | `knowledge/acquisition/sources.py` (`ENTERPRISE_KINDS`, `enterprise_entry_problem`), `update/catalog.py` (`_RETIRED_KINDS`) | `tests/unit/knowledge/update/test_catalog.py`, `tests/unit/knowledge/kap/test_enterprise_provenance.py` |
| TM-2 | A release has no confidentiality marker. Enterprise-derived provenance is refused (`ENTERPRISE_DERIVED_REFUSED`). | `release.json` gains `confidentiality: "internal"`, covered by the release digest and derived from the sources. Enterprise provenance entries carry `confidentiality`, `licence_id` and `licence_access`. Public releases keep the refusal. | `knowledge/release/manifest.py`, `release/provenance.py`, `package/confidentiality.py` | `tests/unit/knowledge/kap/test_enterprise_provenance.py`, `tests/unit/knowledge/kap/test_internal_release_export.py` |
| TM-3 | Licence not checked on provenance. | Enterprise entries must carry a declared licence (form-checked, never a placeholder). Failure reports `LICENCE_UNVERIFIED`. The licence is not verified against upstream; that is a maintainer responsibility (catalog docstring). | `knowledge/acquisition/sources.py` (`LICENCE_CODE`), `release/provenance.py` | `tests/unit/knowledge/kap/test_enterprise_provenance.py`, `tests/unit/knowledge/update/test_catalog.py` |
| TM-4 | `export_package` refuses Enterprise-derived content unless `include_enterprise_derived` is passed. | The `include_enterprise_derived` parameter is removed from `export_package` (it existed at HEAD with default `False`). Internal releases are refused unconditionally (`EXPORT_REFUSED`), with no flag. The export keeps the caller-supplied canary parameter; the CLI passes none (`cli/kap_package.py`), so no Enterprise-specific canary list is added to the export path. | `knowledge/package/builder.py`, `cli/kap_package.py` | `tests/unit/knowledge/kap/test_internal_release_export.py`, `tests/integration/kap/test_report_confidentiality.py` |
| TM-5 | Package import accepts any package that verifies (with P10 for FIX_ENABLED rows). | An internal package is refused before anything is staged (P12, `INTERNAL_RELEASE_REFUSED`). `package validate` reports P12 as well. | `knowledge/package/confidentiality.py`, `package/validate.py`, `package/importer.py` | `tests/unit/knowledge/kap/test_internal_release_export.py` |
| TM-6 | Feature 011 P10: a FIX_ENABLED row needs gates 1 to 5 (and it is refused at import otherwise). Carried-forward built-in rows need a `--downgrade-unverified` import (INTEGRATION_NOTES 76). | **Inherited trust (D3):** a shipped built-in FIX_ENABLED row is trusted by byte identity with the verified shipped baseline (`is_shipped_builtin_rule`). The decision is recorded in the `release_installed` audit entry as `details.inherited_trust` (`rule_ids`, `baseline_digest`). Any other FIX_ENABLED row, new or changed, must pass gates 1 to 5. Trust is never granted by a row's own `origin`. | `knowledge/release/safety.py` (`fix_row_trusted`, `package_fix_findings`, `INHERITED_TRUST_RECORDABLE`), `package/importer.py` (line ~170) | `tests/unit/knowledge/kap/test_certified_fix_trust.py`, `tests/unit/knowledge/update/test_activation.py` |
| TM-7 | No automated approval exists. `promote` requires a human approval reference. | **Automated certification** (`odooflux.fix-certification/1`). A record binds the rule digest, template id and version, primitive identity, evidence sources, fixture and output digests and check results, under policy version `1`. Its reference is `auto-cert:<policy>:<record_digest>`, never presented as human approval. Load, import, build and activation re-verify it. `promote` refuses `auto-cert:` references. Certification never widens trust: it only adds a requirement on top of gates 1 to 5. | `knowledge/update/certification.py`, `transformers/certify_exec.py`, `transformers/fix_templates.py`, `knowledge/release/safety.py`, `knowledge/authoring/promote.py` | `tests/unit/knowledge/update/test_certification.py`, `tests/unit/transformers/test_fix_templates.py`, `tests/unit/knowledge/kap/test_certified_fix_trust.py`, `tests/unit/knowledge/update/test_activation.py` |
| TM-8 | Rule ids are stable. A removed rule is a removal. | **Semantic supersede** (`semantic-replacement/1`). A removed rule is approved only when a replacement with equal executable semantics and at least equal maturity exists. Built-in, manual, origin-less and retired rows are never approved. Approved mappings are recorded in the audit trail and passed to activation so rotated ids are not reported as lost capabilities. | `knowledge/update/capability.py`, `knowledge/pipeline.py` | `tests/unit/knowledge/update/test_supersede_policy.py`, `tests/integration/kap/test_pipeline_supersede_policy.py` |
| TM-9 | Evidence rows cite locations in one source. | **Linked cross-source evidence**: evidence of a change may be shipped and cited by a rule that this build generated (origin `GENERATED`), with its own `source_id`, revision and locations. Any other origin is refused with nothing written. | `knowledge/candidates/accept.py` (`ship_linked_evidence`), `knowledge/pipeline.py` (`LINKED_EVIDENCE_REFUSED`) | `tests/unit/knowledge/kap/test_linked_evidence.py` |
| TM-10 | Reports render evidence and ledger records as stored. | **Confidentiality view**: Enterprise-derived evidence rows, change records and findings are withheld or reduced to ids in `validate`, `refresh`, the rule validate path and `ledger show`. The stored bytes are unchanged. Public records come back as the same object. See [Residual risks](#residual-risks) for what the view does not cover. | `knowledge/release/confidentiality_view.py`, `cli/knowledge.py`, `cli/kap_rule.py`, `cli/kap_extract.py` | `tests/unit/knowledge/kap/test_confidentiality_view.py`, `tests/integration/kap/test_report_confidentiality.py` |

Note on TM-7 scope. The library exists and is wired into the trust predicate. Issuance is not wired into any CLI verb or into the pipeline in this tree: there is no `knowledge rule certify` command, and the build does not issue records. Consequently no rule is FIX_ENABLED through certification today. See [OPEN and BLOCKED items](tasks.md#open-and-blocked-items).

## Support dimensions

The update report and the status output state four dimensions, and never collapse them into one "supported" claim (`knowledge/update/report.py`).

| Dimension | Meaning | What the update reports |
|---|---|---|
| Source availability | Whether each source could be read, and with what verified provenance. | Per-source statuses (`OK`, `SKIPPED_OFFLINE`, `SKIPPED_NO_CREDENTIALS`, `AUTH_FAILED`, `UNAVAILABLE`) and acquisition statuses. |
| Knowledge completeness | How much of the transition the release covers. | `COMPLETE` or `PARTIAL` with limits, from the release. |
| Migration support | Whether the transition is supported by the release. | `not established by an update` in every update report. A new upstream version is never reported as supported. |
| Production certification | Whether a human has certified the knowledge for production use. | `NOT_GRANTED` in every update report and in `status`. |

## Acceptance criteria

Each criterion is testable. The status of each criterion (EXECUTED, SKIPPED, NOT_AUTHORIZED, NOT_RUN) is recorded by the feature owner in [verification.md](verification.md). This file does not assert any status.

- **AC-01**: The shipped catalog loads and validates fail-closed; its digest is computed from the parsed document and is not stored in the file; it contains no commit SHA. (see verification.md)
- **AC-02**: The catalog covers exactly 12.0 to 19.0 for each family; Community entries are `GIT_COMMUNITY`, Enterprise entries are `GIT_ENTERPRISE` with `requires_credentials: true`; `ENTERPRISE_LOCAL` is refused. (see verification.md)
- **AC-03**: Discovery makes one `ls-remote` per repository and never per catalog entry; only `^[0-9]+\.0$` branches are versions. (see verification.md)
- **AC-04**: `check` with `--offline` or `ODOOFLUX_OFFLINE=1` makes zero network calls and exits 4. (see verification.md)
- **AC-05**: `check` and `status` never write to the kb-home; `history` never writes. (see verification.md)
- **AC-06**: Remote fetches are by commit SHA, verify the commit, use the hardened environment, and are the only `remote_git` subprocess use, covered by the no-customer-code-execution allow-list. (see verification.md)
- **AC-07**: Community git calls never receive the Enterprise token; the Enterprise token is attached only to the Enterprise identity. (see verification.md)
- **AC-08**: The token never appears in any output, history record, report or raised exception in the tests that plant it. (see verification.md)
- **AC-09**: A missing Enterprise token is `SKIPPED_NO_CREDENTIALS` with zero Enterprise fetch calls; a rejected token is `AUTH_FAILED`, distinct from `UNAVAILABLE`. (see verification.md)
- **AC-10**: The planning fingerprint and the build fingerprint are distinct lifecycles; a planning fingerprint never serves as a build record. (see verification.md)
- **AC-11**: The update history is hash-chained; an edited line is named by `verify`; `update` refuses to extend a broken chain. (see verification.md)
- **AC-12**: A repeated run with unchanged inputs is `NOOP` only when the persisted build inputs are equal; otherwise it builds. (see verification.md)
- **AC-13**: An installed Enterprise source that cannot be read is carried forward byte-identically, reported as `STALE_UNVERIFIED`, and never removed. (see verification.md)
- **AC-14**: A lost or downgraded capability, or a changed FIX_ENABLED row that is not trusted, blocks activation; `PARTIAL` activates only when no blocking code applies. (see verification.md)
- **AC-15**: Inherited trust (D3) applies to byte-identical shipped FIX_ENABLED rows only, and the decision is recorded in `release_installed.details.inherited_trust`. (see verification.md)
- **AC-16**: A certification record is recomputed on verify; a tampered record, a changed input, a stored pass flag or an unattached executor is refused; `promote` refuses `auto-cert:` references. (see verification.md)
- **AC-17**: An internal release is never exported (no override option) and an internal package is refused on import (P12). (see verification.md)
- **AC-18**: Enterprise provenance entries carry the extra fields; a public release keeps the Feature 011 refusal of Enterprise-derived provenance. (see verification.md)
- **AC-19**: Semantic supersede approves only a removed rule with an equal-semantics replacement of at least equal maturity; built-in, manual, origin-less and retired rows are never approved. (see verification.md)
- **AC-20**: Pair keys are unique and deterministic; two pairs with one step and no distinct keys raise `ValueError`; an internal release skips step 13 with `INTERNAL_NOT_EXPORTABLE`. (see verification.md)
- **AC-21**: Unified inventories: a module declared by two sources is a recorded conflict, never resolved to either; a dependency that resolves to nothing is an explicit finding; a missing inventory on either side fails closed for carried Enterprise modules. (see verification.md)
- **AC-22**: `migrate` resolves dependencies over the target and source inventories with no network, and withholds fixes for an unresolved module (`INCOMPLETE`). (see verification.md)
- **AC-23**: Enterprise-derived content (canary strings planted in evidence match, paths and descriptions) appears in no captured stream and no written report of the covered verbs. (see verification.md)
- **AC-24**: `check`, `update`, `status` and `history` exit with the codes in [quickstart.md](quickstart.md#7-exit-codes) and their JSON outputs validate against the shipped schemas. (see verification.md)
- **AC-25**: The catalog, the new schemas and the update verbs work from an installed wheel, offline, with a socket-and-subprocess guard. The test is opt-in (`ODOOFLUX_PACKAGING_INSTALL=1`). (see verification.md)

## Non-goals

- No automatic migration target from a discovered version. `NEW_VERSION_DISCOVERED` is reported only.
- No live-upstream, real-Enterprise or production verification in this feature's documentation or default test run. The real-source pilot 16.0 to 17.0 is prepared, not run (NOT_RUN / NOT_AUTHORIZED).
- No automatic generation of `FIX_ENABLED` rules. Generated rules stay `DETECT_ONLY` (Addendum D, BLOCKED).
- No static model, field, method or XML-id catalogue. Inventory v1 is modules, dependencies and provenance only. Existing KAP ledger and evidence cover API-change facts.
- No public projection export (a Community-only rebuild for `package export --public`). Not implemented.
- No CLI verb for certification (`knowledge rule certify`). Not implemented.
- No change to human `promote`, to the gate functions 2 to 5, or to the Feature 011 gate P10 beyond the trust predicate above.
- No credential helper command, no `sslVerify` disabling, no global git configuration written or read.
- No change to Feature 011 release store, lock or pointer code.

## Deviations from the plan

Recorded for the owner. None is hidden by the implementation; each is also in [INTEGRATION_NOTES.md](../../docs/planning/kap/INTEGRATION_NOTES.md) (feature 012 section).

- **D-A (provenance for internal releases).** Plan B2.1 asked for `digest_only` Enterprise provenance with no snapshot manifest or file list in the release. The implementation ships Enterprise snapshot manifests (paths and content hashes, never content) inside the internal release (`release/provenance.py`, module docstring). The release stays internal and never leaves the machine. Owner acknowledgement is required because the plan text and the code differ.
- **D-B (inventory location).** Plan B3 placed inventories in `inventory/<version>.json` inside the release. The implementation reads them from `<knowledge tree>/inventory/<M.0>.json` (`dependencies/unified.py`).
- **D-C (carry-forward mechanism).** Plan Addendum C1 chose rebuild from retained snapshots, not a parent overlay. This is the implementation.
- **D-D (certification templates).** The template table in `transformers/fix_templates.py` still enables `REPLACEMENT_CANDIDATE` (`replace_call_name`, `replace_attribute`) and `REMOVED` (`remove_keyword`, `remove_decorator`) classes. Addendum D states that the `REPLACEMENT_CANDIDATE` mapping is wrong and that the eligible classes must be changed (`REPLACEMENT_CONFIRMED`, `DELEGATING_ALIAS`, `IDENTITY_DECORATOR_REMOVED`) before any issuance is possible. Issuance is not wired, so no rule is affected today. This must be corrected before issuance is wired.

## Residual risks

The brief for this documentation named "three known residual leaks". No document or code in the repository enumerates them under that name. The residual leaks verified in code are:

1. **Fail-open view on missing provenance.** `load_provenance_index` returns `None` when the provenance file is missing or unreadable, and drops any `source_id` that appears twice. `enterprise_source_ids` then returns an empty set, and `is_enterprise_record` returns False for every record, so the confidentiality view passes records through unredacted (`release/confidentiality_view.py`, `release/safety.py`). Owner decision pending: fail closed.
2. **Rule messages are not covered by the view.** The view withholds findings only by file and rewrites evidence, change and refresh records. Rule rows (`message`, `suggestion`) are not passed through it, and the canary test covers `match`, location paths and descriptions, not rule messages. Owner decision pending: rule-message redaction for Enterprise-backed rules.
3. **Enterprise identities in output.** Source ids and pinned revisions of Enterprise sources appear in `check`, `update` and `history` output (for example `odoo-enterprise-17.0`). This is identity metadata, not content, and is designed in (ids only), but it discloses which Enterprise versions a holder uses.

Other residual risks: the git-local identity check still trusts a locally configured origin remote as a declared identity (INTEGRATION_NOTES note 14); the release resolver digest cache (note in `release/resolver.py`); the per-version inventory strictness is an owner decision pending.

## Support, limitations and open items

Limitations stated by the update output on every run: migration support not established; production certification not granted; Enterprise freshness unknown without a check. The full ledger of done and open tasks is in [tasks.md](tasks.md).
