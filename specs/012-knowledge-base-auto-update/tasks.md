---
description: "Task ledger for feature 012, Knowledge Base Auto-Update (waves 1 to 3, plan Addenda A to E)"
---

# Tasks: Knowledge Base Auto-Update

**Input**: [spec.md](spec.md), [plan.md](plan.md) (sections 1 to 8, Addenda A to E). **Verification**: [verification.md](verification.md) is written by the feature owner after the final regression; this ledger does not record test outcomes.

## Format

`- [X] Tnn Title (FR/NFR/TM ids; F: owned files; Tests: test modules) — what is implemented`

- `[X]` means the implementation and its test modules exist in the working tree. It does not mean the suite was run by the owner for this ledger. Test modules are under `tests/unit/knowledge/update/`, `tests/unit/knowledge/kap/`, `tests/integration/kap/`, `tests/integration/packaging/` and `tests/unit/transformers/`.
- Paths are relative to the repository root. `K/` abbreviates `src/odooflux/knowledge/`.
- Task ids `T01` to `T08c` follow plan section 7 and Addendum B6. Wave 3 is grouped by the feature brief; each group names the plan task it covers.
- No task commits. The working tree is uncommitted.

---

## Wave 1: catalog, remote git, fingerprint and history

- [X] T01 Source catalog v2 (FR-001, FR-002, TM-3; F: `K/update/catalog.py`, `K/update/catalog.json`, `pyproject.toml` package-data; Tests: `test_catalog.py`) — Loads and validates `catalog.json` fail-closed (schema 3). 12.0 to 19.0 for each of `community` and `enterprise`. Enterprise entries require credentials. `ENTERPRISE_LOCAL` is refused. Digest from the parsed document, not stored in the file. No commit SHA stored.
- [X] T02 Remote git and Enterprise credentials (FR-007, FR-008, FR-009, NFR-002, NFR-003; F: `K/update/remote_git.py`, `K/update/credentials.py`, `tests/unit/validation/test_no_customer_code_execution.py` allow-list entry for `remote_git.py`; Tests: `test_remote_git.py`, `test_credentials.py`) — `ls_remote_heads` (ref advertisement only) and `fetch_commit` (shallow, by SHA, verified, into a managed cache). Hardened environment. Token attached only to the Enterprise identity via a fixed askpass stub and a child-only variable. CA bundle mapped per call. Per-identity lock, temporary directory then atomic rename, stale-temporary sweep.
- [X] T03 Fingerprints, history and report schemas (FR-024, FR-025, NFR-004; F: `K/update/fingerprint.py`, `K/update/history.py`, `K/schemas/update_report.schema.json`, `K/schemas/knowledge_status.schema.json`; Tests: `test_fingerprint.py`, `test_history.py`, `test_report.py`) — Deterministic fingerprint over the build inputs. Hash-chained `updates/history.jsonl` under the kb-home lock.
- [X] T06a Fix templates and certification library (FR-018, TM-7; F: `transformers/fix_templates.py`, `transformers/certify_exec.py`, `K/update/certification.py`, `K/schemas/fix_certification.schema.json`; Tests: `tests/unit/transformers/test_fix_templates.py`, `test_certification.py`) — Versioned template table, record `odooflux.fix-certification/1`, recomputing verifier, executor attached once by the composition root. **Note**: the eligible change classes in the table are the T06a mapping; Addendum D says two of them are wrong. See OPEN items.

## Wave 2: discovery, planner, inventory

- [X] T04 Discovery and the `check` verb (FR-003, FR-004, FR-005; F: `K/update/discovery.py`, `cli/kap_update.py` (check); Tests: `test_discovery.py`, `test_check_cli.py`) — One `ls-remote` per repository. Per-source statuses. Read-only. `NEW_VERSION_DISCOVERED` is never a migration target.
- [X] T05 Planner (FR-002, FR-010; F: `K/update/planner.py`, `K/update/model.py`; Tests: `test_planner.py`) — Pure function from catalog, check report and installed state to ACQUIRE, CARRY_FORWARD and SKIP decisions and the unified pairs. Planning and build fingerprints are separate lifecycles.
- [X] T06b Module inventory and dependency resolver (FR-022; F: `K/update/inventory.py`, `K/schemas/inventory.schema.json`; Tests: `test_inventory.py`) — Static `ast.literal_eval` of `__manifest__.py`; no execution. Merge with conflicts recorded, closure resolution, `carry_forward_compat` (existence only).

## Wave 3: Enterprise sources, unified release, orchestrator

Wave 3 is grouped as the feature brief lists it. Each group names the plan task it covers.

- [X] W3-A Enterprise provenance (TM-1, TM-2, TM-3, FR-021; plan B2.1 with deviation D-A; F: `K/release/provenance.py`, `K/release/manifest.py`, `K/acquisition/sources.py`; Tests: `tests/unit/knowledge/kap/test_enterprise_provenance.py`) — `GIT_ENTERPRISE` official kind with the same identity rules as Community plus a licence. `confidentiality`, `licence_id`, `licence_access` on Enterprise entries only. Top-level `confidentiality: internal` in `release.json`, covered by the release digest. `LICENCE_UNVERIFIED` on a missing or placeholder licence.
- [X] W3-B Export and import fail-closed (TM-4, TM-5, FR-020; plan B2.2; F: `K/package/confidentiality.py`, `K/package/builder.py`, `K/package/validate.py`, `K/package/importer.py`, `cli/kap_package.py`; Tests: `tests/unit/knowledge/kap/test_internal_release_export.py`, `tests/integration/kap/test_report_confidentiality.py`) — `export_package` refuses internal releases with no override. P12 (`INTERNAL_RELEASE_REFUSED`) on import and validate, before anything is staged. The `include_enterprise_derived` parameter is removed.
- [X] W3-C Catalog licence and fingerprint lifecycle (FR-001, FR-002; F: `K/update/catalog.py`, `K/update/fingerprint.py`, `K/update/planner.py`; Tests: `test_catalog.py`, `test_fingerprint.py`, `test_planner.py`) — Licence fields (schema 3). `redistribution` recorded separately from `licence_access`. Build fingerprint requires verified snapshot digests.
- [X] W3-D Acquisition (FR-010, FR-011, NFR-002; plan B4, C1; F: `K/update/acquire.py`, `K/acquisition/adapters/retained.py`; Tests: `tests/unit/knowledge/update/test_acquire.py`) — ACQUIRE by SHA, CARRY_FORWARD at the installed revision, failed non-required ACQUIRE with an installed revision becomes carried, required failure blocks and marks later rows `NOT_ATTEMPTED`. Offline makes no fetch call and does not read the token. `RetainedSnapshotAdapter` returns a stored snapshot only when its digest equals the installed digest.
- [X] W3-E Capability comparison and activation (FR-013, FR-014, FR-015, TM-6; plan B3, C3, D4, Addendum D3; F: `K/update/capability.py`, `K/update/activation.py`, `K/release/safety.py` (`fix_row_trusted`, inherited trust); Tests: `test_capability.py`, `test_activation.py`, `tests/unit/knowledge/kap/test_certified_fix_trust.py`) — Lost, downgraded, changed, added per rule id. Blocking codes `COMPLETENESS_FAILED`, `CAPABILITY_LOST`, `CAPABILITY_DOWNGRADED`, `FIX_NOT_TRUSTED`, `ENTERPRISE_COMPAT`, `INTEGRITY`. Activation through the one atomic pointer swap with fault points `verify`, `lock`, `pointer`, `audit`. D3 inherited trust by byte identity, recorded in `release_installed.details.inherited_trust`.
- [X] W3-F Pipeline unified sources (FR-012; plan B1, C2; F: `K/pipeline.py` (`BuildPlan.pairs` with `key`, `adapter_by_source`, `emit_inventory`, `supersede_policy`), `K/update/orchestrator.py` (GIT_ENTERPRISE `GitLocalAdapter` registration for the build), `builtins.py` (certifier attachment); Tests: `tests/integration/kap/test_pipeline_unified.py`) — Pair keys unique and deterministic. Duplicate keys raise `ValueError`. Step 13 skips with `INTERNAL_NOT_EXPORTABLE` for internal releases. Inventory emitted into the release from verified snapshots.
- [X] W3-G Linked cross-source evidence (TM-9; F: `K/candidates/accept.py` (`ship_linked_evidence`), `K/pipeline.py` (linked step); Tests: `tests/unit/knowledge/kap/test_linked_evidence.py`) — Evidence of a change is shipped and cited only by a rule with origin `GENERATED`. Others refused with nothing written (`LINKED_EVIDENCE_REFUSED`).
- [X] W3-H Certification trust boundaries (TM-7, FR-017, FR-018, FR-019; plan section 4, A4, Addendum D; F: `K/release/safety.py`, `K/loader.py`, `K/authoring/promote.py`, `K/update/certification.py`, `transformers/certify_exec.py`; Tests: `test_certification.py`, `test_certified_fix_trust.py`, `test_activation.py`) — Verify is called at load, package import, build and activation. Record refused on any mismatch (`cert-verify-failed`). `promote` refuses `auto-cert:` references. Certification only adds a requirement on top of gates 1 to 5. **No issuance path is wired**: see OPEN.
- [X] W3-I Semantic supersede policy (TM-8, FR-016; Addendum E, owner decision A; F: `K/update/capability.py` (`semantic_supersede_policy`, `POLICY_NAME = "semantic-replacement/1"`), `K/pipeline.py` (`supersede_policy`); Tests: `tests/unit/knowledge/update/test_supersede_policy.py`, `tests/integration/kap/test_pipeline_supersede_policy.py`) — Approves only equal-semantics replacements of at least equal maturity. One-to-one mapping by sorted id. Built-in, manual, origin-less and retired rows never approved.
- [X] W3-J Orchestrator (T08c; FR-006, FR-010, FR-013, NFR-005; Addendum E; F: `K/update/orchestrator.py`; Tests: `tests/unit/knowledge/update/test_orchestrator.py`, `tests/integration/kap/test_update_orchestrator.py`) — `run_update`. Update lock `<kb-home>/updates/.update.lock` (5 seconds bounded wait, `CONCURRENT_UPDATE`). NOOP only with equal persisted build inputs. Dry run takes no lock and writes nothing. Carried Enterprise pairs are added to the build. Outcomes `NOOP`, `ACTIVE`, `DRY_RUN`, `BLOCKED`, `FAILED`, `ROLLED_BACK`.
- [X] W3-K `update`, `status` and `history` CLI (FR-025, AC-24; F: `cli/kap_update.py`, `K/update/report.py`; Tests: `tests/unit/knowledge/update/test_update_cli.py`, `test_report.py`, `test_history.py`) — Exit codes in [quickstart.md](quickstart.md#7-exit-codes). Human and canonical JSON output. Schemas `odooflux.knowledge-update/1`, `odooflux.knowledge-status/1`, `odooflux.knowledge-history/1`.
- [X] W3-L Unified migrate dependencies (FR-022, AC-21, AC-22; plan B5; F: `K/dependencies/unified.py`, `cli/migrate.py`; Tests: `tests/integration/kap/test_migrate_unified_inventory.py`) — Custom-module closure over source and target inventories. COMPLETE or INCOMPLETE per module with stable reason codes. No edition flag. Fixes withheld for INCOMPLETE modules. Offline, sockets counted.
- [X] W3-M Confidentiality view (TM-10, FR-023; plan B2.5, B5; F: `K/release/confidentiality_view.py`, `cli/knowledge.py`, `cli/kap_rule.py`, `cli/kap_extract.py`; Tests: `tests/unit/knowledge/kap/test_confidentiality_view.py`, `tests/integration/kap/test_report_confidentiality.py`) — Enterprise status from the verified provenance index only. Evidence, change records and findings withheld or reduced to ids. Public records returned unchanged. **Fail-open on missing provenance**: see OPEN.
- [X] W3-N Wheel tests (T11, AC-25; F: `tests/integration/packaging/test_update_wheel.py`) — Builds a wheel and a venv, installs offline, runs the verbs under a socket and subprocess guard. **Opt-in** (`ODOOFLUX_PACKAGING_INSTALL=1`). Skipped by default. Not run for this ledger.
- [~] T12 Documentation (F: this directory, `docs/guides/KNOWLEDGE_UPDATE.md`, appended section of `docs/planning/kap/INTEGRATION_NOTES.md`) — Written: `spec.md`, `tasks.md`, `quickstart.md`, `docs/guides/KNOWLEDGE_UPDATE.md`, INTEGRATION_NOTES notes 78 onward. **Not done by this task**: `README.md`, `docs/TECHNICAL_USAGE.md` (other owners), `verification.md` (owner, after the final regression), and `plan.md` (owner file, not edited).

---

## Verification snapshot taken for this ledger

These are local, offline runs made while writing the documents. They are not the acceptance matrix and not the final regression.

- `python3 -m unittest` over the 012 unit modules (`tests/unit/knowledge/update`, the five `tests/unit/knowledge/kap/` modules named in the brief, `tests/unit/transformers/test_fix_templates.py`) and the integration modules (`test_pipeline_unified`, `test_pipeline_supersede_policy`, `test_update_orchestrator`, `test_migrate_unified_inventory`, `test_report_confidentiality`) plus `test_update_wheel`: **196 tests run, OK, 9 skipped**. The 9 skips are the opt-in wheel tests (`ODOOFLUX_PACKAGING_INSTALL` unset).
- Offline CLI runs in a temporary kb-home (`/tmp`), documented with real output in [quickstart.md](quickstart.md).
- No online command was run. No live upstream, real Enterprise source or production source was contacted.

---

## OPEN and BLOCKED items

### BLOCKED

- [X] **B-1 Generated fixers** — RESOLVED by plan Addendum F: machine confirmation (`machine-confirmation/1`) for S1/S2/S3, derived certification, pipeline issuance, trust verification at build/import/load/activation; e2e `tests/integration/kap/test_autofix_e2e.py` and `test_autofix_e2e_extra.py`.

### OPEN (implementation)

- [X] **O-1 Certification eligibility table** — superseded: the table now serves only the derived classes via `python.rewrite_imported_symbol` and `python.remove_imported_decorator`; older literal-name templates serve no class.
- [ ] **O-2 Certification issuance is not wired.** No `knowledge rule certify` verb exists (`grep` of `src/` finds none). The pipeline does not call `issue`. Certification records can be verified, and the trust predicate uses them, but no CLI or pipeline path creates one. Do not document certification as an available user workflow.
- [ ] **O-3 Public projection export (plan B2.3) is not implemented.** `knowledge package export --public` does not exist. The only export path refuses internal releases.
- [ ] **O-4 Plan B2.1 versus implementation.** The plan asked for `digest_only` Enterprise provenance with no snapshot manifest in the internal release. The implementation ships Enterprise snapshot manifests (paths and hashes, never content) inside the internal release. Recorded as deviation D-A in [spec.md](spec.md#deviations-from-the-plan). Owner acknowledgement needed.
- [ ] **O-5 Enterprise adapter reality.** `ENTERPRISE_LOCAL` is retired from the catalog. The Enterprise managed-cache clone is read through the existing `GitLocalAdapter` (no working tree), registered by the update orchestrator only. This is implemented and tested with synthetic repositories only. The Feature 011 command `knowledge source acquire` (`cli/kap_source.py`, `build_adapters`) still registers `ENTERPRISE_LOCAL` and no `GIT_ENTERPRISE` adapter, so a `GIT_ENTERPRISE` spec cannot be acquired through it. Not changed by feature 012.
- [X] **O-6 Pre-existing bug, `knowledge refresh --search-candidates` (not fixed here).** `K/refresh.py` lines 71-72: the `git grep -l` call passes the file basename as the pathspec, which matches only root-level files of that name, and the parser keeps only lines with at least two colons, while `git grep -l <rev>` prints `<rev>:<path>` (one colon). Reproduced in a throwaway repository: a match moved to another path returns no candidates with the flag on. `refresh.py` is unchanged from HEAD, so the bug predates feature 012. (fixed with regression test)

### OPEN (owner decisions)

- [ ] **O-7 Rule-message redaction for Enterprise-backed rules.** The confidentiality view does not pass rule `message` or `suggestion` text. See [spec.md residual risks](spec.md#residual-risks), item 2.
- [ ] **O-8 Fail-closed missing provenance in the confidentiality view.** An unreadable, missing or ambiguous provenance index makes the view pass records through. See [spec.md residual risks](spec.md#residual-risks), item 1.
- [ ] **O-9 Per-version inventory strictness.** Whether a missing or unreadable per-version inventory should block migration rather than report `INCOMPLETE`.
- [ ] **O-10 Real-source pilot 16.0 to 17.0.** NOT_RUN and NOT_AUTHORIZED. Prepared only. No live upstream or real Enterprise source was contacted for this feature.

### OPEN (documentation outside this task's ownership)

- [ ] **O-11** `docs/reviews/automated/DOC-verification-kap.md` lines about 45 and 75 describe pre-012 behaviour (default `import` refused by P10 with exit 3, and `--downgrade-unverified` changing the release id). Feature 012 inherited trust (D3) changes the import path, so these lines may be stale. Not re-executed in this task. Not edited (not owned here).
- [ ] **O-12** `README.md` and `docs/TECHNICAL_USAGE.md` have no feature 012 section (other owners).
- [ ] **O-13** `verification.md` (owner, after the final regression) and the acceptance matrix AC-01 to AC-25 status.
