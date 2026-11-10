# Feature 012 — Verification record

Date: 2026-11-09. Baseline commit: `1c7f33c` (branch `main`). **Nothing is committed or pushed**; the working tree holds all
Feature 012 changes (new files plus the edits listed in tasks.md). No live upstream access, no real Enterprise credentials,
and no change to any real Knowledge Base were used at any point.

Status vocabulary: EXECUTED / SKIPPED / BLOCKED / NOT_AUTHORIZED. A criterion is PASS only when a test executed against the
behaviour. All evidence below is **synthetic** (local bare git repositories, synthetic clones, fake remotes). There is no
real-source evidence.

## Final runs (executed on this working tree)

| Run | Command | Result |
|---|---|---|
| Full regression | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .` | EXECUTED: 3750 tests OK, 60 skipped (opt-in wheel tests), 1 expected failure (before Feature 012: 2575 OK, 40 skipped) |
| Wheel + installed-wheel tests | `ODOOFLUX_PACKAGING_INSTALL=1 PYTHONPATH=src python3 -m unittest discover -s tests/integration/packaging -p 'test_*.py' -t .` | EXECUTED: 29 tests OK, none skipped (the extra skips in the full run are these opt-in tests); includes 11 clean-wheel workflow tests (fresh install, Community+Enterprise, incremental, failure recovery, no-op/offline) |
| CI gates | `bash tools/ci_check.sh gates` | EXECUTED: OK (knowledge validate, matrix, support statement, RTM) |
| RTM gate | `python3 tests/unit/release/rtm_tools.py` | EXECUTED: PASS (TESTED=138, UNMAPPED=0) |
| Guards | import graph, version literals, no-customer-code-execution, schema checker, knowledge-root guard | EXECUTED: OK (inside the full run) |
| Offline CLI smoke | `knowledge check/update/status/history` against empty temp kb-homes | EXECUTED (see quickstart.md) |
| Live upstream acquisition | any online `check`/`update` | NOT_AUTHORIZED, NOT_RUN |
| Real Enterprise access | any call with a real token | NOT_AUTHORIZED, NOT_RUN |
| Pilot 16.0 → 17.0 Community | opt-in real-source build | NOT_AUTHORIZED, NOT_RUN |
| Branch protection / GitHub CI on this change | | NOT_RUN (nothing pushed) |

## Acceptance matrix

| ID | Result | Evidence | Limitations |
|---|---|---|---|
| AC-01 Catalog covers Community 12–19 | PASS | `update/catalog.json` v3 (both families, same eight versions, licence/redistribution metadata); `test_catalog.py`; installed-wheel catalog digest equals the checkout (`test_update_wheel.py`) | Enterprise entries exist too (requested). No pinned SHAs by design; SHAs resolve at acquisition. Licence ids are maintainer-declared, not machine-verified |
| AC-02 No manual source registration | PASS | `planner.py` builds registry specs from the catalog; `acquire.py`; `test_update_orchestrator.py` fresh install without any source registration or plan file | Synthetic remotes only (local bare repos) |
| AC-03 `check` discovers updates | PASS | `discovery.py`, `test_discovery.py`, `test_check_cli.py` (changed revisions, new versions, per-source statuses) | Remote answers are faked (`ls_remote` seam); no live ls-remote executed |
| AC-04 `check` does not modify the installed KB | PASS | kb-home tree hashed before/after in human, JSON, offline and env runs | — |
| AC-05 `update` needs no manual plan | PASS | `orchestrator.py`; `test_update_orchestrator.py` | Synthetic repos |
| AC-06 Feature 011 services reused | PASS | `run_build`, `activate`, release store, provenance, gates, import/export all reused; orchestrator composes them | Pipeline extended minimally (pair key, retained adapter, inventory emission, supersede hook), documented in spec.md TM list |
| AC-07 No-op updates idempotent | PASS | NOOP only when planner NOOP and `needs_build` is false; integration test: second run creates no release | Decision uses persisted build inputs; absent inputs force a build |
| AC-08 Incremental updates work | PASS (limited) | changed-revision, multi-source, carry-forward integration tests | Saving is network/acquisition only: unchanged sources are rebuilt from retained verified snapshots, extraction is recomputed |
| AC-09 New major versions discoverable | PASS | `test_discovery.py` (new version from fake heads; `saas-*`/`master` ignored; never a planned target) | Fake heads only; no live upstream |
| AC-10 Valid detection rules become active | PASS | unified/orchestrator integration: generated DETECT_ONLY rules activate when gates pass | Synthetic corpus only; real-corpus rule yield unknown |
| AC-11 Fully verified deterministic fixes become active | PASS (synthetic) | `machine-confirmation/1` + `fix-certification/1` issued by the pipeline for S1/S2/S3; `tests/integration/kap/test_autofix_e2e.py` (20) and `_extra.py` (11): FIX_ENABLED after `knowledge update` activation, exact `migrate --fix` output, idempotent second run, tamper cases demoted at load/import/activation, decoys and insufficient evidence stay DETECT_ONLY; Sonnet adversarial review findings fixed with regression tests | Synthetic sources only; narrow coverage by design (module-level symbols resolved via imports); L2 re-proof needs retained blobs; real-corpus yield unknown |
| AC-12 Unverified fixes remain disabled | PASS | load-time cap (KAP_FIX_CAPPED), gate 1–5, `FIX_NOT_TRUSTED` at build and activation, P10 at import; `test_certified_fix_trust.py` adversarial cases | — |
| AC-13 No interactive prompt | PASS | `update`/`check`/`status`/`history` are non-interactive; all tests run non-interactively | Not proven by a TTY test; no `input()` use in the new CLI |
| AC-14 No silent auto-fix downgrade | PASS | `activation.evaluate`: CAPABILITY_LOST/DOWNGRADED, FIX_NOT_TRUSTED; `supersede` never clears FIX_NOT_TRUSTED; `--downgrade-unverified` is never used by update | Semantic supersede only for GENERATED rules with an equivalent replacement |
| AC-15 Activation is atomic | PASS | existing `activate` (pointer swap) reused; injected faults → ROLLED_BACK with previous pointer verified | POSIX file semantics |
| AC-16 Failed updates preserve the previous release | PASS | orchestrator tests: tampered/missing retained snapshot, blocked gates, capability loss, ENTERPRISE_COMPAT, fault at pointer | A built-but-blocked release stays INSTALLED (never active) |
| AC-17 Provenance and integrity gates enforced | PASS | gate 1–5, P01–P12, `verify_provenance`, release integrity before activation; Enterprise coherence enforced by recomputation | Identity remains a declared origin, as in Feature 011 (no cryptographic proof) |
| AC-18 OD-K13 handled safely | PASS | D3: byte-identical shipped FIX_ENABLED rows accepted at import; anything else P10; audit in `release_installed.details.inherited_trust`; adversarial tests | A modified shipped row is not inherited |
| AC-19 Offline commands: zero network | PASS (bounded) | `--offline`/`ODOOFLUX_OFFLINE`: no subprocess/ls-remote call (mocks), packaging test with a socket/subprocess guard, kb-home untouched | Guard is in-process, not kernel-level isolation |
| AC-20 Normal migration stays offline | PASS (bounded) | migrate integration tests count socket calls = 0; migrate never imports the update acquisition modules | No kernel-level isolation either |
| AC-21 Wheel installation works | PASS | 18 packaging tests: wheel ships catalog + four new schemas; the four commands work from a clean venv outside the checkout | Wheel built from the working tree, not a commit; no PyPI publication checked |
| AC-22 Update reports show real changes | PASS (synthetic) | `UpdateResult`/`report.py`; counts derived from capability comparison and tested with 7/0/13-style numbers; distinguishes zero changes from unavailable comparison | Never run against a real corpus |
| AC-23 Existing Feature 011 tests pass | PASS | Full suite OK. Existing assertions changed (all for intended contract changes): `test_package_builder::test_enterprise_derived_refused_by_default`, pipeline_e2e variant F, quickstart 2b0/3b | Listed in INTEGRATION_NOTES.md |
| AC-24 Production certification not inferred | PASS | every result and doc carries `production_certification: NOT_GRANTED` and "migration support not established" | — |
| AC-25 Synthetic and real-source evidence separate | PASS | no real-source evidence exists; every result above is labelled synthetic; real-source runs NOT_RUN | — |

## Material findings and open decisions

1. **Automatic fixes (AC-11) are implemented** under plan Addendum F (S1, S2, S3). An independent adversarial review found four exploitable gaps (generated row trusted without confirmation; L1 forgery; L2 skippable at activation; unsound call-site rewrite on stores/strings/`__all__`); all were fixed with failing-first tests. Residual: an S1 pair with an unrelated module-level mutation (for example `os.sep = 'x'`) still proves; machine confirmation has no authenticity beyond the manifest digest and L2 where blobs exist; `fix_templates.eligible` still accepts an absent-origin row for issuance (trust refuses it).
2. **Enterprise confidentiality.** Provenance failure now fails closed for installed releases. Still open: generated rule messages and `ledger list/show` print Enterprise symbol identifiers; Enterprise source ids/revisions appear in check/update/history output. Public export is fail-closed; `package export --public` does not exist (safe refusal, documented).
3. **Deviation D-A.** Enterprise snapshot manifests (paths and hashes, never content) ship inside the internal release, which is never exported.
4. **Per-version inventory strictness.** A release with an inventory for only one version of a pair makes every dependent module incomplete (fail-closed; may withhold fixes).
5. **Defects fixed this round:** `refresh --search-candidates`; `remote_git` absent commit now `REVISION_UNAVAILABLE`; stale DOC-verification-kap lines; confidentiality view fail-open.
6. **Gaps:** the online HTTPS path of the plain `odooflux knowledge update` against real GitHub has never been executed (not authorized); wheel workflow tests drive the installed package through documented seams (no sound local-repo hook for the plain CLI exists, and none was added); `knowledge-check/1` and `knowledge-history/1` have no shipped schema; `kap_source` lacks a GIT_ENTERPRISE adapter; POSIX-only locks; offline guard is in-process.
7. **Security notes.** The Enterprise token is visible in the git child's environment to same-user processes while git runs; the fetch size guard has bounded overshoot; HTTPS auth exercised only through stubs and local repositories.

Production certification: **NOT_GRANTED**. Migration support for any newly discovered version: **NOT_ESTABLISHED**. Real-source pilot 16.0 to 17.0: **NOT_RUN** (no authorized local official snapshots).

## RC closure addendum (2026-11-10)

- S1/S2/S3 proofs refuse import-time module effects (`MODULE_EFFECT`); Enterprise symbol names, rule text and source ids/revisions are withheld in shareable output; `knowledge-check/1` and `knowledge-history/1` schemas ship; scoped `update --from N --to M` acquires only that pair (planner), `ODOOFLUX_FETCH_TIMEOUT` added.
- Full regression: 3782 tests OK (65 skipped opt-in, 1 expected failure). Wheel workflows 29/29 (system python with setuptools). Gates rc=0.
- Real-source pilot 16.0 to 17.0: NOT COMPLETED. Scoped acquisition fetched only 16.0 (verified, cached) and 17.0 stalled twice (git `curl 28`, under 1000 B/s for 60 s, then `bad pack header`; plain `git fetch` reproduces it). No real-source FIX_ENABLED, DETECT_ONLY or BLOCKED result exists. Production certification: NOT_GRANTED.
