# Feature Specification: Knowledge Acquisition Pipeline (KAP)

**Feature Branch**: `011-knowledge-acquisition-pipeline` (no git branch, ADR-015)
**Created**: 2026-11-08
**Status**: Draft, planned, not implemented
**Decision record**: ADR-020 (PROPOSED), open owner decisions OD-K1..OD-K12 in [research.md](research.md#open-owner-decisions)
**Input**: Project-owner requirements for an offline-first, evidence-based, extensible knowledge pipeline: acquire official Odoo sources, extract version differences structurally, account for every change, produce validated rules, package them as portable releases, and let `migrate` use an activated release without network.
**Baseline**: [PHASE0_ASSESSMENT.md](../../docs/planning/kap/PHASE0_ASSESSMENT.md) (facts about the repo at `main`).

## Scope and vocabulary

| Term | Meaning |
|---|---|
| Built-in release | The knowledge tree shipped in the wheel (`src/odooflux/knowledge/`). Implicit when nothing is activated. |
| Knowledge release | Immutable, digest-identified, complete knowledge tree plus manifests (see data-model.md). |
| Knowledge package | One file (`.ofkp`) carrying a release for export/import. |
| kb-home | Local directory holding installed releases, snapshots, active pointer and audit log. |
| Complete / Partial | Release completeness claims. `COMPLETE` needs all blocking gates green. `PARTIAL` lists explicit limits. Neither is human certification (ADR-019). |

Non-goals: see [Non-goals](#non-goals).

## User Scenarios and Testing

### US1 - Offline migration uses an installed release (P1)
An engineer without internet imports `odoo-17-18.ofkp`, activates it, runs `odooflux migrate`. The report names the release id and digest. No network call happens.
Independent test: socket-blocked test run of `migrate` with an activated fixture release (TST-011-xxx).
1. Given no active release, When `migrate` runs, Then output is byte-identical to the pre-KAP output (REQ-KAP-005).
2. Given an active release lacking the 17.0 to 18.0 transition, When `migrate` plans that step, Then a coverage warning is in the report and the step is never reported as verified success (REQ-KAP-037, REQ-KAP-041).
3. Given a corrupted active release (digest mismatch), When `migrate` starts, Then it fails closed with a clear error and does not fall back silently (REQ-KAP-036).

### US2 - Maintainer acquires and builds a release (P1)
A maintainer registers pinned official sources (local clones or snapshots), runs acquire, diff, ledger, candidates, validate, coverage, gates, build, export.
Independent test: end-to-end pipeline over a tiny pinned synthetic repository fixture, offline (REQ-KAP-029).
1. Given a pinned revision that is absent from the local clone, When acquire runs, Then it fails with `REVISION_UNAVAILABLE` and never substitutes another revision (REQ-KAP-009).
2. Given a changed file with no parser, When extract runs, Then it is recorded `UNSUPPORTED` in the file accounting and the gate G-FILES blocks a `COMPLETE` claim (REQ-KAP-013, REQ-KAP-034).
3. Given a rename candidate with 0.9 similarity, When classification runs, Then the class is `RENAMED_CANDIDATE` and a human or explicit manual action is needed to confirm (REQ-KAP-012).

### US3 - Author manages a rule by hand (P2)
An author creates, edits, links evidence, adds tests, validates, and retires a rule with the CLI. History keeps every revision.
1. Given a new rule with an existing id, When `rule create` runs, Then it is rejected with a duplicate error (REQ-KAP-020).
2. Given a manual rule and a generated candidate for the same detector scope, When the next release is built, Then the conflict is surfaced and the manual rule is kept unchanged (REQ-KAP-031).

### US4 - Package safety (P1)
1. Given an archive entry named `../x` or `/abs`, a duplicate entry, a symlink, or an oversize entry, When `package validate` or `import` runs, Then the package is rejected and nothing is installed (REQ-KAP-023).
2. Given a package with a FIX_ENABLED rule that fails local gates, When imported, Then import is refused (default) and no rule is enabled (REQ-KAP-027).

### Edge cases
- Interrupted import or activation leaves the previous active release in force (REQ-KAP-025).
- Two releases installed; rollback to the previous one restores its digest exactly (REQ-KAP-026).
- Enterprise source declared, no credentials or no licence: status `SKIPPED_UNAUTHORIZED`, Community-only pipeline still completes and is labelled with the missing scope (REQ-KAP-007).
- AI disabled or no grant: the pipeline completes with identical deterministic output (REQ-KAP-017).

## Requirements

Acceptance criteria (AC) are testable. Test ids are assigned in tasks.md. Priority: M = must.

### A. Offline-first and platform constraints

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-001 | `migrate`, `analyze`, `knowledge validate` and all release read paths make no network call and never download a KB implicitly. Only commands `source fetch` (explicit) may touch the network, and only when the source is declared with a network transport and `--allow-network` is passed. | AC1: socket-patched test of migrate with an active release passes. AC2: `source fetch` without `--allow-network` exits with code 2 and no socket opened. AC3: import-graph test shows no urllib/socket import in `knowledge/release`, `knowledge/package`, `knowledge/extract`, `knowledge/coverage` modules. |
| REQ-KAP-002 | No silent external AI. AI use in KAP requires the existing D-08 grant per provider and data category, kill switch honoured, and appears in the release provenance. | AC1: with no grant, any AI step is skipped with an INFO line, pipeline output identical to AI-off. AC2: `ODOOFLUX_AI_DISABLE_EXTERNAL=1` blocks external calls. |
| REQ-KAP-003 | Storage is plain files (JSON, ZIP). No database server and no SQLite. | AC: an import-graph test forbids `sqlite3`; research.md records the rejection and the evidence threshold for revisiting. |
| REQ-KAP-004 | Core KAP modules are stdlib-only (ADR-002). Heavy parsers (tree-sitter JS adapter) load lazily from existing optional extras; absence degrades JS files to `UNSUPPORTED` with reason, never to silent skip. | AC1: `dependencies = []` unchanged. AC2: with the JS adapter disabled (`ODOOFLUX_DISABLE_JS_ADAPTER=1`) JS files are accounted `UNSUPPORTED`. |
| REQ-KAP-005 | Backward compatibility: with no activated release, the knowledge directory layout, `load_knowledge()` behaviour, validator output and every existing report/CLI output stay byte-identical. The built-in release is implicit. | AC1: golden snapshot test of `knowledge validate`, `knowledge matrix --check`, and a golden `migrate` report before/after KAP code. AC2: wheel asset test unchanged and green. |

### B. Sources and acquisition

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-006 | A source registry records, per source: `source_id`, `kind`, `url`, `licence_access`, `branch`, `revision` (immutable), `retrieved_at`, `checksum`, `status`, `scope`, `failure_reason`, `official` flag. | AC: schema `source_registry.schema.json` validates; missing field fails; `status` enum is closed. |
| REQ-KAP-007 | Supported source kinds: official Odoo Community git, official documentation, upgrade scripts (in Community git), authorized Enterprise. Enterprise never bypasses authentication or licence; Community-only mode works end to end. | AC1: Enterprise adapter requires a caller-supplied local path or snapshot the user is entitled to; never fetches. AC2: Community-only fixture build reaches `PARTIAL` or `COMPLETE` with the Enterprise scope listed as excluded. |
| REQ-KAP-008 | OCA and OpenUpgrade are supplementary and labelled `official: false`. Their evidence cannot raise a rule above DETECT_ONLY and is displayed as non-official. | AC1: record with `official:false` cannot be the sole evidence of a FIX_ENABLED rule (gate G-SAFE). AC2: report/manifest label present. |
| REQ-KAP-009 | A pinned revision that cannot be retrieved fails the acquisition. No branch-head, tag, or nearest-revision substitution. Pins are 40-hex SHAs for git sources. | AC: test with a missing SHA expects `REVISION_UNAVAILABLE`, status `FAILED`, zero output snapshot. |
| REQ-KAP-010 | Local snapshots and caches are supported: a snapshot is a content-addressed manifest plus blob store, created from a local clone, directory, or snapshot pack, and re-usable offline. Every blob is verified by sha256 on read. | AC1: snapshot of a fixture tree is deterministic (same digest twice). AC2: a tampered blob raises `SNAPSHOT_CORRUPT`. |

### C. Difference extraction, ledger

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-011 | Differences are extracted with structural parsers per domain: Python/ORM (ast), XML views/data/security/reports/QWeb (expat), JS/OWL (lexer, optional adapter), manifest and dependencies, security (`ir.model.access` CSV, record rules, groups), controllers and routes, assets bundles, data files, migration scripts. No regex-only extraction for classification. | AC: each domain has a fixture pair and a golden extraction result; a test asserts extractors import from `odooflux.parsers.*`. |
| REQ-KAP-012 | Each change is classified: `ADDED`, `REMOVED`, `RENAMED_CANDIDATE`, `MOVED`, `SIGNATURE_CHANGED`, `BEHAVIOUR_CHANGED`, `DEPRECATED`, `REPLACEMENT_CANDIDATE`, `UNKNOWN`. A rename or replacement candidate is never auto-confirmed. | AC1: classification rules table has a test per class. AC2: no code path sets `confirmed=true` without a `confirm` action record (manual or reviewer). AC3: AI output cannot set confirmation (REQ-KAP-017). |
| REQ-KAP-013 | Full diff accounting: every changed file in the declared scope has exactly one terminal state: `ANALYZED`, `EXCLUDED` (reason code), `UNSUPPORTED`, `FAILED`, or the non-terminal `PENDING`. No silent skips. Inventory totals reconcile with an independent `git diff --name-status` style count. | AC1: invariant test sum(states)==in-scope files. AC2: a deliberately unparsable file lands `FAILED` with reason. AC3: any `PENDING` blocks `COMPLETE`. |
| REQ-KAP-014 | A change ledger holds every change with a stable id, class, domain, subject, from/to snapshot refs, evidence refs, rule refs, and a disposition from: `RULE_CREATED`, `EXISTING_RULE_LINKED`, `NO_CUSTOM_MODULE_IMPACT` (rationale mandatory), `DETECTION_ONLY`, `HUMAN_REVIEW`, `UNSUPPORTED`, `UNRESOLVED`. | AC1: id stable across two runs on the same inputs. AC2: `NO_CUSTOM_MODULE_IMPACT` without rationale fails validation. AC3: ledger is append/revise-only (history preserved). |

### D. Evidence, candidates, promotion

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-015 | The existing evidence schema is extended compatibly (optional fields only): per-location `content_sha256`, `snapshot_ref`; record-level `origin`, `source_id`, `change_ids`. Existing 200 records validate unchanged. | AC1: `knowledge validate` on the built-in tree has identical output. AC2: new records validate; `additionalProperties:false` retained. |
| REQ-KAP-016 | Candidate rule generation is deterministic and data-driven (templates selected by domain and class, bound to existing generic detectors via `detector_ref` + `params`); no per-release hardcoded Python. A candidate carries applicability, category, detection, provenance, confidence, disposition, tests. Generated rules default `DETECT_ONLY` (or `DRAFT` while tests are missing). | AC1: same ledger gives byte-identical candidates. AC2: no candidate has maturity `FIX_ENABLED`. AC3: adding a new version pair needs no new `.py` file (test over a synthetic pair). |
| REQ-KAP-017 | AI only proposes. AI output is never evidence, never confirms an ambiguous rename, never changes maturity, and is labelled `AI_PROPOSED` until a verified evidence record and deterministic check support it. It uses the existing AI gateway, D-08 category grants and minimisation. The deterministic offline path is complete without AI. | AC1: proposals stored with `origin: AI_PROPOSED` and are excluded from gate counts as evidence. AC2: a test with a fake provider returning "confirm rename" leaves class `RENAMED_CANDIDATE`. AC3: gateway call count is 0 with AI off. |
| REQ-KAP-018 | A rule may enter `FIX_ENABLED` only through `rule promote`, which re-checks existing gates: linked evidence, applicability, validation tests (positive, negative, idempotence), conflict check, safety (no `review_required`, official evidence not `UNVERIFIED`/`CONFLICTING`, SC-005), and records an owner-approval reference (ADR-018). | AC1: each failed gate has a test and blocks. AC2: promotion writes a revision entry. |

### E. Manual rule management

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-019 | CLI `odooflux knowledge rule <create|edit|disable|retire|inspect|validate|history|link-evidence|add-test>` uses the same rule schema and the same validator as generated rules. | AC: for each verb a CLI test; a manually created rule passes `knowledge validate` identically to a generated one. |
| REQ-KAP-020 | Duplicate and conflict detection runs on create, edit, import, and build: duplicate id, duplicate detector+params+step scope, `conflicts_with` and `depends_on` references resolvable and acyclic, overlapping edits of one scope. | AC: tests per class; the checks run in `knowledge validate` for non-built-in trees and, as warnings first, for the built-in tree (REQ-KAP-005 keeps built-in output unchanged until OD-K11 decided). |
| REQ-KAP-021 | Manual edits preserve `author`, `created_at`, all revisions, provenance, and validation status in an append-only history; edits never rewrite history. | AC: edit twice then `history` lists 3 revisions with unchanged creator; tamper (removing a revision) is detected by the history hash chain. |

### F. Knowledge package and releases

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-022 | A `.ofkp` package carries: rules, evidence, schemas, version metadata, source provenance, coverage manifests, ledger, integrity metadata (sha256 manifest), compatibility metadata, fixtures. Commands: export, import, validate, activate, list, rollback. | AC: round-trip test export then import yields an identical release digest. |
| REQ-KAP-023 | Safe extraction: canonical relative POSIX paths only; reject absolute paths, `..`, drive letters, backslashes, NUL, symlinks and hardlinks, duplicate entries (also case-folded), entries missing from or extra to the manifest; enforce limits (entries, per-file bytes, total uncompressed bytes, compression ratio, path length). Extraction streams each entry into a new empty staging dir with `is_within` checks. | AC: a table-driven malicious-archive test suite (traversal, abs, dup, symlink, bomb, oversize, bad manifest hash) all rejected, staging removed, kb-home untouched. |
| REQ-KAP-024 | Export is deterministic and reproducible: sorted entries, fixed timestamps and modes, canonical JSON, no host data. Same release exported twice gives byte-identical files. | AC: two exports sha256-equal; also equal across two temp dirs and with different umask. |
| REQ-KAP-025 | Import and activation are atomic: stage, verify, move into place, then switch the `active.json` pointer via atomic write. A failure at any point leaves previous state. Activation is separate from import (`import` does not activate unless `--activate`). | AC: fault-injection tests at every step boundary keep the old active release and leave no half-installed dir. |
| REQ-KAP-026 | Multiple releases can be installed; `list` shows id, digest, label, completeness, active flag; `rollback` re-activates the previously active release safely and records it; removal of an active release is refused. | AC: install A, B, activate B, rollback gives A and its digest. |
| REQ-KAP-027 | An imported package never enables an unverified FIX_ENABLED rule. Gates are recomputed locally; package self-assertions are not trusted. Default: refuse import. Option `--downgrade-unverified` imports with those rules capped to DETECT_ONLY and a W-code. | AC: package with a FIX_ENABLED rule lacking evidence is refused; with the option it is capped and the original is retained in provenance. |
| REQ-KAP-028 | Packages contain no secrets and no customer data: no credentials, tokens, absolute paths, hostnames, or customer module code; redaction scan runs at build and at import. | AC: canary-secret build test fails the build; fixtures only from official or synthetic sources. |
| REQ-KAP-047 | Schema and framework compatibility: manifest declares `package_format`, `min_framework`, `max_framework` and schema versions; import and activate refuse incompatible releases. | AC: tests for newer format, older framework, unknown schema version. |

### G. Release lifecycle

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-029 | The lifecycle has ordered, individually re-runnable steps with recorded results: acquire, verify, extract, classify, evidence, candidates, schema-validate, duplicate/conflict, rule-tests, coverage, gates, build package, validate package, publish locally, export, import and activate, record provenance. | AC: `release build --dry-run` prints the step plan; each step writes a step result to the build log; a failed step stops later steps. |
| REQ-KAP-030 | Incremental updates never destroy or silently replace validated knowledge. A new release is a new directory with `parent_release`; unchanged records keep their bytes; any changed or removed record is listed in a release diff. | AC1: release diff test. AC2: replacing a VERIFIED evidence record by a different one without explicit `--supersede` fails. |
| REQ-KAP-031 | Manual versus automatic conflicts are explicit: a manual (or reviewed) record always wins by default; the generated alternative is stored as a `conflict` item needing a decision; resolution is recorded. | AC: test for each of: same rule id, same scope detector, disposition clash. |

### H. Coverage and gates

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-032 | Eight separately reported metrics with explicit denominators: source retrieval, file scan, change classification, change disposition, evidence, rule validation, fix verification, version transition. No blended score. A zero denominator is `NOT_APPLICABLE`, never 100%. | AC: unit test per metric on a fixture; output shows `numerator/denominator` and the denominator definition. |
| REQ-KAP-033 | Independent cross-checks: upgrade scripts, independent comparison (tool-independent file listing), existing KB, known regressions, benchmark sets. Recall is reported only against a named benchmark set and states its size; otherwise `NOT_MEASURED`. | AC: no output contains a recall figure without `benchmark_id`; test enforces. |
| REQ-KAP-034 | Coverage gates block a `COMPLETE` claim when: a required source is missing, files are unaccounted or `PENDING`, classification failures are hidden, unresolved changes are omitted, evidence is absent where required, or manifests are inconsistent. `PARTIAL` releases are allowed when limits are explicit and non-empty. | AC: one test per gate, plus a test that `PARTIAL` with empty limits is invalid. |
| REQ-KAP-035 | A coverage manifest (JSON) records declared scope, inventories, per-state file counts, the eight metrics, cross-check results, gate results, limits, and tool and schema versions; it is part of the digest. | AC: manifest consistency test (counts match ledger and file accounting). |

### I. Migration integration

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-036 | `migrate` resolves the active release (kb-home from `--kb-home` or `ODOOFLUX_KB_HOME`), verifies its digest, loads its tree via the loader, and falls back only to the implicit built-in release when no release is active. A broken active release fails closed. | AC: tests for no-active, valid, corrupt, missing-dir. |
| REQ-KAP-037 | Before planning, `migrate` checks version-transition coverage of the active release for each step and surfaces missing or partial coverage as report warnings and in the human summary. | AC: report warning code `KAP_TRANSITION_NOT_COVERED` per step. |
| REQ-KAP-038 | Existing precedence and legacy disposition (`legacy_overlap`, RETIRED categories) are unchanged; release rules pass through the same binder. | AC: existing legacy overlap tests pass with an active fixture release. |
| REQ-KAP-039 | Only authorized and verified fixes run: FIX_ENABLED rules from a release run only when local gates still pass at load (REQ-KAP-027) and the existing `rule_maturity` cap and SC-005 apply. | AC: test with a FIX_ENABLED rule lacking VERIFIED-or-documented evidence is capped. |
| REQ-KAP-040 | The report records release id and digest (and completeness, and `builtin` marker only when a release is active). The report schema is extended compatibly: optional `knowledge_release` object; `schema_version` is `1.0.0` when absent and `1.1.0` when present (OD-K4). | AC1: no-release report bytes identical. AC2: report schema accepts both. AC3: renderers (JSON, HTML, SARIF, text) show the release line. |
| REQ-KAP-041 | Missing or partial knowledge is never treated as success: absence of a rule for a transition yields `NOT_COVERED`/warning, and the run status cannot be `VERIFIED_SUCCESS` on a not-covered step. | AC: status decision test with not-covered step downgrades per existing status rules (no new status values). |
| REQ-KAP-042 | Existing rollback, dependency (L3), and release-status contracts are unchanged. | AC: existing contract tests pass unmodified; no edits to their expectations. |

### J. Governance, audit, testing

| ID | Requirement | Acceptance criteria |
|---|---|---|
| REQ-KAP-043 | Technical completion is separate from human certification (ADR-019). Items needing human sign-off stay `PENDING_HUMAN_REVIEW` with a register fragment in `docs/reviews/fragments/`. Built-in FIX_ENABLED rules are grandfathered, not re-gated. | AC: tasks.md has no task that marks a certification part done. |
| REQ-KAP-044 | Default tests are offline with pinned synthetic fixtures. Live retrieval and Docker are opt-in via `ODOOFLUX_KAP_LIVE_TESTS=1`, `ODOOFLUX_KAP_CLONES=<dir>`, `ODOOFLUX_KAP_DOCKER_TESTS=1`. | AC: opt-in tests skip cleanly and are listed as opt-in by the RTM tool markers (`skipUnless(`). |
| REQ-KAP-045 | An audit trail records acquisition, build, import, activation, rollback using the existing hash-chained `AuditLog`. | AC: `verify_chain` passes after a scripted lifecycle; tamper is detected. |
| REQ-KAP-046 | Redaction uses `utils/redaction.py` (OD-K9) on logs, manifests and packages; error messages never print file contents or credentials. | AC: canary tests for logs and package build. |

## Non-goals

- Automatic FIX_ENABLED, automatic rename confirmation, automatic AUTO_TRANSFORM (ADR-018 stays).
- Downloading knowledge from a hosted service, a package registry, auto-update, telemetry.
- Package signing and trust PKI (digest pinning only, OD-K5).
- Bypassing Enterprise authentication or licence; redistributing Enterprise code (snapshots of Enterprise sources are never exported in packages, only derived metadata the owner authorizes, OD-K6).
- Runtime-validated claims (`RUNTIME_VALIDATED` unreachable today, no KAP output claims it).
- A database, a daemon, a GUI.
- Writing the actual KB rule corpus (stays in KNOWLEDGE_BASE_BACKLOG.md); KAP builds the machinery and a small synthetic fixture release.
- Editing existing specs 001 to 010.

## Success criteria

| ID | Measure |
|---|---|
| SC-K01 | Zero network syscalls in the migrate path (socket-blocked test). |
| SC-K02 | Built-in-only outputs byte-identical (golden hashes) before and after. |
| SC-K03 | Malicious-archive suite: 100 percent rejected, kb-home unchanged. |
| SC-K04 | Two exports of one release are byte-identical. |
| SC-K05 | A synthetic two-version fixture pair flows through every lifecycle step offline and ends `COMPLETE` with eight metrics printed with denominators. |
| SC-K06 | Every REQ-KAP has at least one task and one named test (RTM). |

## Assumptions

- Source of truth for versions remains `versions.json`; KAP does not add Odoo majors by editing code (REQ-KAP-016).
- Python 3.10+, Linux/macOS/Windows path semantics handled via `PurePosixPath` for archive names.
- The report schema evolution reading (minor bump for additive field) is an assumption needing OD-K4.
