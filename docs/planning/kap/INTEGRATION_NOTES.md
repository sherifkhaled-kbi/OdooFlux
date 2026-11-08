# KAP integration notes (orchestrator, feature 011)

Cross-stream findings that later tasks must honour. Technical notes only; nothing here records a human decision.

| # | Note | Owner task | Status |
|---|---|---|---|
| 1 | Gate 1 (`release/safety.py`) treats evidence as official only when its `source_id` resolves in `provenance/sources.json` with `official`, a non-OCA/OpenUpgrade `kind`, status `VERIFIED`, a `url` on the allow-list (or `local:`), a pinned `revision`, a non-AI record and a location `content_sha256`. The data-model list for a release `sources` entry names `{source_id, revision, snapshot_digest, official, status}` only. The release builder MUST also emit `url` and `kind` into `provenance/sources.json`, or every official claim stays unsupported (fail-closed). | T070 pipeline/build, T062 | open |
| 2 | Promotion approval is a recorded reference only: it is checked for presence (empty, "unknown" and the promoter's own identity string are refused) and is NOT authenticated. Owner decision: approver identity, authentication, RBAC and approval workflows are deferred to a future release (docs/planning/kap/FUTURE_ENHANCEMENTS.md, FE-1). Not a current-release blocker; the technical gates (provenance, validation, conflicts, FIX_ENABLED eligibility, package integrity) are unchanged. | FE-1 | deferred (owner) |
| 3 | `core/recovery/audit_log.py` `verify_chain` does not detect an edit to the final entry. Affects the existing run audit log and the kb-home log. | register | open (technical) |
| 4 | Built-in FIX_ENABLED rules (10) carry no provenance, so a release built from the built-in tree has them refused on import, or capped to DETECT_ONLY with `--downgrade-unverified`. Intended: stricter gate for releases, built-ins grandfathered. | ADR-020 OD list | open (owner) |
| 5 | KAP CLI exit codes 3 and 4 differ from the migrate table (3 rejected edits, 4 blocked) and from the legacy `knowledge` docstring (3 tool error). Matches contracts/cli-surface.md; different commands. Document in the CLI reference. | T088 docs | open |
| 6 | `deactivate` removes `active.json` and drops the previous-release stack (agent interpretation). Confirm. | register | open (owner) |
| 7 | Built-in digest is computed from the bytes loaded; no shipped reference. Wheel hash is the anchor. | register | accepted risk |
| 8 | Resolver stat fingerprint misses a same-size edit with a restored mtime within one process; a new process verifies fully. | register | accepted risk |
| 9 | T001 byte-compat golden for a migration report uses the reporting model's built-in report, not a real `migrate` run. A real-migration golden check is required in the migration-integration phase. | T080/T083 | open |
| 10 | Concurrent agents editing `tasks.md` checkboxes once lost a mark (T020). Orchestrator reconciles checkboxes after each wave. | orchestrator | process |

## Follow-ups from S1f (owner-confirmed direction)

| # | Item | Plan | Owner task | Status |
|---|---|---|---|---|
| 11 | `SKIPPED_UNAUTHORIZED` is terminal for the current acquisition attempt. After entitlement exists, the same source id should be retried as a NEW attempt (attempt counter, old attempt kept in history) instead of requiring a new source id. | Assess and, if small, add an `attempt` field to the registry entry and a `--retry` path in `kap_source acquire`; never reuse a terminal attempt's result. | follow-up after S1g (owns `acquisition/sources.py`) | planned |
| 12 | The default registry path is `./sources.json`, relative to the current working directory (override `--registry`). | Document in README/TECHNICAL_USAGE CLI reference and quickstart. | T088 docs | planned |
| 13 | Lifecycle fixture copies built-in evidence record EV-101. | Replace with a fully synthetic evidence record; keep a separate built-in compatibility test. | follow-up (fixture-only, `tests/fixtures/kap/fixture_release/`) | planned |
| 14 | Official local clone identity: a configured Git remote URL is a declared identity, not cryptographic proof. The contract verifies consistency of declaration, allow-list, pinned commit and content digest. A forged local origin stays a residual risk absent a trust anchor (signed tags or maintainer-published hashes). | S1g implements one shared helper used by the adapter, provenance and gate 1. | S1g | in progress |
| 15 | No provenance writer exists yet. The release builder (T070 via the pipeline T068) must ship the snapshot files under `snapshots/` and write `provenance/sources.json` entries with `source_id, kind, url, origin_url (official local clones), revision, snapshot_id, snapshot_digest, official, status`. Gate 1 reads exactly these and recomputes against the shipped snapshot file. | T068, T070 | open |
| 16 | `origin_url` is not part of `snapshot_digest`; official identity is a declared identity, not authenticity (see contracts/source-adapter.md "Official local clone identity"). | register | accepted risk |
| 17 | M8 (version-transition coverage) has no gate. S7b read the contract and data-model: both are silent on whether an incomplete declared transition downgrades release completeness, so NO rule was invented. The ambiguity and the proposed rule (completeness = weakest declared step) are recorded as "Open question (M8)" in contracts/coverage-and-gates.md and await an owner decision. `check_consistency` still detects a manifest that contradicts its own recomputed M8 values. | owner decision | closed as recorded question (no behaviour change)
| 18 | `coverage.manifest.check_consistency` must be called at release time by the pipeline (T068) and the coverage CLI (T069); the build-time G-MANIFEST gate is empty by construction. | T068, T069 | open |

## Owner direction after S1g (release integration closure)

| # | Requirement | Stream / task | Status |
|---|---|---|---|
| 19 | Provenance writer at the release-builder boundary: package the verified source snapshots under `snapshots/` and emit `provenance/sources.json` consumable by Gate 1 (note 15). New module `knowledge/release/provenance.py` (+ tests), later called by the pipeline (T068) and `release build` (T070). | P-WRITER (next free slot) | queued |
| 20 | Keep the existing `snapshot_digest` unless a contract defect is shown. Bind `source_id`, canonical claimed origin, pinned revision and snapshot digest inside the integrity-protected release metadata (`release.json` body and the manifest-hashed provenance and snapshot files). No claim that a configured Git origin proves authenticity. | P-WRITER | queued |
| 21 | End-to-end test: verified local clone to acquired snapshot to release builder to portable package to importer to Gate 1, with missing, altered and mismatched provenance cases failing closed. | P-WRITER (`tests/integration/kap/test_provenance_e2e.py`) | queued |
| 22 | Close note 17 (M8) from the actual contract text without inventing semantics; if the contract is silent, record an open owner question (no new behaviour). | S7b (item 2) | done (branch b: contract silent, question recorded) |
| 23 | `check_consistency` at the release boundary: coverage CLI (S7b item 1) and the pipeline (T068); inconsistent releases are never reported complete or valid. | S7b, T068 | coverage CLI done (`coverage show/gates --path DIR`, exit 1 on inconsistency); pipeline wiring open (T068); `--release` waits for T070; `coverage/inputs.json` has no producer yet |
| 24 | Narrow `data-model.md` update for the source identity fields (`expected_origin`, `origin_url`, `snapshot_id`, provenance entry fields). | P-WRITER | queued |
| 25 | Preserve S8a's active-knowledge loader work (`loader.py`, `builtins.py`, `versions/registry/loader.py`, `view_index.py`); shared-file changes only after S8a completes. | orchestrator | holding |

## Architecture conflict found at integration (import-graph guard)

| # | Finding | Decision (orchestrator, from existing architecture) | Owner | Status |
|---|---|---|---|---|
| 26 | `tests/unit/test_import_graph.py` (REQ-ARC-001: core packages, `knowledge` included, import only stdlib and other core packages) fails: 7 files under `knowledge/extract/domains/` import `odooflux.parsers.*` and `knowledge/candidates/templates.py` imports `odooflux.rules.bindable`. The guard must not be weakened or exempted. | Inject adapters through the composition root, as `builtins.py` documents (only module that wires adapters into the core): `run(argv, ctx)` passes `ctx.registries` to the `knowledge` command (today dropped); extractor domains obtain parsers from the registries (`registries.parsers`) handed in by the driver caller; the template loader takes the known detector names as a parameter (verification at the composition root and in tests). No new core-to-adapter imports. | S9a (after S7b releases `extract/driver.py`) | queued |
| 27 | `resolve_knowledge` returns `root=<release dir>` while `load_active_knowledge` loads `<root>/knowledge` (release layout: `knowledge/`, `provenance/`, `snapshots/`). The T073-T075 readers take the knowledge tree root. | Keep; reconcile and document at T082. | T082 | open |
| 28 | `authoring/ops.create_rule` forced origin MANUAL, so T059 could not write GENERATED rules. | Additive keyword-only `origin` ("MANUAL" default, or "GENERATED" with a `source_candidate` id recorded in history); still DETECT_ONLY/DRAFT; `edit_rule` still protects origin. | S6 (resumed) | in progress |

## Decisions on the import-graph fix (S9a blocker, orchestrator)

| # | Decision | Rationale |
|---|---|---|
| 29 | Adapters reach the core through an `ExtractToolkit` (new non-core module `parsers/extract_toolkit.py`) attached to the registries by `builtins.py` (`registries.extract_toolkit`), passed as a parameter to the driver and handlers. Document-level factories (python/xml span-bearing documents, optional lazy JS adapter) are needed because the registered `_ParserEntry.parse` is only a syntax check. | Follows the documented composition-root pattern and the existing dynamic attribute `run_rule_binder`; the import-graph guard (REQ-ARC-001) is not weakened. |
| 30 | Template detector verification fails closed: `load_templates(known_detectors=None, *, verify=True)` raises without a mapping; only an explicit `verify=False` (tests) skips it and records `detectors_verified=False`. The generator takes `known_detectors` explicitly. | Verification must not silently drop on the production path. |
| 31 | `known_detectors` is a mapping detector ref -> bindable module/callable (as `BINDABLE_MODULES`), because signature checks need the objects. | Same. |

## Provenance writer closure (P-WRITER)

| # | Item | Status |
|---|---|---|
| 32 | `release/provenance.py` (write_provenance, sources_meta, verify_provenance) built; 16 unit + 9 e2e tests: verified local clone to snapshot to release to package to importer to Gate 1. Fail-closed cases: provenance missing, revision altered, digest altered, origin_url missing or not allow-listed, source official=false, evidence source_id absent, shipped snapshot missing or altered, clone origin swapped (acquisition fails OFFICIAL_IDENTITY_UNVERIFIED, nothing built). Importer default: P10 refuses the FIX_ENABLED rule; `--downgrade-unverified` caps it. | done |
| 33 | Orchestrator edits in files of finished streams, required by the writer: `package/builder.py` now allows ONLY `snapshots/ss-<12hex>.json` manifests (blobs and everything else under `snapshots/`, and all of `staging/`, stay forbidden; test_package_snapshot_rule); `release_manifest.schema.json` sources items gain optional `origin_url`, `snapshot_id`. | done |
| 34 | The production pipeline/builder (T068/T070) must catalogue each evidence revision in the release's own `official_sources/revisions.json` (E003), as the e2e fixture does, and must call `write_provenance`/`verify_provenance`. | open (T068/T070) |
| 35 | Snapshot manifests list file paths and hashes of the scanned sources. For an Enterprise-derived source this is metadata about licensed content: the builder/writer should refuse to ship snapshots of sources flagged `enterprise_derived` (flag introduced by S1c in package validation). Not enforced yet. | open (technical, before any Enterprise use) |
| 36 | A forged local clone whose origin remote matches passes the identity check: declared identity, not authenticity; nothing is signed. | accepted risk (note 16) |

## Security guard (REQ-SEC-001, no customer-code execution) found violations in new KAP code

| # | Finding | Resolution | Status |
|---|---|---|---|
| 37 | `tests/unit/validation/test_no_customer_code_execution.py` forbids dynamic import (outside `cli/plugins.py`) and `subprocess` outside the runtime adapters and `knowledge/refresh.py`. New KAP code violated it in three places. | (1) `cli/kap_common.py` dynamic `importlib` discovery replaced by a static explicit module list (S9a). (2) `knowledge/authoring/ops.py` no longer spawns `git config user.name`; `resolve_author` reads `--author`, `$GIT_AUTHOR_NAME` or the OS login name (recorded metadata only, not authenticated identity, FE-1). (3) `knowledge/acquisition/adapters/git_local.py` added to the subprocess allow-list with a written reason, because it runs read-only git plumbing against local clones (`shell=False`, cleared environment, no system/global git config, `core.fsmonitor=false`; commands `cat-file`, `rev-parse`, `remote get-url`, `ls-tree`); the command set and the hardened call are pinned by `test_git_local_readonly.py` so the allow-list cannot grow silently. | done |
| 38 | `test_knowledge_root_guard` (S8b) fails on a stale allow-list entry if a file stops referencing `KNOWLEDGE_ROOT`; S9a edits may require an allow-list update. | S8b | watch |

## Owner direction: items for migration integration and cross-stream verification

| # | Requirement | Where | Status |
|---|---|---|---|
| 39 | Active-release consistency: resolve the knowledge release ONCE per migration run into one handle and pass that same handle/root to every reader (rule binder, versions registry, view index, RNG, dependency integrity, Docker environment, AI escalation, support statement); a reader must never fall back to the built-in tree while a release is active, and no run may mix data from two releases. Add a cross-reader consistency test (all readers report the same release id and digest; a deliberately mismatched reader raises) and a guard that a reader given no root while a release is active is detected. S8b threaded optional roots but no caller passes them yet. | T082 (migrate options, `--kb-home`, single resolution) | open |
| 40 | Focused cross-stream integration run (kap unit tree, tests/integration/kap, import-graph, customer-code guard, builtin golden, knowledge validate/matrix/support-statement checks) after S9a and S10 finish and BEFORE T060-T062 and T068/T070 start; the whole suite is run only at the final acceptance milestone. | orchestrator | pending |
| 41 | Import-boundary regression test (`test_extract_boundary.py`), unverified-template visibility and acceptance refusal, and explicit validated detector mapping. | S9a addendum | queued |

## Checkpoint after S9a/S10 (74/88 tasks)

| # | Item | Status |
|---|---|---|
| 42 | Focused cross-stream integration run passed: kap unit tree 620 OK (3 skipped, JS adapter), tests/integration/kap 24 OK (incl. the 9 trust-chain cases), import-graph and customer-code guards OK, reporting 113 OK, knowledge validate / matrix / support-statement checks clean. The whole suite is deferred to the final acceptance milestone. | done |
| 43 | T086 finding fixed: `write_release_manifest(..., secrets=())` scrubs meta with `utils.redaction.scrub` (registered secrets and credential shapes masked; meta without secrets is unchanged so digests do not move). | done |
| 44 | `detectors_verified` contract: absent/None/non-True reads as unverified; survives JSON; refused by `candidates/accept.py` AND by `authoring/ops.create_rule` (GENERATED needs `detectors_verified=True`, default False) so no entry point can skip verification. | done |
| 45 | T081/T082 reconciliation: owner direction is that the migration report records the actual selected release id and digest INCLUDING the built-in release. The report model embeds any supplied dict; T082 therefore passes the built-in handle too (builtin=true, computed digest). Consequence: every migration report carries `knowledge_release` and schema_version 1.1.0, so the provisional corpus expected report JSON changes and must be regenerated (`tools/update_expectations.py`); reporting-model goldens (no release supplied) are unchanged. To record in the human-review register (T035/T044 expected trees). | T082 |
| 46 | S9a risks: the detector table enumerates the public functions of the explicitly listed BINDABLE_MODULES (no package scanning; judgement call, an explicit name list is an alternative); ExtractToolkit imports `knowledge.candidates.templates` (allowed by the guard, adds a dependency). | accepted, review |
| 47 | S10 risks: `schema_check.py` does not enforce additionalProperties/pattern (strict check runs through `tests/unit/reporting/schema_validator.py`); two reporting tests failed once in a full unit run and did not reproduce (watch for flakiness). | watch |

## Git adapter security review (S11, REQ-SEC-001)

| # | Finding | Status |
|---|---|---|
| 48 | Hostile local repository fixture (fsmonitor, pager, editor, sshCommand, askPass, hooksPath, .git/hooks, diff.external, textconv, filter clean/smudge, credential.helper, gpg.program, packObjectsHook, `ext::` remote, git-* executables): no code fired for probe, snapshot or `remote get-url`, official and unofficial. Positive control: the same clone does fire for `git status` and `git log -p`. | verified (git 2.43.0 only) |
| 49 | Four defects fixed in `git_local.py`: `refs/replace/*` could substitute a tree (`--no-replace-objects`); revision regex accepted a trailing newline (fullmatch); ls-tree object ids not checked before `cat-file --batch` (40-hex); repo path now resolved and refused before spawn if it starts with `-` or has newline/NUL. Every call also carries extra `-c` overrides, `--no-optional-locks`, `GIT_ATTR_NOSYSTEM`, `GIT_CEILING_DIRECTORIES`; env is PATH plus fixed values. | done |
| 50 | `url.<x>.insteadOf` makes `remote get-url` print an allow-listed URL, so a hostile origin can pass the official-identity check. Closing it needs raw URL reading (`git config`, outside the pinned command set) and gains little: the repo config is attacker-controlled, so the raw URL can simply be the official string. Pinned as `expectedFailure` as documentation. | accepted risk (same class as notes 14, 16) |
| 51 | Not covered by the review: git versions other than 2.43.0, tty pager, foreign-owned repositories (`safe.directory`; fails closed), alternates/shallow/grafts in untrusted clones are still read, sha256-object-format repos fail closed. | residual |

## Candidates stream closure (S12, T060-T062)

| # | Item | Status |
|---|---|---|
| 52 | T060-T062 done: 38 new tests (proposer 12, CLI 18, e2e 8). The proposer takes `gateway` and `authorizer` as parameters (duck-typed, no `odooflux.ai` import); the CLI gets them from `registries.ai_gateway_factory(cfg) -> (gateway, authorizer)`. D-08 evidence: no-grant denial names `evidence_excerpt` and the provider receives zero requests; kill switch blocks transmission; AI off builds no gateway. AI output is labelled AI_PROPOSED and never creates evidence, confirms a rename, sets FIX_ENABLED or sets `detectors_verified`. | done |
| 53 | `builtins.py` does not attach `ai_gateway_factory`, so a real `ai propose` exits 2 until the composition root wires it using the existing `cli/ai_options.py` gateway construction (D-08 unchanged: AI off by default, explicit grants, kill switch, no silent fallback). Wiring waits for S13 (owner of `builtins.py` in this round). | open (after S13) |
| 54 | Generator allocated evidence ids from the tree and ledger only, so a rejected candidate's stored evidence could clash on regeneration. Fix with reserved ids and a candidate-store scan. | S12b running |
| 55 | AI proposal provenance records are returned, not written to the kb-home audit log (`ai_proposal` action exists). Candidate stores live in an arbitrary tree path, not kb-home; decide whether proposals should also be audited. Also: the excerpt is the evidence description plus location labels (the schema has no excerpt text; no source is sent). | open (decision) |

## Redaction boundaries (S14) and T082 (S13)

| # | Item | Status |
|---|---|---|
| 56 | S14: 19 boundary tests (10 failed before). Fixed: URL credentials leaked through audit, package scan and provenance (new shape `user:pass@` masked; credentials in `url`/`expected_origin`/`origin_url` refused with code `URL_CREDENTIALS`); snapshots with credential shapes refused; CLI error paths echoed argv values (now masked; `--sha256` format-checked first). Manifest ordering proven: scrub happens before hashing, `release_digest` binds the scrubbed body, tampering after hashing is still detected. | done |
| 57 | S14 residual: the CLI export passes no canaries, so only credential SHAPES are caught there (a non-shaped secret in a release file would ship); `scrub` does not mask secret text in dict KEYS. | accepted risk, register |
| 58 | S13 (T082): `main.run` resolves the release once via `cli/migrate.resolve_migrate_knowledge` (`--kb-home`, `--require-complete-kb`); missing/corrupt/refused release prints to stderr and exits 4, no fallback; `Context.for_knowledge(handle)`; `builtins.main` uses a deferred context so migrate never builds an unrooted context; binder, versions registry, L3 integrity, AI escalation and the report use the handle's tree (`test_resolution_happens_once_per_migrate`: 1 call). Built-in release is recorded in reports too (owner decision). | done, T082 pending final reader fix |
| 59 | Cross-reader test found a real mixing risk: opt-in rules `*.xml.inherit-id-missing-in-target` and `*.xml.xpath-anchor-missing-in-target` called `load_view_index(target)` with no root. Fix approved (root passed via run params). RNG `validate_views` and `DockerEnvironment` have no call site under `src`, so migrate cannot reach them. | S13 resumed |
| 60 | `tools/update_expectations.py` reports no changes: the corpus expectation is built by `tests/integration/helpers.normalised_report`, which bypasses migrate. A real `migrate --fix` report differs from the golden only in `schema_version` and `knowledge_release` (`test_report_differs_from_golden_only_in_schema_and_release`). So the committed provisional-corpus goldens do not carry the release block; register this for the human review of the expected trees (T035/T044). | register |
| 61 | `test_knowledge_root_guard` fails on `cli/kap_candidates.py` (new, references KNOWLEDGE_ROOT only to refuse writing into the built-in tree, same as `kap_rule.py`). Do not broaden the reviewed allow-list: replace the direct reference with a shared helper in an already allow-listed module (`knowledge/loader.py`). After S12c releases `kap_candidates.py`. | open |

## Checkpoint 2 (78/88 tasks) and follow-ups

| # | Item | Status |
|---|---|---|
| 62 | Focused checkpoint passed after S12c/S13/S14: kap unit tree 710 OK x3 consecutive runs (3 skipped, 1 expected failure = the documented `insteadOf` gap), tests/integration/kap 33 OK, guards (import-graph, customer-code, knowledge-root, extract-boundary, builtin golden) 14 OK, reporting 113 + 36 OK, knowledge validate / matrix / support-statement / RTM clean. The earlier one-off SSH-normalisation failure did not reproduce (order-dependent, watch). | done |
| 63 | Knowledge-root guard: `cli/kap_candidates.py` no longer references KNOWLEDGE_ROOT; shared helper `knowledge.loader.is_builtin_path` (loader is already allow-listed). The 21-entry reviewed allow-list is unchanged. | done |
| 64 | S12c: generation never overwrites, resets or resurrects a candidate of any status (content-derived ids); skipped candidates are reported under `existing`; `_write_candidate(update=False)` refuses overwrite. Follow-ups: `authoring/conflicts.write_conflicts` rewrites `conflicts.json` from the current run only (resolved-conflict history may be dropped on a later generate); `ai propose` writes `candidates/ai/*.json` directly (not through the overwrite guard). | open (technical) |
| 65 | T068/T070/T071 running as one sequential stream (S15); gateway factory wiring (note 53) and T083 running as S16. | running |

## S16 closure (T083, AI gateway factory)

| # | Item | Status |
|---|---|---|
| 66 | `registries.ai_gateway_factory` attached in `builtins.py` (module-level function; imports `odooflux.ai` only when called; existing `build_gateway` + `Authorizer`; catalog/grant/credential errors exit 1). The command is `knowledge ai propose` (sibling of `candidates`). 14 tests with sockets blocked cover grants, denial naming `evidence_excerpt` (provider receives nothing), kill switch by flag and env, credential read only from the catalog env name and never echoed, unknown/forbidden categories refused, no gateway built without `--ai`. Deviation: a literal "odooflux.ai.gateway not in sys.modules after build_registries" assertion cannot hold because `builtins.py` already imports `EscalationPass` at top level; the call-level property is asserted. | done |
| 67 | D-08 gap: the factory passes `scanned_paths=()` to `load_credential`, so an `--ai-secrets-file` placed inside the scanned tree is not refused by that guard. Fix: pass the candidate tree as scanned path. | open (small follow-up) |
| 68 | T083 done (5 tests, offline, sockets counted 0): active release rules fire and removing activation returns to built-in; report carries the active release id and digest (built-in shows its computed digest); legacy overlap equals built-in behaviour for shared rules; rollback contract unchanged (second rollback says "already rolled back"). The tmp copy of `tests/fixtures/kap/fixture_release` had to be completed (real versions.json, built-in compat/evidence files, DETECT_ONLY copies of built-in rules, steps_covered, probe fixer cleared), so the shipped fixture is NOT a complete runnable release. | done |
| 69 | A release built by the pipeline (T068/T070) must be a COMPLETE knowledge tree usable by `migrate` (versions.json, compatibility files, schemas, evidence), carrying forward the parent release (built-in by default) per "incremental updates never destroy validated knowledge". Verify with a real built release run through `migrate` (not a hand-completed fixture). | verify after S15 |

## S15/S17 closure

| # | Item | Status |
|---|---|---|
| 70 | T068 and T070 done; T071 variants A-F pass (6 tests): A clean fixture after explicit triage and resume from step 7 is COMPLETE with empty limits; B plain fixture PARTIAL (limits G-FILES: unparsable file FAILED and JS UNSUPPORTED, G-DISP: undisposed changes); C missing required source stops at step 1, nothing installed; D unsupported-only PARTIAL; E `coverage show --release` prints M1-M8; F export then default import refused (P10, only the built-in FIX_ENABLED rules), with downgrade_unverified it installs and caps them. Variant G (a pipeline-built release used by `migrate`) is being done by S18. The old stub test was replaced (`test_build_requires_a_plan_file`). | G pending |
| 71 | OD-K13 (new owner decision): built-in FIX_ENABLED rules are copied into every release as parent content and are refused on a default import (gate 1 / P10); and a non-built-in active release has FIX_ENABLED rules capped at load unless provenance-verified. Consequence: activating a pipeline-built release turns off the built-in automatic fixes unless their provenance verifies. Options: grandfather rules with origin BUILTIN, keep refusing, or cap. Not changed; behavioural trade-off from the owner rule that an imported package must not enable an unverified FIX_ENABLED rule. | owner decision, register |
| 72 | Ledger edits made outside the pipeline are not detected by resume (probes flip when step 6 saves the ledger): operators must use `--from-step` after editing. The pipeline auto-accepts verified PROPOSED candidates (DETECT_ONLY/DRAFT, GENERATED origin, verified detectors) without human review; steps 15-16 (export/import) are not run inside the build; AI proposal is not wired into the pipeline. | register / document |
| 73 | S17: T084 (7 tests, 77 files, no violation), T085 (3 live tests skipped by default + 3 offline counterparts), T087 (wheel 539 entries, 10 schemas and 5 templates present, no forbidden entries, 9 packaging tests OK, no packaging change). `ODOOFLUX_KAP_CLONES` is the clone path itself (not a parent directory); document exactly. | done |

## OD-K13 classification (final-closure direction) and a defect found while classifying it

**Classification.** Two different things were bundled under OD-K13; they classify differently.

| Part | Classification | Basis |
|---|---|---|
| A cap on unverified FIX_ENABLED rules in a non-built-in release: refuse on import (default), `--downgrade-unverified` caps, and cap at load with warning `KAP_FIX_CAPPED` unless gates 1 to 5 pass | **A: established technical invariant**, binding | REQ-KAP-027, REQ-KAP-039, REQ-KAP-018, INV-5 (data-model), the migration-integration contract "Loader" paragraph, and the owner brief ("a package must not enable an unverified FIX_ENABLED rule simply because it was imported") |
| How copies of built-in FIX_ENABLED rows that a release carries forward are treated: grandfathered at load (the shipped rows keep running) but refused at import (P10 gates every FIX_ENABLED row, built-in included) | **B: unresolved product policy**, not made binding | The contract only says "Built-in rules are grandfathered" and defines it for the built-in release; nothing states what an imported or carried-forward copy is. |

**Defect found while classifying (A, technical blocker, FIXED).** `release/safety.gate_findings` decided that a rule was a grandfathered built-in from the rule row's OWN `origin` field (absent or `BUILTIN`). At load (`load_active_knowledge`, `include_builtin=False`) such a row was neither gated nor capped, so a FIX_ENABLED rule with no `origin` placed in a non-built-in release (a locally assembled and re-hashed release, or a directory copied into kb-home, neither of which passes the importer) would run unverified. That contradicts REQ-KAP-027 ("package self-assertions are not trusted"). Fix: a rule is grandfathered only when it is byte-for-byte identical to the row shipped in the built-in tree (`safety.is_shipped_builtin_rule`); anything else goes through gates 1 to 5 whatever it claims. Carried-forward unchanged built-in rows keep their current behaviour (still grandfathered at load), so no migration behaviour changes for them. Tests: `test_release_safety` (origin claim never grandfathers; shipped rows grandfathered, altered rows gated, import path still gates all) and `test_loader_active.test_origin_claim_does_not_skip_the_cap_at_load`; 110-test regression set (safety, loader, importer, validate, pipeline, promote, consistency, provenance e2e, pipeline e2e, migrate-with-release, lifecycle, guards, golden) OK.

**Correction of an earlier statement.** The earlier note 71 said activating a pipeline-built release turns off the built-in automatic fixes. That was a prediction from the import behaviour, not an observed load behaviour: at load the shipped built-in rows are grandfathered and keep running; only non-shipped unverified FIX_ENABLED rules are capped. Observed behaviour will be confirmed by S18 (variant G, assertion 5).

**Distinctions that must stay clear.** VERIFIED evidence is an evidence status; an ACCEPTED candidate is a generated DETECT_ONLY/DRAFT rule in the tree; FIX_ENABLED is a maturity that only `rule promote` can set and that gates 1 to 5 re-check at promote, import and load. Verification of a candidate, acceptance, inheritance (carry-forward) and activation never raise a rule to FIX_ENABLED.

**Open (B), recorded for the register (KAP-OD-K13):** whether carried-forward built-in rows should be accepted on import (grandfather by identity with the shipped row, consistent with load), kept refused, or capped; and whether a release built from the built-in parent should be importable by default without `--downgrade-unverified`.

## T071 closure and the T089 quickstart run

| # | Item | Status |
|---|---|---|
| 74 | T071 done (variants A-G). G: a pipeline-built release is a complete usable tree (defect fixed: `schemas/` was not carried forward; regression test added), is activated explicitly, and `migrate --kb-home` offline gives every reader the release root, report carries the built release id and digest (schema 1.1.0), uncovered 17->18 emits `KAP_TRANSITION_NOT_COVERED` and status is not PASS (caveat: on kbi_demo status is already FAILED from critical findings, so the unverified reason is masked), deactivate returns to built-in with the computed digest. Observed: carried-forward built-in FIX_ENABLED rows are NOT capped at load (grandfathered by identity), confirming the correction to note 71. | done |
| 75 | T089 quickstart run (S21): `quickstart.md` was a pre-implementation plan; ~14 lines named flags that never existed (DOCUMENTATION DEFECT; corrected to the real commands). Works as written: `source acquire`, `coverage show --release`, `package export`, `release list`, all five section 3 safety rows. One IMPLEMENTATION DEFECT found: `candidates generate` exits 1 for any source spec without `repository` (fell back to the `local:` url, rejected by the evidence schema, and the local path would also have leaked into evidence). Decided identity rules and fix: S22 (explicit slug, else slug of the verified `expected_origin`, else usage error exit 2; evidence url never the local path). | S22 running |
| 76 | `package import` of a pipeline-built release is refused by default (gate P10 on the carried-forward built-in FIX_ENABLED rows, KAP-OD-K13) so the documented consumer workflow needs `--downgrade-unverified` today. A downgraded install has a different release id than the package (the downgrade recomputes the manifest, audit-logged); `--expect-digest` checks the package's own digest. Documented, not changed. | open (OD-K13) |
| 77 | `--downgrade-unverified` caps the carried-forward built-in rows to DETECT_ONLY in the INSTALLED release, while a locally built release keeps them grandfathered at load: the import path and the build path disagree for the same rows (the narrowed OD-K13 question). | open (OD-K13) |
