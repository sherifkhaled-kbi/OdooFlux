# Verification: feature 011, Knowledge Acquisition Pipeline (KAP)

Date: 2026-11-08. Recorded by the orchestrator at T090. Nothing is committed or pushed. **Technical verification only: no production certification, no human approval, no verification on a real Odoo corpus.**

## 1. Final verification run (once, at the integration milestone)

| Check | Command | Result |
|---|---|---|
| Release and knowledge gates | `tools/ci_check.sh all` (gates step) | `knowledge validate` records=200 rules=91 errors=0 warnings=0; compatibility matrix up to date; support statement up to date; RTM gate PASS |
| Full regression suite | `tools/ci_check.sh all` (test step), `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .` | **2575 tests, OK, 40 skipped, 1 expected failure**, about 103 s |
| Wheel build and installed-wheel tests | `tools/ci_check.sh all` (package step) | 4 tests OK |
| Wheel assets and install (opt-in, run) | `ODOOFLUX_PACKAGING_INSTALL=1 PYTHONPATH=src python3 -m unittest tests.integration.packaging.test_wheel_install tests.integration.packaging.test_wheel_assets` | 9 tests OK; wheel has 539 entries incl. all 10 new schemas and 5 extraction templates; no tests, fixtures, snapshots, kb-home data or .pyc inside |
| Security and provenance regression | 20 named modules (redaction boundaries, release safety, loader cap, provenance, official identity, git read-only and hostile-repo, archive, package validate/importer/snapshot rule, KAP import graph, knowledge-root guard, extract boundary, AI gateway factory and proposer, provenance e2e, customer-code guard, import graph) | 202 tests OK, 1 expected failure |
| RTM | `python3 tests/unit/release/rtm_tools.py` and `--strict` | PASS: TESTED=138, RECORD=1, DEFERRED_KB=0, UNMAPPED=0 (92 product + 47 KAP requirements) |
| Documentation consistency | script over README, TECHNICAL_USAGE, quickstart, PROJECT_STRUCTURE and the KAP notes and fragments | 0 broken relative links; flag, path and env-var checks recorded in docs/reviews/automated/DOC-verification-kap.md (268 flag references, 0 unknown) |
| First full run | same command | 1 failure: a count pin (`92` requirements) in `test_rtm_completeness` after the 47 KAP rows were added; the pin now states 92 product + 47 KAP. Not a gate weakening. |

## 2. Requirements and evidence

The RTM lists all 47 REQ-KAP requirements with their tasks and the test modules that cite them (`docs/planning/REQUIREMENTS_TRACEABILITY_MATRIX.md`). 46 are evidenced by tests citing the requirement id. **REQ-KAP-043** (technical completion is separate from human certification) has no test by nature and is satisfied by a verification record: `docs/reviews/fragments/kap.md`. No placeholder evidence was added and the RTM gate was not changed. Requirements whose evidence is partial are named in the matrix Gap column: REQ-KAP-002, 009, 027, 033, 034, 039, 043, 044.

## 3. Tests by state

| State | Count | Detail |
|---|---|---|
| Passed | 2534 | of 2575 run in the default suite (2575 - 40 skipped - 1 expected failure) |
| Failed | 0 | after the count-pin update |
| Skipped (opt-in or missing optional dependency) | 40 | AI live provider 11 (`ODOOFLUX_AI_TESTS`), Docker runtime 9 (`ODOOFLUX_RUNTIME_TESTS`), JS adapter 5 (`ODOOFLUX_JS_ADAPTER_TESTS`) plus 3 (tree-sitter not installed), benchmarks 4 (`ODOOFLUX_BENCH`) plus 1 (`ODOOFLUX_BENCHMARKS`), packaging install 4 (`ODOOFLUX_PACKAGING_INSTALL`, run separately above), KAP live clone 1, KAP live fetch 1, KAP Docker probe 1 |
| Expected failure | 1 | `insteadOf` identity gap in the git adapter, pinned as documentation |
| Opt-in NOT executed (unauthorized or unavailable) | live AI, Docker runtime, live KAP clone/fetch/Docker, JS tree-sitter structural path, benchmarks | the JS structural branch has never run (tree-sitter absent) |
| Known flaky | 2 observed once | `test_official_local_identity` SSH normalisation and two reporting tests failed once in a full run each and did not reproduce in three consecutive kap runs; treated as order-dependent, watch |
| Requiring live AI, network or Docker, not authorized and not run | all of the above opt-in tests | no live AI call, network acquisition or Docker execution happened in this feature |

## 4. Requirements lacking tests

None, except REQ-KAP-043 (record, see section 2).

## 5. Unsupported paths and open items

- **Unsupported or untested:** no real Odoo corpus build was run (every fixture is synthetic); live provider calls; Docker; network acquisition; JS structural extraction with tree-sitter; git versions other than 2.43.0; Enterprise acquisition path verified offline only.
- **Support statement:** unchanged by KAP: 0 supported paths.
- **Open product decisions and human-review items:** `docs/reviews/fragments/kap.md` (all PENDING_HUMAN_REVIEW) and the register appendix. The most consequential: KAP-OD-K13 (carried-forward built-in FIX_ENABLED rows: grandfathered at load, refused at import, so the default consumer import of a pipeline-built release needs `--downgrade-unverified`), M8 completeness rule, first real-corpus build certification.
- **Deferred by owner:** approval identity, authentication and RBAC (FE-1).
- **Known limitations found at closure:** a mistyped or empty `--kb-home` runs the built-in release by contract (the report names the built-in release and digest); unofficial evidence cannot be packaged (E002); the source registry schema has no `repository` key (an explicit repository needs a candidate-source file); `release show` does not re-hash; `candidates generate` refuses while PROPOSED candidates are pending; ledger edits outside the pipeline are not detected by resume; the pipeline auto-accepts verified candidates; AI proposal is not wired into the pipeline and `ai propose` can reach an external provider only with explicit authorization.

## 6. Defects found by verification and fixed during the feature (selection)

Release diff did not recognise the real release layout; manifest secrets were written verbatim (now scrubbed before hashing); URL credentials leaked through audit, package scan and provenance; git adapter: `refs/replace` substitution, trailing-newline revision, unvalidated object ids, path option injection; candidate regeneration could overwrite a rejected record; evidence ids could be reused; `candidates generate` identity failed for local clones; pipeline-built release missed `schemas/`; **the load-time FIX_ENABLED cap trusted a rule row's own `origin` claim (fixed: grandfathering is by byte identity with the shipped row)**; view-index rules read the built-in tree with an active release; three security-guard violations in new code (dynamic import, subprocess for author name, git adapter allow-listed with a pinned command set).

## 7. Token usage (runtime-reported per completion; no limit was enforced)

Sonnet: 1 stream (Phase 1 plan), 134,518 tokens. All other streams Haiku. Resumed agents are shown with their latest reported figure; the runtime may report resumed totals cumulatively, so the sum is an estimate.

| Stream | Tokens |
|---|---|
| Phase 0 assessment (Haiku) | 102,330 |
| Phase 1 architecture plan (Sonnet) | 134,518 |
| F foundation T001-T005 | 101,361 |
| T030 | 67,103 |
| S1 | 90,513 |
| S2 | 95,297 |
| S3 | 122,828 |
| S1b | 118,142 |
| S2b | 112,241 |
| S3b | 144,971 |
| S1c | 169,154 |
| S1d | 76,005 |
| S2c | 219,661 |
| S3c | 159,004 |
| S1e | 161,498 |
| S2d | 183,223 |
| S1f | 185,814 |
| S3d | 151,579 |
| S2e | 210,811 |
| S7 | 189,295 |
| S7b | 130,773 |
| S2f | 113,295 |
| S6 (resumed; latest figure) | 159,268 |
| S1g | 162,358 |
| S8a | 114,828 |
| S8b | 143,633 |
| S9a (resumed; latest figure) | 234,824 |
| S10 | 138,288 |
| P-WRITER | 200,989 |
| S11 | 117,301 |
| S12 | 217,570 |
| S12b | 73,001 |
| S12c | 105,030 |
| S13 (resumed; latest figure) | 257,029 |
| S14 | 155,956 |
| S15 (resumed; latest figure) | 315,666 |
| S16 | 166,198 |
| S17 | 87,062 |
| S18 | 151,502 |
| S19 | 160,258 |
| S20 | 447,247 |
| S21 | 197,398 |
| S22 | 126,722 |
| **Total (estimate)** | **6,771,544** |
