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
- Final verification on the finished code (2026-11-11, one run): full regression 3827 tests OK (65 skipped opt-in, 1 expected failure), wheel workflows 29/29 (system python with setuptools), gates rc=0 (knowledge validate, matrix and support statement current, requirements traceability PASS). Earlier counts in this file are superseded.
- Real-source pilot 16.0 to 17.0: SUPERSEDED BY THE SECTION BELOW (completed 2026-11-11). Earlier text: NOT COMPLETED. Scoped acquisition fetched only 16.0 (verified, cached) and 17.0 stalled twice (git `curl 28`, under 1000 B/s for 60 s, then `bad pack header`; plain `git fetch` reproduces it). No real-source FIX_ENABLED, DETECT_ONLY or BLOCKED result exists. Production certification: NOT_GRANTED.

## Real-source pilot, Odoo Community 16.0 to 17.0 (executed 2026-11-11)

Plain `odooflux knowledge update --from 16 --to 17` in an isolated kb-home against `https://github.com/odoo/odoo.git`
(no Enterprise credentials; the user's KB untouched). Acquired only 16.0 (`cb69381...`) and 17.0 (`8d5d88a...`).
Outcome `ACTIVE`, release `kr-15b35d46b2a4`, completeness `PARTIAL`, rc 0, 17 pipeline steps.

| Fact | Value |
|---|---|
| Ledger changes | 156,921 (ADDED 66,892; UNKNOWN 48,538; REMOVED 30,571; BEHAVIOUR_CHANGED 7,266; other 3,654) |
| Candidates / accepted / refused | 3,345 / 2,786 / 559 |
| Refusal code of the 559 | all `A002` (duplicate of an accepted rule: same step, detector and params), verified by replay |
| Rules in the release | 2,877 = 2,786 generated (`DRAFT`) + 91 shipped; generated FIX_ENABLED: **0** |
| Automatic-fix proofs | **0** of 37,847 eligible (SIDE_FILE_MISSING 27,924; NO_FORWARD 7,276; ENTRY_SUBJECT 2,591; S3_NOT_IDENTITY 44; NOT_PLAIN_DEF 4; STAR_IMPORT 2) |
| SIDE_FILE_MISSING (sample 3,000) | 98.7% file absent in 17.0; 1.3% absent at that path (same name elsewhere); 0 mapping defects |
| Coverage | M1 100%, M2 15.7%, M3 69.0%, M4 1.7%, M5 100%, M6 100%, M7 n/a, M8 100%; G-FILES and G-DISP fail as allowed partial |
| `coverage/inputs.json` | 52,465,276 bytes (was 237,074,142; limit 67,108,864) |
| Timings | extract 2 min 20 s; candidates 35 min 9 s; whole build 14:21:28 to 15:02:24 |

`migrate --fix` on a disposable 16.0 module (isolated release): 1 edit applied (manifest version bump; **correction 2026-11-11:** it comes from the
uncertified legacy layer, `apply_manifest_fixes`, not from a shipped FIX_ENABLED row: the KB row `*.manifest.version-prefix`
is DETECT_ONLY and opt-in), 0 rejected, L1 to L3 PASS; 3 findings `needs_review` (`attrs` removal, `name_get`, info). A second
run applied 0 edits, wrote 0 files and left the tree byte-identical (it adds a "manifest declares 17.x" warning).
No generated rule produced a finding or an edit on that fixture.

Defects found by this pilot and fixed (each with failing-first tests): quadratic rename pairing; evidence id space capped at
`EV-999`; per-candidate re-reads of pending evidence; per-change re-parsing in the automatic-fix prover; whole-ledger
copy and validation per accepted candidate; cubic authoring check A005; coverage bundle over the package size limit.
Observed, not changed: the step summary truncates refusal codes (hides `A002`); 559 changes stay `UNRESOLVED` instead of
being linked to the equivalent accepted rule.

Limits: one pair, Community only, one fixture; machine suspend killed one earlier run (timeout across suspend); not a
production certification. Production certification: NOT_GRANTED. Migration support for other pairs: NOT_ESTABLISHED.

## Automation slice 1: experimental attrs/states fixer and legacy-layer findings (2026-11-11)

Plan: [automation-roadmap.md](automation-roadmap.md). Implemented: T0 (legacy XML fixer gated by target version), T1
(`odooflux migrate --fix --experimental-fixes`, registry in `rules/experimental/`, report `fix_class` and
`summary.experimental`), T2 (strict-subset `attrs`/`states` conversion; `16-17.xml.attrs-removed` and
`16-17.xml.states-attribute-removed` stay DETECT_ONLY and uncertified). D1 (a field named like an expression-context
variable, such as `uid`, was converted) was found by QA and fixed with failing-first tests.

Measured on 249 official 16.0 community modules copied from the cached snapshot and renamed with a `kbi_` prefix
(unprefixed names collide with the release inventory, and the dependency-coverage check correctly withholds fixes):

| Measure | Result |
|---|---|
| `attrs` occurrences in the corpus XML | 3,835 |
| converted by the experimental fixer | 944 (24.6 %) |
| refused, with reason | 2,647: not-in-form 1,408; falsy-literal 766; nested-view 373; non-literal-value 39; unsupported-operator 31; malformed-domain 11; dotted-field 10; same-modifier-exists 9 |
| semantic check of the 944 conversions (independent evaluator over each domain's literals plus other and None) | 944 equivalent, 0 mismatches |
| XML files changed / became malformed | 243 / 0 |
| second pass | 0 edits, no file differs |
| classified not-in-form refusals | 99 % are inherited-view fragments (`position=` patches), not unsafe semantics |

Coverage so far is 24.6 % of `attrs` occurrences. A path to about 90 % of `attrs` (plan, not measured): inherited
fragments (up to +36.7 points), falsy literals (up to +20.0), nested views (up to +9.7).

## Report hash audit (VR-5)

Scope: `tests/golden_fixtures/reports/**` and `PRE_CHANGE_HASHES` in `tests/unit/reporting/test_report_release.py`,
against HEAD. Method: structural diff of the 10 scenario goldens; line diff of the 60 snapshot files; all 7 renderers of
the 10 scenarios rendered from HEAD (`git archive`) and from the working tree, each changed path or line mapped to a
category. Every HEAD pin reproduces HEAD output and every current pin reproduces current output.

| Cat | Meaning | Changed paths |
|---|---|---|
| A | dry run: `recovery.reversible`/`rollback_cmd` cleared, `summary.edits.planned`, `applied` 0 | 24 |
| B | unresolved findings only: `location`, `reason_not_fixed`, `developer_action` (11 findings) | 33 |
| C | PARTIAL: `status`, `status_reasons`, `modules_by_status`; additive `refused_files` | 25 |
| D | `location.column` is `UNKNOWN` (inside B; no int column in any golden) | 11 |
| E | dry run: `modules[].reversible` false | 7 |
| F | `validation` key on edits | 0 (no golden carries it) |
| G | `fix_class` / `experimental` | 0 |
| H | unexpected | 0 |

JSON: 89 changed paths in 10 goldens; `reconcile` checks pass (modules_by_status, findings, edits applied/planned/rejected
against module sums; FIXED findings have no unresolved-only field; fix-mode recovery and reversible unchanged).

Hash table: 70 entries, 54 changed against HEAD (json 20, html 10, sarif 12, terminal 12) and 16 unchanged (sarif and
terminal of blocked, install_verified, provisional, verified_success). Sarif changes are one `properties.reason_not_fixed`
per unresolved finding (11 per form); the sarif message already carried the action. Unchanged terminal pins are explained
by the default terminal not listing FIXED findings and by no dry-run wording change there.

Snapshots (plain and colour, widths 60/80/120): every added line is A, B, C, D or the PA-6 table layout; no overflow or
truncation at any width.

Unexpected finding, fixed: the HTML badge and tile emitted the raw status as the class, so
`class="badge status-PARTIAL — DEVELOPER ACTION REQUIRED"` split into several tokens and matched no CSS rule. Fix:
`_status_css_class` in `reporting/html/html.py` (first word of the status) and a `.status-PARTIAL` colour. Failing-first
test `test_html_status_class_is_one_css_token`. The 10 html pins were re-pinned; each html output differs from its
pre-fix form only by the CSS rule and the class token.

Corrected: the `PRE_CHANGE_HASHES` header claimed the sarif pins were unchanged and that scenarios without unresolved
findings were unchanged. Both were wrong and the comment is rewritten.

Observations, no change made:
* Dry-run goldens with `fix_applied` findings and `fixes` greater than edit files (for example `static_validated`: 3 fixes,
  1 edit file) are synthetic. A real dry run never sets `fix_applied`, so it cannot produce FIXED findings. `planned` counts
  edit files, which matches the fix-run `applied` unit (`run.py` adds `len(writable)`).
* `refused_files` is empty in every golden, so `changes_kept` is not covered by a golden.
* The D3 bullet under Known defects is stale. `test_known_defects_d2_d4.D3DryRunClaimsReversible` already asserts the fixed
  behaviour and passes.
* `tests/unit/reporting/renderer_hashes.json` is untracked, referenced by nothing, and matches 10 current and 22 HEAD pins.
  It is stale and not part of this audit.

Focused tests: `discover -s tests/unit/reporting`: 162 OK, 1 skipped. `discover -s tests/integration/reporting`: 36 OK.
`test_report_release`: 10 OK. `tests.integration.test_provisional_corpus` and `tests.unit.knowledge.kap.test_migrate_coverage`:
14 of 16 pass. The 2 failures compare a real `migrate` JSON report with `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json`
and the `kbi_demo` expected report. Both pass at HEAD. The differing paths are: `developer_action` on finding 12 (the AF-9
addition, absent from the golden), finding 12 and 17 `id`/`message`/`severity`/`suggestion`, `status_inputs_digest`, and
`summary` findings and open_findings info/warning. This is golden drift in the `kbi_demo` area, which was not touched.
The reporting renderers are not implicated: both tests compare JSON only.

Outcome: report output is consistent with the approved categories, with one renderer defect fixed. Open: the `kbi_demo`
golden drift (owner of `kbi_demo`), the untracked stale `renderer_hashes.json`, and the stale D3 bullet.

## Known defects (pinned by `tests/regression/test_known_defects_d2_d4.py`, behaviour deliberately unchanged)

* **D2, confirmed certified-mode correctness defect.** The legacy `states=` rewrite
  (`legacy_rules._convert_states_to_invisible`) runs under plain `--fix`, is uncertified, and converts without checking
  that the view's model has a `state` field, so it can produce a view Odoo 17 rejects. It predates Feature 012. It does not
  change the Feature 012 automatic-fix results (no generated FIX_ENABLED rule exists), but it does mean plain `--fix` is
  not limited to certified rules: it also runs the legacy regex layer.
* **D3 (fixed).** A `--dry-run` report now states `recovery.reversible: false` and no rollback command, since nothing was
  written. `tests.regression.test_known_defects_d2_d4.D3DryRunClaimsReversible` asserts this and passes (FC-3, re-run
  2026-11-11).
* **D4 (resolved as detection; article-based, not verified against 17.0 source).** A 16 to 17 report no longer flags
  `<tree>`: the `<tree>` to `<list>` row is gated to the 18 and 19 targets, because the community article places that change
  at v18 and `<tree>` is valid for 17. A 17 to 18 report keeps the v18 wording. The `<tree>` to `<list>` rewrite by the
  XML fixer is separate and unchanged here.
* **D6.** On 2 of 249 official modules (`hr_skills_slides`, `hr_skills_survey`) the legacy XML fixer produces malformed XML.
  The L1 validator rejects the edit (fail-safe), but the module's other edits are withheld too. Same with and without the
  experimental flag.
* Fixed in this slice: the legacy XML fixer rewrote `<tree>` to `<list>`, `view_mode` and chatter blocks for targets
  below 18, which breaks views on 17.

## VR-3 / VR-2: article-derived detection rows (Medium article, verified 2026-11-11)

Article: "Odoo Migration Decoded 16→17→18→19 … (Part 1)" by Osama (@eng.osama1998). **Limitation: article not retrievable
(HTTP 403) on the one permitted WebFetch; an ordinary WebSearch by title did not return it.** No bypass, mirror or archive was
used. Every row below is therefore checked against official sources only, not against the article text. Status key:
verified-official (cited Odoo or Python source), contradicted (official evidence differs; gate or severity changed or lowered),
unverified (no official evidence found; the gate is marked "gate unverified" in the code).

| Rule | Gate now (from / target) | Evidence status | Note |
|---|---|---|---|
| name_get | from < 17, WARNING | verified-official | 17.0 `models.py` warns "Since 17.0, deprecated method, read display_name instead"; 17.0 ORM changelog. Replacement is `display_name`, not `_compute_display_name` |
| read_group | target 19, WARNING (was from < 17) | contradicted for 17; verified-official for 19 | 17.0 and 18.0 `read_group()` have no deprecation note. 19.0 ORM changelog, "Odoo Online 18.2" entry: deprecated for backend use, use `_read_group`. Mapping 18.2 to 19.0 is inferred |
| invalidate_cache / flush | from < 17, WARNING (kept) | verified-official | 16.0 `models.py` defines both with DeprecationWarning; 17.0 `models.py` defines neither. See FC-1 |
| HTML body (`body=` string with `<`) | from < 17, WARNING | verified-official | 16.0 `mail_thread.py` passes body through; 17.0 escapes a plain str body (`escape(body)`) and keeps `Markup` |
| `from odoo.fields import Command` | any, INFO (was from < 17, CRITICAL) | contradicted | 17.0 `odoo/__init__.py` imports Command from `odoo.fields`; the path works |
| post_init_hook(cr, registry) | from < 17, CRITICAL | verified-official | 16.0 `loading.py` calls `(cr, registry)`; 17.0 calls `(env)` |
| _render_qweb_pdf | from < 17, INFO (was WARNING) | contradicted | 17.0 `ir_actions_report.py` defines it with no deprecation note |
| distutils | any, WARNING | verified-official (Python, not Odoo) | Python 3.12 what's new: removed (PEP 632) |
| utcnow | any, INFO | verified-official (Python, not Odoo) | Python 3.12 what's new: `utcnow()` deprecated |
| @http.route type='json' | target 18 and target 19, WARNING (was 19 only) | verified-official | 19.0 branch `upgrade_code/18.1-02-route-jsonrpc.py` rewrites `json` to `jsonrpc`; 18.0 HTTP docs list only `json`/`http` |
| t-raw | any, WARNING (was from < 17, CRITICAL) | verified-official (deprecation); gate contradicted | 17.0, 18.0, 19.0 QWeb docs: "Deprecated since version 15.0", still supported |
| t-esc to t-out | target 18, INFO (was WARNING) | contradicted | 17.0, 18.0, 19.0 QWeb docs: alias of t-out, "Not yet formally deprecated" |
| kanban-box to card | target 18, WARNING (kept) | verified-official | 18.0 `kanban_arch_parser.js` says `"kanban-box" is deprecated` in favour of a `card` template. See FC-1 |
| inline `<script>` in QWeb | target 18, WARNING (kept) | unverified (gate unverified) | Article only |
| createElement('script') | target 18, WARNING (kept) | unverified (gate unverified) | Article only; CSP claim not verified |
| SCSS @import | any, INFO (was WARNING) | verified-official for Dart Sass; contradicted for Odoo 17 | Dart Sass deprecated `@import` in 1.80.0 (removal 3.0.0). Odoo 17.0 compiles SCSS with libsass (`assetsbundle.py`) |
| SCSS division `/` | any, INFO (was WARNING) | verified-official for Dart Sass; contradicted for Odoo 17 | Dart Sass `math.div` since 1.33.0; no removal version on the page. Same libsass point |
| manifest `license` missing | any, INFO (was WARNING, from < 17) | contradicted | 17.0 manifest docs: `license` defaults to LGPL-3, so it is optional |
| `<tree>` to `<list>` | target 18 and 19 (unchanged) | verified-official | 18.0 branch `upgrade_code/17.5-01-tree-to-list.py` |

Verification of gates: the 16-to-17, 17-to-18, 18-to-19, 16-to-19 and 17-to-19 pairs are covered in
`tests/unit/test_legacy_article_detections.py` (20 tests OK; see FC-1 below for the two rows changed in this step).

Golden fixture: `tests/golden_fixtures/17.0/kbi_demo/expected/18.0/report.json` was regenerated (only this file). The diff from
the previous expected file is limited to the intended finding changes: the t-esc finding (WARNING to INFO, new text), the
kanban-box message ("(unverified)"), and the values derived from them (finding ids, `status_inputs_digest`, which hashes the
open critical/warning/review counts, and the warning and info counts). Other working-tree changes to this file were already present before this step and are unaffected.

FC-1 (2026-11-11): the kanban-box message and suggestion changed again, so the same file was regenerated once more with a
one-off script that calls the harness `run_case` for kbi_demo 17.0 to 18.0 (no other golden file touched). The golden test
passes. The kanban finding is now the verified wording. The rule's own suggestion is "Rename the kanban-box template to
t-name="card"". The HEAD file already has the KB-rule finding with the same deprecation wording.

### FC-1 (kanban-box, invalidate_cache/flush, inline script, KB rule 17-18.xml.kanban-box-deprecated)

Official sources only. Each `raw.githubusercontent.com` URL is a branch head fetched through WebFetch (summaries, not byte
reads, and long files were paged). The Medium article was not used.

| Item | Evidence (sources tried) | Status | Action taken |
|---|---|---|---|
| (a) `invalidate_cache()` / `flush()` | `odoo/odoo` 16.0, 17.0, 18.0 `odoo/models.py` (raw URLs, pages 0-100k, 100-200k, 200-300k). 16.0 defines `invalidate_cache` and `flush` with `DeprecationWarning` ("use invalidate_model(), invalidate_recordset() or env.invalidate_all()" and "use flush_model(), flush_recordset() or env.flush_all()"). 17.0 defines neither (only `invalidate_model`, `flush_model`, `*_recordset`). The ORM changelog (`/documentation/17.0/developer/reference/backend/orm/changelog.html`, `/18.0/...`) names none of them; the 15.4 entry introduced the new API. Not read: the last 23k characters of 17.0 and the last 10k of 18.0 | verified-official (deprecated in 16.0, absent in 17.0) | Gate kept at from < 17. Messages now name the 16.0 deprecation and the replacement. Tests assert the 16-to-17 and 16-to-19 findings and the absence for 17-to-18 and 17-to-19 |
| (b) `kanban-box` template | `odoo/odoo` 18.0 `addons/web/static/src/views/kanban/kanban_arch_parser.js`: comment `"kanban-box" is deprecated`, runtime `console.warn`, replacement is a `card` template. 17.0 same file: only a `NOTE ON 't-name="kanban-box"'` comment. 19.0 same file: only the `card` constant, no `kanban-box` or deprecation wording. `kanban-card` appears nowhere; the new name is `card`. The 18.0 upgrade_code listing (`/tree/18.0/odoo/upgrade_code`) has no kanban script | verified-official (deprecated in 18.0) | Gate kept at the 18 target. Message reads "deprecated in Odoo 18.0 in favour of a 'card' template". Suggestion changed to rename to `t-name="card"`. Test assertions updated. The 19.0 target has no legacy row; it is covered by KB rule 18-19.xml.kanban-box-removed (not edited) |
| (c) inline `<script>` in QWeb; `document.createElement('script')` and CSP | WebSearch (`odoo.com` and `github.com` domains) returned the 18.0 Security and QWeb docs, and odoo/odoo issue #22404 (CSP without `unsafe-inline`, about older versions). No official 18.0 or 19.0 change found | unverified | Rows unchanged. "gate unverified" comments and wording kept in `legacy_rules.py` and the test file |
| (d) KB rule `17-18.xml.kanban-box-deprecated` (EV-119) | The rule's claim (17.0 has the name, 18.0 deprecates it for `card`, 19.0 does not read it) matches (b). EV-119's cited revisions (`9ef8d62`, `75d6abe`) were not fetched; the branch heads above were. Line numbers in the WebFetch summaries are approximate | verified-official, consistent with EV-119 | No KB JSON, digest or release data edited. Recommended action for the KB owner: keep the rule. Optionally re-check EV-119 line numbers against the pinned revisions |

FC-1 tests: `tests.unit.test_legacy_article_detections` 20 OK, `tests.unit.test_legacy_xml_version_gating`,
`tests.unit.test_legacy_xml_wellformed`, `tests.integration.test_golden_migrations`, `tests.regression.test_known_defects_d2_d4`,
`tests.unit.knowledge.test_legacy_precedence`, `tests.contract.test_plugin_exception`: all OK (60 tests across the seven modules).

Note: the Known defects D3 entry is fixed (FC-3 above). Lines in the Observations block and the Outcome paragraph of the
earlier report still call the D3 bullet stale. These were left unchanged per the FC-3 scope. That block also describes
`tests/unit/reporting/renderer_hashes.json` as present: it was untracked, unreferenced by any code, tool or test, and
stale, and was removed in FC-4 (owner-approved).
