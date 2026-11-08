# Fragment KAP: human-review items for the knowledge acquisition pipeline (feature 011)

Each entry is PENDING_HUMAN_REVIEW. Nothing here records a human decision, approval, certification or production readiness. Reviewer name and review date are intentionally empty.

Conventions used in this fragment:
- Owner decisions OD-K1 to OD-K12 come from ADR-020 (`docs/planning/ARCHITECTURE_DECISIONS.md`) and `specs/011-knowledge-acquisition-pipeline/research.md`. Their defaults are recommendations, written as "assumed default, needs confirmation".
- "Note N" refers to `docs/planning/kap/INTEGRATION_NOTES.md`.
- Automated tests are evidence for a reviewer. They do not replace review.
- "Certification impact" reads `Decision` where the sources leave the blocking status to the owner, `Yes` where a source says certification of a built release stays pending (ADR-020 "Not decided here", ADR-019), and `No` where a source says the item is not a blocker.

## KAP-OD-K1: kb-home location and environment variable
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** ADR-020 open decision OD-K1 (research.md).
- **Component:** `knowledge/release/store.py`, `knowledge/release/resolver.py`, `cli/migrate.py` (`--kb-home`).
- **Review:** confirm the kb-home location and variable. Assumed default (needs confirmation): `ODOOFLUX_KB_HOME` or `--kb-home`, otherwise the XDG data dir (`$XDG_DATA_HOME/odooflux/kb`, fallback `~/.local/share/odooflux/kb`; Windows `%LOCALAPPDATA%\odooflux\kb`), separate from `ODOOFLUX_STATE_DIR`. ADR-020 also notes that installed releases living outside `src/odooflux/knowledge/` extend ADR-009 and need owner confirmation.
- **Why:** installed releases must outlive runs and must not sit inside the package.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_resolver.py`, `test_release_store.py`, `test_cli_release.py`.
- **Risk if not approved:** the path and variable become a user-facing commitment; changing them later moves installed releases.
- **Reviewer:** project owner (architecture).
- **Certification impact:** Decision.

## KAP-OD-K2: package container and compression
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K2 (research.md, R4).
- **Component:** `knowledge/package/builder.py`, `knowledge/package/archive.py`.
- **Review:** confirm the `.ofkp` container. Assumed default (needs confirmation): ZIP with DEFLATE level 6, deterministic entry order and timestamps. `ZIP_STORED` is the alternative if byte equality across zlib versions is required.
- **Why:** DEFLATE output is stable for one zlib version only. The reproducibility test therefore compares the sha256 manifest and release digest, and byte equality runs in one interpreter (research.md, R4).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_package_builder.py`, `test_archive_reader.py`, `test_package_limits.py`; `tests/integration/kap/test_package_lifecycle.py`.
- **Risk if not approved:** packages built on different zlib versions may differ byte for byte, although their digests match.
- **Reviewer:** release maintainer.
- **Certification impact:** Decision.

## KAP-OD-K3: unverified FIX_ENABLED rules on import
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K3 (research.md); REQ-KAP-027.
- **Component:** `knowledge/package/importer.py` (gate P10), `knowledge/release/safety.py`.
- **Review:** confirm the import default. Assumed default (needs confirmation): refuse the package if it has an unverified FIX_ENABLED rule; `--downgrade-unverified` imports it with those rules capped to DETECT_ONLY and the original kept in provenance.
- **Why:** an imported package must not enable a fixer on its own say-so; gates are recomputed locally (REQ-KAP-027).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_package_importer.py`, `test_release_safety.py`, `test_release_provenance.py`; `tests/integration/kap/test_provenance_e2e.py`, `test_package_lifecycle.py`.
- **Risk if not approved:** with refusal as default, a package containing a fixer cannot be imported without the downgrade option; with the option, fixers are silently capped.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-OD-K4: report schema bump and the built-in release in reports
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K4 (research.md); REQ-KAP-040; note 45; note 60.
- **Component:** `reporting/model/report.schema.json`, `reporting/model/model.py`, `knowledge/release/resolver.py`, `cli/migrate.py`.
- **Review:** confirm the report change. Assumed default (research.md, needs confirmation): an optional `knowledge_release` object, with `schema_version` 1.1.0 only when the field is present. Conflict to decide: note 45 records the owner direction that the migration report also records the built-in release. In that case every `migrate` report carries `knowledge_release` and reads 1.1.0, not only reports made with an active release. ADR-020 says REPORTING_AND_UX increments `schema_version` on breaking changes, so the bump needs owner confirmation. The committed provisional-corpus expected trees (ORIG-006-T035-T044) must be regenerated and recorded, because a real `migrate --fix` report differs from the golden only in `schema_version` and `knowledge_release` (note 60).
- **Why:** a migration report must say which knowledge produced its findings (ADR-020, decision 5).
- **Evidence and tests available:** `tests/integration/kap/test_migrate_with_release.py` (`test_report_has_release_id_digest`, `test_legacy_overlap_with_release`); `tests/unit/knowledge/kap/test_migrate_coverage.py` (`test_report_differs_from_golden_only_in_schema_and_release`). `tools/update_expectations.py` reports no changes because the golden is built by `tests/integration/helpers.py` (`normalised_report`), which bypasses migrate (note 60).
- **Risk if not approved:** consumers of schema 1.0.0 see a changed report shape; provisional goldens remain stale and do not carry the release block.
- **Reviewer:** project owner, with the test architect for the expected trees.
- **Certification impact:** Decision.

## KAP-OD-K5: package authenticity
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K5 (research.md).
- **Component:** `knowledge/package/importer.py`, `knowledge/release/manifest.py`, `knowledge/release/provenance.py`.
- **Review:** confirm the authenticity model. Assumed default (needs confirmation): digest pin only, with `--expect-digest` on import; no signing in v1 and no hosted distribution.
- **Why:** a self-consistent package can be produced by anyone. The digest only proves that a user received the bytes they pinned. Related: notes 14, 16 and 50 (see KAP-TRUST-ORIGIN).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_release_provenance.py`, `test_package_builder.py`, `test_package_importer.py`; `tests/integration/kap/test_provenance_e2e.py`.
- **Risk if not approved:** packages from an unknown source are accepted when their internal digests match. Gate 1 still recomputes provenance locally.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-OD-K6: Enterprise and supplementary source scope
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K6 (research.md); REQ-KAP-007; REQ-KAP-008; note 35.
- **Component:** `knowledge/acquisition/adapters/enterprise_local.py`, `knowledge/acquisition/adapters/supplementary.py`, `knowledge/package/builder.py`.
- **Review:** confirm the scope. Assumed default (needs confirmation): Enterprise is accepted by local path only and its derived data is excluded from exported packages; OCA and OpenUpgrade come from local git or a snapshot and are labelled non-official. Note 35 records that refusing snapshots of Enterprise-derived sources is not enforced yet. Confirm that this must be closed before any Enterprise use.
- **Why:** Enterprise content is licensed. Snapshot manifests list paths and hashes of the scanned files.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_adapter_enterprise_supp.py`, `test_adapter_git.py`, `test_adapter_dir_pack.py`.
- **Risk if not approved:** Enterprise-derived metadata could be shipped in a package until note 35 is enforced.
- **Reviewer:** project owner (licensing) with the release maintainer.
- **Certification impact:** Decision.

## KAP-OD-K7: audit log reuse
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K7 (research.md); REQ-KAP-045; note 3.
- **Component:** `knowledge/release/audit.py`, `core/recovery/audit_log.py`.
- **Review:** confirm reuse of the hash-chained `AuditLog` in kb-home for release actions. Note 3 applies here: the existing `verify_chain` does not detect an edit to the final entry, and this affects the kb-home log as well as the run log. Note 3 is recorded as a technical item in the notes; it is listed here because the kb-home log inherits it.
- **Why:** one audit mechanism for acquisition, build, import, activation and rollback (REQ-KAP-045).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_release_audit.py`; `tests/integration/kap/test_package_lifecycle.py` (audit cases).
- **Risk if not approved:** an edit to the last kb-home audit entry is not detected by `verify_chain`.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-OD-K8: named benchmark sets for recall
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K8 (research.md); REQ-KAP-033.
- **Component:** `knowledge/coverage/metrics.py`, `knowledge/coverage/crosscheck.py`.
- **Review:** confirm the benchmark sets. Assumed default (needs confirmation): the golden corpus (42 review cases) plus the synthetic fixture set; no recall claim is made otherwise, and recall is `NOT_MEASURED` without a named `benchmark_id`.
- **Why:** a recall figure without a named benchmark overclaims.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_metrics.py`, `test_crosscheck.py`. The 42 golden review cases are themselves PENDING_INDEPENDENT_REVIEW (register ORIG-006-T035-T044).
- **Risk if not approved:** no recall statement can be made beyond the named sets; if the golden cases are not independently reviewed, the benchmark is not an accuracy measure.
- **Reviewer:** Odoo migration maintainer.
- **Certification impact:** Decision.

## KAP-OD-K9: redaction module
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K9 (research.md); REQ-KAP-046; REQ-KAP-028; note 57.
- **Component:** `utils/redaction.py`, `knowledge/release/` export path.
- **Review:** confirm `utils/redaction.py` as the one redaction module (assumed default, needs confirmation; `utils/redact.py` left alone). Note 57 records accepted risks to confirm: the CLI export passes no canary values, so only credential shapes are caught there, and `scrub` does not mask secret text in dictionary keys.
- **Why:** packages must contain no secrets or customer data (REQ-KAP-028).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_kap_redaction.py`, `test_kap_redaction_boundaries.py`.
- **Risk if not approved:** a non-shaped secret inside a release file would ship in an export; a secret used as a dict key is not masked.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-OD-K10: activating PARTIAL releases
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K10 (research.md); REQ-KAP-034; REQ-KAP-037.
- **Component:** `knowledge/release/store.py`, `knowledge/release/coverage_check.py`, `cli/migrate.py`.
- **Review:** confirm activation rules. Assumed default (needs confirmation): a PARTIAL release can be activated with a report warning; `--require-complete-kb` refuses.
- **Why:** partial knowledge must never be presented as success (REQ-KAP-041).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_gates.py`, `test_migrate_coverage.py`; `tests/integration/kap/test_migrate_with_release.py`.
- **Risk if not approved:** with the default, a partial release is in force for `migrate` and only warnings flag the gap.
- **Reviewer:** project owner.
- **Certification impact:** Decision.

## KAP-OD-K11: rule history sidecar and built-in duplicate checks
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K11 (research.md); REQ-KAP-020; REQ-KAP-021.
- **Component:** `knowledge/authoring/history.py`, `knowledge/authoring/checks.py`.
- **Review:** confirm the choice. Assumed default (needs confirmation): rule history in a sidecar `history/rules/<rule-id>.json` (append-only, hash-chained) rather than inline; duplicate and conflict checks on the built-in tree only with `--strict-builtin`, so default `knowledge validate` output is unchanged.
- **Why:** rule files and evidence stay byte-compatible with the built-in tree (REQ-KAP-005).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_rule_history.py`, `test_authoring_checks.py`, `test_builtin_golden.py`.
- **Risk if not approved:** duplicate problems in the built-in tree are not reported by default.
- **Reviewer:** Odoo migration maintainer.
- **Certification impact:** Decision.

## KAP-OD-K12: revisit SQLite
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** OD-K12 (research.md, R3); REQ-KAP-003.
- **Component:** storage decision for `knowledge/ledger/`, `knowledge/release/`.
- **Review:** confirm that SQLite stays out. Assumed default (needs confirmation): plain JSON and ZIP only, and SQLite is reconsidered only above the stated threshold (over 500 000 ledger entries per release, or load time over 5 s on the reference machine, shown by a committed benchmark). The notes do not record such a benchmark.
- **Why:** REQ-KAP-003 forbids a database server and SQLite.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_kap_import_graph.py` (no `sqlite3` import in the knowledge tree).
- **Risk if not approved:** none immediate; the threshold is untested.
- **Reviewer:** project owner.
- **Certification impact:** Decision.

## KAP-OD-K13: carried-forward built-in FIX_ENABLED rows in a pipeline-built release (policy B, narrowed)
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** new owner decision, integration notes 4, 32 and the OD-K13 classification section of docs/planning/kap/INTEGRATION_NOTES.md; REQ-KAP-043 ("built-in FIX_ENABLED rules are grandfathered, not re-gated").
- **Component:** `knowledge/pipeline.py` (release build carries the parent tree forward), `knowledge/package/importer.py` (gate P10), `knowledge/release/safety.py` (`is_shipped_builtin_rule`), `knowledge/loader.py` (`load_active_knowledge`).
- **Classification (not a policy question):** the cap on UNVERIFIED FIX_ENABLED rules in a non-built-in release is an established technical invariant (REQ-KAP-027, REQ-KAP-039, REQ-KAP-018, INV-5) and stays enforced: refuse on default import, `--downgrade-unverified` caps, cap at load with `KAP_FIX_CAPPED`. A defect against it was found and fixed during closure: the load path treated a FIX_ENABLED row as a grandfathered built-in because the row itself omitted `origin` or claimed `BUILTIN`; it now grandfathers only rows byte-for-byte identical to the shipped built-in rows (`test_release_safety`, `test_loader_active`).
- **Unresolved decision:** the contract says only "built-in rules are grandfathered". Observed behaviour for copies of the ten shipped FIX_ENABLED rows that a release carries forward: kept running at load (identical to the shipped rows) but REFUSED on default import, because P10 gates every FIX_ENABLED row, built-in included, and the built-in rows carry no provenance. Decide: (a) accept carried-forward rows on import when identical to the shipped rows (consistent with load), (b) keep refusing them, so a built release needs `--downgrade-unverified`, or (c) cap them.
- **Why:** the two paths disagree today, and a release built from the built-in parent cannot be imported by default.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_release_safety.py`, `test_loader_active.py`, `test_package_importer.py`; `tests/integration/kap/test_package_lifecycle.py`, `test_pipeline_e2e.py` (variant F), `test_pipeline_release_usable.py` (variant G, if present).
- **Risk if not approved:** (a) removes the stricter import gate for the ten shipped rows; (b) makes every pipeline-built release need an explicit downgrade on import; (c) turns off built-in automatic fixes when such a release is active. None of these is approved or production-certified.
- **Reviewer:** security reviewer with the Odoo migration maintainer.
- **Certification impact:** Decision.

## KAP-M8: weakest declared step for release completeness
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** open question (M8), `specs/011-knowledge-acquisition-pipeline/contracts/coverage-and-gates.md`; note 17; note 22.
- **Component:** `knowledge/coverage/gates.py`, `knowledge/coverage/manifest.py`, `knowledge/coverage/metrics.py`.
- **Review:** decide whether a declared version transition whose steps are not all COMPLETE must downgrade a release from COMPLETE. The contract is silent. The proposed rule (not implemented): release completeness is the weakest of its declared `steps_covered`; `decide` returns PARTIAL with the incomplete step named in `limits`; `check_consistency` fails when the manifest says COMPLETE but a declared step is not. This needs a gate code the contract does not name.
- **Why:** REQ-KAP-034 lists blocked claims but does not mention transition coverage. Today a COMPLETE manifest with an incomplete declared transition is not blocked.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_gates.py`, `test_coverage_manifest.py`, `test_metrics.py`; `tests/integration/kap/test_migrate_with_release.py`.
- **Risk if not approved:** a release can be reported COMPLETE while a declared version transition is incomplete.
- **Reviewer:** project owner, with the test architect.
- **Certification impact:** Decision.

## KAP-AI-AUDIT: audit trail for AI proposals
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** note 55 (open decision); REQ-KAP-017; REQ-KAP-045.
- **Component:** `knowledge/candidates/ai_proposer.py`, `cli/kap_candidates.py`.
- **Review:** decide whether AI proposals are written to the kb-home audit log. The `ai_proposal` action exists, but proposal provenance records are returned, not written there, and candidate stores live in an arbitrary tree path rather than kb-home. Also confirm the excerpt rule: the excerpt is the evidence description plus location labels (the schema has no excerpt text), and no source is sent.
- **Why:** AI output is proposal-only and never evidence (REQ-KAP-017); an audit trail would show what was sent and proposed.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_ai_proposer.py`, `test_ai_gateway_factory.py` (denial without grant, kill switch, provider receives no request on denial).
- **Risk if not approved:** AI proposals leave no kb-home audit record.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-DEACTIVATE: meaning of `deactivate`
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** note 6 (agent interpretation, to confirm).
- **Component:** `knowledge/release/store.py`, `cli/kap_release.py`.
- **Review:** confirm that `deactivate` removes `active.json` and drops the previous-release stack. Current behaviour is an agent interpretation recorded in note 6.
- **Why:** if the stack is dropped, a later rollback cannot return to an earlier release.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_release_store.py`, `test_cli_release.py`.
- **Risk if not approved:** rollback history is lost on deactivate.
- **Reviewer:** project owner.
- **Certification impact:** Decision.

## KAP-TRUST-ORIGIN: trusted-origin limit and external trust anchor
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** notes 14, 16, 36 and 50 (accepted risks, declared identity).
- **Component:** `knowledge/acquisition/adapters/git_local.py`, `knowledge/release/provenance.py`, gate 1 (`knowledge/release/safety.py`).
- **Review:** the official identity of a local clone is a declared identity, not cryptographic proof. The check verifies consistency of the declaration, the allow-list, the pinned commit and the content digest. A forged local origin remains a residual risk. Decide whether to adopt an external trust anchor (signed tags or maintainer-published hashes) or to accept declared identity for this release.
- **Why:** nothing in the release is signed; a clone whose remote matches the allow-list passes the identity check (note 36).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_official_local_identity.py`, `test_git_local_malicious_repo.py`, `test_release_provenance.py`; `tests/integration/kap/test_provenance_e2e.py` (clone origin swapped fails closed).
- **Risk if not approved:** a hostile local clone with a matching origin is accepted as official. Gate 1 still needs the snapshot, revision and digest to agree.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-AUTO-ACCEPT: automatic acceptance of verified candidates
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** new item from the pipeline code (`knowledge/pipeline.py`, step `candidates`, around lines 486 to 500 call `knowledge/candidates/accept.py`).
- **Component:** `knowledge/pipeline.py`, `knowledge/candidates/accept.py`, `knowledge/candidates/generator.py`.
- **Review:** the release pipeline accepts a PROPOSED candidate without human review when `accept` passes: detectors verified, evidence present and matching the schema, no collision with an active MANUAL rule, no ledger settlement and no id clash. Accepted rules are origin GENERATED with maturity DRAFT or DETECT_ONLY. Decide whether this automatic acceptance is acceptable, or whether a human accept step must precede inclusion in a release.
- **Why:** generated rules enter the release tree without a person reading them. The maturity cap keeps them out of FIX_ENABLED (REQ-KAP-016).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_accept.py`, `test_generator.py`, `test_pipeline.py`; `tests/integration/kap/test_candidates_e2e.py`, `test_pipeline_e2e.py`.
- **Risk if not approved:** unreviewed generated detectors can appear in a built release. They cannot apply edits while DETECT_ONLY or DRAFT.
- **Reviewer:** Odoo migration maintainer.
- **Certification impact:** Decision.

## KAP-CORPUS-CERT: SC-005-style certification of the first real-corpus build
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** new item; ADR-020 ("certification of any built release stays PENDING_HUMAN_REVIEW", ADR-019); SC-005 of feature 011 `spec.md`.
- **Component:** the first knowledge release built from real Odoo sources (pipeline `knowledge/pipeline.py`, all extractors).
- **Review:** certify the first real-corpus knowledge build. No real Odoo corpus build was run. The offline fixtures are synthetic (`tests/fixtures/kap/fixture_release`, `tests/unit/knowledge/kap/_archives.py`, `make_synth_repo.py`). The reviewer must check that the built release is correct Odoo migration knowledge, with evidence verified against pinned upstream sources.
- **Why:** offline tests prove mechanics on synthetic data. They do not prove accuracy of real knowledge.
- **Evidence and tests available:** synthetic only: `tests/integration/kap/test_pipeline_e2e.py`, `test_provenance_e2e.py`, `test_extract_e2e.py`. The real-source path is opt-in (KAP-LIVE-TESTS).
- **Risk if not approved:** no KAP-built knowledge can be called certified or supported. Migration accuracy for such a release stays unverified.
- **Reviewer:** senior Odoo developer who has migrated custom addons across the relevant versions, not the author of the rules; plus the release maintainer.
- **Certification impact:** Yes. Mandatory for any certified KAP knowledge build.

## KAP-LIVE-TESTS: opt-in live and Docker tests that have not been run
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** REQ-KAP-044; spec.md; notes 42 and 62 (checkpoints ran offline only).
- **Component:** `tests/integration/kap/test_live_sources.py`, `tests/unit/knowledge/kap/test_fetch_offline.py`.
- **Review:** run the opt-in tests once with the real environment: `ODOOFLUX_KAP_LIVE_TESTS=1` (live fetch, with `ODOOFLUX_KAP_FETCH_URL` and `ODOOFLUX_KAP_FETCH_SHA256`), `ODOOFLUX_KAP_CLONES=<dir>` with `ODOOFLUX_KAP_CLONE_REV` (real clones), and `ODOOFLUX_KAP_DOCKER_TESTS=1` (Docker). None of these was run.
- **Why:** the default suite is offline by design. Live network, real clones and Docker paths are unexercised.
- **Evidence and tests available:** the test modules above skip cleanly when the variables are unset.
- **Risk if not approved:** the live fetch, clone and Docker paths have no evidence from a real run.
- **Reviewer:** maintainer with git, network and Docker access.
- **Certification impact:** Decision.

## KAP-JS-ADAPTER: JavaScript structural extractor (tree-sitter branch unverified)
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** REQ-KAP-004; REQ-KAP-011; `parsers/javascript/treesitter_adapter.py`.
- **Component:** `knowledge/extract/domains/js_owl.py`, `parsers/extract_toolkit.py`, `parsers/javascript/treesitter_adapter.py`.
- **Review:** the tree-sitter branch of the optional JavaScript adapter is UNVERIFIED and has never been executed. Its tests are skipped without the `js` extra (`test_domain_js.py`, `skipUnless` on the adapter). Without the adapter, JS files are accounted `UNSUPPORTED` with reason `NO_JS_ADAPTER`. Decide whether to accept the fallback for this release, or to run the tree-sitter branch in an environment with the `js` extra and record the result.
- **Why:** JS/OWL changes are classified only through the optional adapter; without it their classification is incomplete by design.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_domain_js.py`, `test_extract_toolkit.py` (the adapter-disabled path via `ODOOFLUX_DISABLE_JS_ADAPTER`).
- **Risk if not approved:** JS/OWL changes may be missing from classification; the missing coverage shows as `UNSUPPORTED` and blocks COMPLETE (REQ-KAP-013, REQ-KAP-034).
- **Reviewer:** engineer with the `js` extra installed.
- **Certification impact:** Decision.

## KAP-GIT-IDENTITY: `insteadOf` identity gap and git versions
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** notes 50 and 51; `tests/unit/knowledge/kap/test_git_local_malicious_repo.py` (one `expectedFailure`, documented).
- **Component:** `knowledge/acquisition/adapters/git_local.py`.
- **Review:** (1) A `url.<x>.insteadOf` rule makes `git remote get-url` print an allow-listed URL, so a hostile origin can pass the official-identity check. Closing it needs raw URL reading, which is outside the pinned command set. Decide whether to accept this as residual risk. (2) The hostile-repository review was verified only with git 2.43.0. Other git versions, tty pager, foreign-owned repositories (fail closed under `safe.directory`), alternates, shallow clones and grafts, and sha256 object formats (fail closed) are not covered.
- **Why:** the git adapter runs read-only git plumbing against local clones, and the review covered one git version.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_git_local_malicious_repo.py`, `test_git_local_readonly.py`.
- **Risk if not approved:** on other git versions, or against an `insteadOf` config, the official-identity check can be passed by a hostile clone.
- **Reviewer:** security reviewer.
- **Certification impact:** Decision.

## KAP-ROOT-GUARD: knowledge-root guard allow-list sign-off
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** notes 38, 61 and 63; `tests/unit/knowledge/kap/test_knowledge_root_guard.py`.
- **Component:** the 21-entry reviewed allow-list of modules that may reference `KNOWLEDGE_ROOT` (in `test_knowledge_root_guard.py`), including `knowledge/loader.py`.
- **Review:** sign off the 21-entry allow-list. Note 63 records that the list is unchanged after `cli/kap_candidates.py` was changed to use the shared helper `knowledge.loader.is_builtin_path`. Note 38 records that a stale entry fails the guard, so later edits may need allow-list updates. The allow-list must not be widened without review.
- **Why:** modules that reference the built-in tree root are the path by which a release could be bypassed.
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_knowledge_root_guard.py`, `test_loader_active.py`.
- **Risk if not approved:** unreviewed modules can read the built-in root while a release is active, which breaks the single-release rule in note 39.
- **Reviewer:** Odoo migration maintainer or test architect.
- **Certification impact:** Decision.

## KAP-FE-1: approval identity deferred (future enhancement, not a blocker)
- **Status:** PENDING_HUMAN_REVIEW
- **Original ID:** FE-1 in `docs/planning/kap/FUTURE_ENHANCEMENTS.md`; ADR-020 scope clarification; notes 2 and 37.
- **Component:** `knowledge/authoring/promote.py`, `knowledge/authoring/ops.py` (`resolve_author`).
- **Review:** acknowledge the deferral. Authenticated approver identity, RBAC and approval workflows are out of scope for this release. The approval reference taken by `knowledge rule promote` is recorded metadata only, and `--author`, `$GIT_AUTHOR_NAME` or the OS login name are not authenticated identity. This item is NOT a blocker: the technical gates (provenance, validation, conflicts, FIX_ENABLED eligibility, package integrity) are unchanged.
- **Why:** the owner deferred it explicitly (ADR-020 scope clarification).
- **Evidence and tests available:** `tests/unit/knowledge/kap/test_promote.py`, `test_authoring_ops.py`.
- **Risk if not approved:** none for the current release. Reports and documentation must not present the approval reference as human certification.
- **Reviewer:** project owner.
- **Certification impact:** No. Stated as not a blocker.

## KAP closure additions (findings of the final documentation and quickstart passes)

All entries below are PENDING_HUMAN_REVIEW. Nothing here records a human decision.

## KAP-CL-1: mistyped or empty `--kb-home` runs the built-in release
- **Status:** PENDING_HUMAN_REVIEW
- **Review:** by the migration-integration contract a kb-home that does not exist or has no `active.json` resolves to the built-in release. A typo in `--kb-home` therefore silently selects built-in knowledge. The report does name the built-in release and its digest, and `--require-complete-kb` exists, but a stderr notice for an explicitly supplied path that yields the built-in release was not added because it would reinterpret the contract. Decide whether an explicit `--kb-home` that does not exist should be an error or a warning.
- **Evidence and tests:** `test_migrate_coverage`, `test_migrate_with_release`, `test_release_consistency`. **Reviewer:** product owner with the migration maintainer. **Certification impact:** Decision.

## KAP-CL-2: unofficial evidence cannot be packaged; registry schema has no `repository` key
- **Status:** PENDING_HUMAN_REVIEW
- **Review:** a release build refuses evidence from `official=false` sources (E002: url not on the allow-list), so OCA/OpenUpgrade-derived knowledge cannot ship as a package. `source_registry.schema.json` has no `repository` key, so an explicit repository needs a separate candidate-source file. Decide whether supplementary knowledge should be packageable (labelled non-official) and whether the registry schema should carry `repository`.
- **Evidence and tests:** `test_pipeline_e2e`, `test_quickstart`, `test_evidence_builder`. **Reviewer:** knowledge-base maintainer. **Certification impact:** Decision.

## KAP-CL-3: smaller behaviours to confirm
- **Status:** PENDING_HUMAN_REVIEW
- **Review:** `release show` does not re-hash the release; `extract` with a wrong `--blobs` exits 0 with FAILED files in the accounting; `candidates generate` refuses while PROPOSED candidates are pending; ledger edits made outside the pipeline are not detected by `resume` (use `--from-step`); `--downgrade-unverified` yields an installed release id that differs from the package digest (the manifest is recomputed, audit-logged; `--expect-digest` checks the package's own digest); `ai propose` can reach an external provider only with explicit authorization, so "only `source fetch` opens a socket" in the draft contract is not true for that command; `conflicts.json` history may be dropped on a later generate and `candidates/ai/*.json` is not covered by the overwrite guard.
- **Evidence and tests:** `test_cli_release`, `test_cli_package`, `test_cli_candidates`, `test_cli_extract_ledger`, `test_ai_gateway_factory`, `test_quickstart`. **Reviewer:** engineer. **Certification impact:** low; none block, the first four should be decided before release.
