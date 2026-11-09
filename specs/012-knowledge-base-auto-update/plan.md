# Feature 012 — Plan (F012-0 architecture checkpoint)

Status: PROPOSED. No implementation has started. Baseline: main @ 1c7f33c, clean except an untracked empty `sources.json`
(default registry written by an earlier ad-hoc run; not part of the feature).

## 1. Reuse map (Feature 011, not rewritten)

| Need | Existing owner |
|---|---|
| Source records, status, allow-list, origin normalisation | knowledge/acquisition/sources.py, official_sources/allow_list.json |
| Local git snapshot + origin identity check | acquisition/adapters/git_local.py (read-only plumbing, hardened env) |
| HTTP blob retrieval (single file, sha256, `allow_network`) | acquisition/fetch.py (only network module) |
| 17-step build, resume, fingerprints, dry run | knowledge/pipeline.py (`BuildPlan`, `run_build`) |
| Rules/evidence/gates 1-5, grandfathering | candidates/*, release/safety.py, loader.py |
| Release store, lock, active pointer, audit chain | release/store.py, audit.py, resolver.py, package/importer.py |
| Coverage/gates | coverage/*, release/coverage_check.py |
| Migration-time KB load (offline) | release/resolver.py, cli/migrate.py |
| Fix primitives | transformers/python.py (remove_decorator, remove/rename_keyword, replace_call_name, replace_attribute), xml.py |
| CLI registration | cli/knowledge.py + cli/kap_*.py |

## 2. Gaps found (not in Feature 011)

G1. No remote git acquisition. `fetch.py` is HTTP blob only; `git_local` needs an existing clone. Check needs `git ls-remote`
    (no object download); update needs a shallow fetch of the resolved SHA into a managed cache clone, then the existing
    `GitLocalAdapter` runs on that clone. New subprocess use => new pinned allow-list entry in
    tests/unit/validation/test_no_customer_code_execution.py with written reason. Hardened env, no hooks, no submodules,
    no credential helpers, `--no-recurse-submodules`, protocol https only, fetch by SHA after ls-remote.
G2. Generated rules can never carry a fixer: templates.py:151 forbids `fixer_ref` by design; skeletons are DETECT_ONLY.
G3. `promote` requires an externally supplied, non-self approval reference that is "recorded, never generated here"
    (authoring/promote.py). Automatic FIX_ENABLED therefore conflicts with two Feature 011 contracts (REQ-KAP-018 and the
    owner rule). Needs a dedicated, owner-approved certification path (section 4). It must not reuse `promote`.
G4. Only five Python primitives exist as transformers. Realistic auto-fix scope: deterministic rename/replace/remove-keyword
    classes whose ledger change maps 1:1 to a primitive. Expect few or zero new verified fixes on a real corpus; the report
    must say so rather than imply coverage.
G5. Catalog and discovery do not exist; `pyproject` package-data must include the catalog json.
G6. Release activation only exists via `package import --activate` or store primitives; pipeline step 16 is SKIPPED.
G7. Network policy: `--allow-network` is per-fetch today.

## 3. Update Manager (new, stdlib-only, core package `odooflux/knowledge/update/`)

catalog.py (load+validate packaged catalog, digest) · discovery.py (ls-remote heads, `^\d+\.0$` only, never hardcoded;
statuses of spec section 6) · fingerprint.py (commit SHA, snapshot digest, catalog digest, extractor version, schema
version, build config, parent release id) · planner.py (catalog + discovery + active release -> `BuildPlan`) ·
remote_git.py (G1) · certify.py (section 4) · activation.py (section 5) · report.py + history.py (JSON schema
`update_report` 1.0.0; `kb-home/updates/history.jsonl`, also audit chain) · cli/kap_update.py (check/update/status/history).
Import-graph guard unchanged: update/ imports only core packages; adapters/toolkits attached in builtins.py as today.

Flow of `update`: load catalog -> discover (or `--offline`: local verified state only) -> fingerprint compare ->
no relevant change = NO-OP, no release -> plan -> acquire (G1) -> `run_build` steps 1-15,17 -> certify (section 4) ->
activation policy (section 5) -> store install + atomic pointer swap under existing `.lock` -> report + history.
Interrupted build resumes through pipeline resume. `--dry-run` = discovery from local state + plan only, zero network.

## 4. Automated certification (SECURITY DESIGN — needs owner approval before Haiku implements)

Proposal: a versioned `fix-certification/1` record, separate from human `promote`:
- Applies only to rules whose ledger change maps to a registered *fix template* (table: change class -> existing
  transformer primitive + parameter derivation). Table is code, versioned, digest-pinned; AI output never qualifies.
- Certifier generates fixtures deterministically from the evidence (before/after snippets), then requires: positive,
  negative, idempotence, conflict, and regression-suite pass; verified evidence (gate 1); gates 2-5.
- Record binds: rule digest, transformer id+version, evidence ids+digests, fixture digests, test outcomes, policy version.
- The approval reference is `auto-cert:<policy_version>:<record_digest>` — labelled automated, never presented as human
  approval, not forged. Release load re-verifies the record digest against the row; mismatch => capped to DETECT_ONLY with
  a finding (reuses the KAP_FIX_CAPPED path).
- `knowledge rule certify` becomes the only writer of the record; `promote` and gate P10 remain unchanged except P10
  accepting a valid certification record.
- Trust-model delta, stated plainly: FIX_ENABLED may rest on a machine-checked record instead of a human approval for
  template-class fixes. Human governance stays required for production certification (dimension 4) and any rule outside the table.
Alternative if owner declines: updates activate detection only; fixes stay DETECT_ONLY and are listed as "eligible, awaiting approval".

## 5. Activation policy and OD-K13

Activate only if: provenance verified, integrity + release consistency pass, blocking gates pass, no unauthorised
FIX_ENABLED, and **no capability regression** (no active FIX_ENABLED or detection rule lost without an explicit ledger
REMOVED reason). The release is the unit of activation: PARTIAL activates only when it meets this rule; otherwise the
previous release stays and the report states why. Pointer swap atomic (existing write_active); failure => ROLLED_BACK
state recorded, previous release untouched.
OD-K13 recommendation (owner decision B): grandfather carried-forward built-in rows by byte-identity with the shipped row
at import (same predicate `safety.is_shipped_builtin_rule` the loader uses); anything else still refused. Update does not
use `--downgrade-unverified`; it reports a capability diff against the previous release and fails closed if FIX_ENABLED
shrinks. Changes release/package gate P10 => owner sign-off.

## 6. Network policy (decision)
Proposal: invoking `knowledge check`/`update` online is the explicit authorization (mapped internally to
`allow_network=True`); `--offline` or `ODOOFLUX_OFFLINE=1` forces zero network calls; `migrate` never networks (already
true, add a test). `pip install` downloads nothing.

## 7. Task ledger (Haiku executes after approval; disjoint files; max 3 concurrent)

Wave 1: T01 catalog.json + schema + loader + pyproject package-data + tests (update/catalog.py) |
        T02 remote_git.py + guard allow-list entry + tests with a local bare repo as "remote" (no network) |
        T03 fingerprint.py + history.py + report schema + tests.
Wave 2: T04 discovery.py + `check` CLI (injected ls-remote runner) | T05 planner.py (catalog->BuildPlan) |
        T06 fix-template table + certify.py + adversarial tests (after D2 approval).
Wave 3: T07 activation.py + OD-K13 predicate change + tests | T08 orchestrator + `update` CLI (+dry-run/offline/resume) |
        T09 status/history CLI.
Wave 4: T10 integration tests (local bare-repo "upstream", new-version discovery, no-op, failure/rollback, concurrency,
        wrong kb-home) | T11 wheel test outside checkout | T12 docs (spec, quickstart, guide, README, TECHNICAL_USAGE, notes).
Final: full suite once; acceptance matrix AC-01..25 with EXECUTED/SKIPPED/NOT_AUTHORIZED; real-source 16->17 pilot prepared, not run.

## 8. Decisions requested at this checkpoint
D1 network policy (section 6) · D2 automated certification (section 4, or detection-only) · D3 OD-K13 option (section 5) ·
D4 PARTIAL activates only without capability regression (section 5).

---
# Addendum A (Wave 2 design, Sonnet) — editions, Enterprise auth, hardening, certification

## A1. Edition model — SUPERSEDED by Addendum B (one unified KB). Kept for history only.
Facts from Feature 011: Enterprise snapshots are never exported (`enterprise_derived` => provenance verification and package
export refuse); `ENTERPRISE_LOCAL` adapter reads a local entitled directory only.
Decision: **two knowledge lines**, one per edition. The community line is the existing kb-home layout, unchanged. The enterprise
line is a complete kb-home layout under `<kb-home>/enterprise/` (own releases/, active.json, audit chain, updates/history),
local-only and never packaged/exported. Consequences: a Community-only update cannot touch Enterprise capabilities (separate
pointer, separate lock); Enterprise stays optional; reports carry `edition`; fingerprints use edition-qualified source ids
`<edition>:<version>`; rule rows keep their shape (edition is the line they live in; certification records carry `edition`).
Catalog v2: every entry has `edition` (community|enterprise), `requires_credentials` (false|true), `kind`
(GIT_COMMUNITY|ENTERPRISE_LOCAL), repository `https://github.com/odoo/odoo.git` or `https://github.com/odoo/enterprise.git`
(both already allow-listed), expected_origin, branch == version. Community and enterprise entries for the same version are
paired by version. A transition candidate needs the same edition on both ends.
OPEN (Wave 3, flagged not blocking): (a) how the pipeline reads an Enterprise managed-cache clone (the cache has no working
tree; needs a git-backed Enterprise adapter or a checkout step, still reading nothing outside the cache); (b) how `migrate`
consumes the Enterprise line (overlay merge in the loader) — touches migrate and needs owner confirmation before Wave 5.

## A2. Enterprise authentication design (reviewed)
- Token source: `ODOOFLUX_ENTERPRISE_TOKEN` env, or a file named by `ODOOFLUX_ENTERPRISE_TOKEN_FILE` (regular file, not symlink,
  owner-only perms, size-bounded). No arbitrary credential-helper command: a helper is a configured command to execute,
  contradicting the no-arbitrary-execution rule. Decision D5 (record): "approved credential-helper mechanism" = these two
  inputs plus a fixed OdooFlux-owned `GIT_ASKPASS` stub; user-configured git helpers are not honoured.
- Delivery: child env `GIT_ASKPASS=<stub path>` (a script written by OdooFlux into a private 0700 temp dir that reads the token
  from a private env var of the child and answers the username/password prompts; the token never appears in the script, argv,
  URL, git config, cache repo config or temp files). `GIT_TERMINAL_PROMPT=0`, `-c credential.helper=`,
  `-c http.followRedirects=false` (a redirect must not carry credentials elsewhere), `-c http.sslVerify=true`.
- Scope: credentials are attached ONLY when the validated identity is the allow-listed Enterprise origin; Community calls get an
  env that provably lacks the token (test asserts the child env of every Community call).
- Failure taxonomy (stderr classified, then discarded after scrub): AUTH_REQUIRED (no token, enterprise repo), AUTH_FAILED
  (rejected token/403/404 on private repo with token), UNAVAILABLE (DNS/connect/timeout/5xx). Distinct statuses, never merged.
- Scrubbing: any message/report/history/audit text passes `utils.redaction.scrub(..., secrets=(token,))`; tests grep
  captured logs, exceptions and history for the token.
- Corporate CA: `ODOOFLUX_CA_BUNDLE` (existing regular file) is mapped to child env `GIT_SSL_CAINFO` for that call only. No
  global git setting is written or read. `sslVerify` is never disabled.
- Offline: network gate precedes credential handling; offline never reads the token.

## A3. Wave 1 hardening design
Per-identity `flock` on `<cache>/<id16>.lock` (non-blocking with bounded wait); fetch into `<cache>/<id16>/tmp-<random>` created
under the lock owner's process, verified, then atomically `os.replace`d to `<cache>/<id16>/<sha>`; a failing fetch removes only
its own temp dir; stale `tmp-*` older than a bound are removed under the lock; the shared final dir is never deleted by a
failure. In-flight guard: a watcher polls the temp dir size and terminates the git process group beyond `max_bytes`
(bounded overshoot of one poll interval plus one pack write; documented, NOT a strict guarantee), plus
`http.lowSpeedLimit/lowSpeedTime` and the existing wall-clock timeout. Interrupted fetch (kill mid-run) leaves only `tmp-*`.

## A4. Certification (`fix-certification/1`) — library only in Wave 2
Not wired into gates/loader/import until Wave 3 (no FIX_ENABLED is created in Wave 2).
- `fix_templates.py`: versioned table template_id -> {ledger change class, transformer primitive (existing five),
  param derivation from the rule row, fixture generator}. Initial templates only where a primitive maps 1:1.
- `certification.py`: `issue(rule_row, evidence_rows, ...) -> record`; `verify(rule_row, evidence_rows, record) -> findings`.
  The verifier RECOMPUTES everything: regenerates fixtures from the rule params, runs the real engine path (the same
  fixer + `apply_edits` the fix engine uses), checks positive/negative/idempotence/conflict, and compares digests. The record
  stores digests only (rule canonical digest, template id+version, transformer identity = function qualified name + digest of
  its source, evidence ids+digests, fixture digests, output digests, policy version, edition); no PASS flag is read or trusted.
  Reference: `auto-cert:<policy>:<record digest>`. Any mismatch => findings, rule stays DETECT_ONLY with a reported reason.

---
# Addendum B (owner correction, Sonnet revision) — ONE unified Knowledge Base

Supersedes A1 and D5. No `<kb-home>/enterprise/`, no second store, pointer, loader or lock. Community and Enterprise are
two official *source families* feeding one Knowledge Release (one active pointer, one release id/digest, one rule registry,
one migrate pipeline). `edition` in the catalog is a **source identity label**, not a KB partition.

## B1. What stays from Waves 1-2
Catalog v2 (entries = sources; both families per version), `remote_git` + `credentials` (A2/A3 unchanged), fingerprints,
history. Fingerprint source ids are `<family>:<version>`. Certification (A4) changes: `edition` is replaced by
`evidence_sources` [{source_id, confidentiality}] bound per record; one policy for all rules (message sent to the T06 agent).

## B2. Feature 011 contract deltas required (trust-model changes — need your approval before implementation)
Today an `enterprise_derived` source makes `provenance.write_provenance`/`verify_provenance` fail
(ENTERPRISE_DERIVED_REFUSED) and `export_package` refuses it by default. A unified release therefore needs:
1. **Internal releases.** Manifest gains `confidentiality: "public"|"internal"` (covered by the release digest; *derived*:
   internal iff any source is enterprise-derived; never self-declared). Provenance accepts an enterprise source only as a
   `digest_only` entry (source_id, verified Enterprise origin, pinned revision, snapshot id + digest; NO snapshot manifest,
   file list or content shipped in the release). Public releases keep today's refusal unchanged.
2. **Export fails closed for internal releases.** `export_package` refuses `internal` releases always; the existing
   `include_enterprise_derived` escape hatch is removed from public CLI paths (kept only as an internal parameter used by
   no command). Package import never receives an internal release. Canary scan extended with Enterprise canaries.
3. **Public projection = a separate Community-only build, not a filtered copy.** `knowledge package export --public` builds
   (from retained Community snapshots) a release with zero Enterprise inputs, validates it fully, and exports that. Filtering
   a unified release is rejected as a design (disclosure risk through derived text, ids, coverage numbers, paths).
4. **Gate 1 for Enterprise-derived evidence**: identity via the managed-cache clone's verified origin against the allow-list
   (Enterprise prefix is already allow-listed); same fail-closed rules. Evidence rows keep locator + content digest;
   proprietary `match` excerpts live only in the internal release and are never rendered by reports/projections (D6).
5. **Confidentiality is derived, never declared**: a rule/evidence/inventory/ledger record is Enterprise-derived iff its
   `source_id` is an enterprise-derived source in the verified provenance index. Reports and exports consult that index.
No other gate (2-5, P01-P11, load-time cap, certification) is weakened.

## B3. Unified inventory and dependency graph
New artifact `inventory/<version>.json` in the release (built from acquired snapshots by static `ast.literal_eval` of
`__manifest__.py`, no execution): modules {name -> source_id, depends, manifest digest}. Enterprise entries are
Enterprise-derived records (internal only). `dependencies/` resolution at migrate time consults the inventory of the target
and source versions: Community, Enterprise, cross-repository and transitive dependencies of custom modules; unresolved
= explicit finding (never silently Community-only). **Honest scope**: inventory v1 = modules + depends + provenance.
Static model/field/method/XML-ID catalogs are not in scope of Feature 012 v1; existing KAP ledger/evidence cover API-change
facts only. Recorded as a limitation, not claimed.

## B4. Update semantics
- No credentials: Community sources acquired; Enterprise skipped with status ENTERPRISE_SKIPPED_NO_CREDENTIALS; the new
  release **carries forward** parent Enterprise components byte-identically (sources entries, evidence, rules, inventory,
  certification records, tagged `carried_from: <parent release id + digest>`), freshness reported as STALE_UNVERIFIED,
  never as fresh or removed. Carry-forward is checked: bytes equal the parent's, records still verify.
- Compatibility gate: every carried Enterprise module's `depends` must still resolve in the new unified inventory, and every
  carried certification record must re-verify. Failure => BLOCKED_ENTERPRISE_COMPAT, previous release stays active.
  Success is reported as "compatibility of carried Enterprise knowledge with the new Community revision: dependency-checked,
  not source-verified" — never "compatible" in general.
- Credentials later: a normal update with the token acquires Enterprise sources and *enriches* the same lineage (parent =
  previous release). Credentials removed: same as "no credentials". AUTH_FAILED (rejected token) is distinct from
  UNAVAILABLE and from SKIPPED; a failed Enterprise acquisition never removes anything and never blocks Community unless
  the run was explicitly `--require-enterprise`.
- Pipeline support to verify first (Wave 3, T08a): `BuildPlan.pairs` is one (from,to) per step label. Unified builds need
  up to two source pairs per transition (community + enterprise). Task T08a inspects `_extract/_evidence/_candidates` and
  change-id derivation and extends minimally (source-scoped change ids) or reports BLOCKED. Also: how the pipeline reads the
  Enterprise managed-cache clone (no working tree): git-backed adapter over the cache using the existing plumbing.
- Activation stays release-level, atomic, existing `write_active` under `.lock` (D4 unchanged). Capability-regression
  comparison (D4) includes carried Enterprise rules: losing or downgrading one blocks activation.

## B5. Migration (offline, one pipeline)
`migrate --from 16 --to 17` unchanged. Loader reads the one active release (internal or public). Dependency resolution uses
the inventory when present (B3); no edition flag. Reports render Enterprise-derived evidence by id + source id + revision
only. Report/SARIF/HTML renderers get a confidentiality-aware evidence renderer (Wave 5, touches report outputs; golden
files must stay byte-identical for public releases).

## B6. Revised task ledger (replaces section 7 beyond Wave 2a)
Done/in review: T01 catalog v2, T02 remote_git+credentials, T03 fingerprint+history, T06a templates+certification library.
Wave 2b: T04 discovery + `knowledge check` (per-source statuses incl. ENTERPRISE_SKIPPED_NO_CREDENTIALS, AUTH_FAILED,
  UNAVAILABLE; ls-remote only) | T05 planner (catalog + discovery + active release -> BuildPlan inputs, unified pairs, carry-forward
  intent, fingerprint with family-qualified ids) | T06b `inventory.py` (static manifest inventory + dependency resolver, tests).
Wave 3 (needs B2 approval first): T07a provenance digest_only + manifest confidentiality + export fail-closed + canaries |
  T07b gate 1 Enterprise identity + load/import enforcement of certification | T08a pipeline multi-pair/Enterprise cache adapter
  | T08b carry-forward + compatibility gate | T08c orchestrator + `update` CLI.
Wave 4: activation policy + atomic activation + rollback; public projection export; status/history CLI; cert wiring
  (issuance in pipeline, load-time cap re-verify).
Wave 5: migrate dependency resolution via inventory, confidentiality-aware renderers, integration tests (the 13 listed in
  the owner brief), wheel test, docs, acceptance matrix.
FIX_ENABLED stays untouched until issuance, load-time and import-time enforcement are all wired and tested (Wave 4).

## B7. Decisions needed now
D6 (B2 deltas 1-5, esp. internal-release digest_only provenance and projection-by-rebuild rather than filtering) and D7
(`--require-enterprise` opt-in flag; default is Community-only success with Enterprise skipped/carried).
Haiku continues only after you approve B2/B6.

---
# Addendum C (Wave 3b design, Sonnet) — carry-forward, pairs, activation

Findings (pipeline.py investigation): a new release starts from the shipped base tree; the parent release is used only for
delta flags and the destructive-removal gate, so parent sources/rules/evidence NOT regenerated by the run are silently
dropped (surfacing only as DESTRUCTIVE_NEEDS_SUPERSEDE). A duplicate step label collides on ledger/accounting/steps_covered
files. cmd_build only registers GIT_COMMUNITY adapters.

## C1. Carry-forward = rebuild from retained verified snapshots (no parent overlay)
Rather than splicing parent records into a new tree (record-level merge across shared evidence/rule files, high risk), a
carried source is re-extracted from its *retained verified snapshot* with the unchanged pipeline:
- the update uses one stable work directory (`<kb-home>/staging/update/`, mode 0700) with a persistent content-addressed
  blob store and per-source snapshot manifests, reused across runs (the existing resume/fingerprint machinery applies);
- a CARRY_FORWARD source is registered with a `RetainedSnapshotAdapter` that returns the stored snapshot only if its digest
  equals the digest recorded by the installed release (InstalledState.snapshot_digests) and the blobs re-verify;
- if the retained snapshot is missing/mismatched the source FAILS, the removed-rule gate stops the build
  (DESTRUCTIVE_NEEDS_SUPERSEDE) and the previous release stays active — fail closed, never silent loss;
- same snapshot + same extractor version => byte-identical rule/evidence rows; the capability comparison (C3) proves it.
  A changed extractor yields *reported* modified rules, never silent ones.
Confidentiality note: the retained Enterprise blobs live in the user's own kb-home staging dir and are never part of any
release/package; document it, create it 0700.

## C2. Pairs: pair key
`BuildPlan.pairs` entries may carry `key` (default = `step`). Files that are keyed by step today (ledgers/accounting/
steps_covered) use the key; the `step` NN-NN keeps flowing to Ledger.create, rule ids, evidence applicability. Community and
Enterprise pairs for one transition use keys `<step>` and `<step>.enterprise`... (exact scheme chosen by the implementer,
must be deterministic and unique). Module inventory `inventory/<version>.json` (inventory.py) is emitted into the release
from the VERIFIED snapshots of that run (carried ones included).

## C3. Activation = capability comparison + trust re-check
Capability of a rule = (id, maturity, detector_ref+params, fixer_ref+params, applicability/scope fields). Against the active
release: LOST (id missing), DOWNGRADED (maturity rank lower), CHANGED (any executable field differs). Activation allowed only if
integrity/gates passed (release is INSTALLED), completeness != FAILED, no LOST/DOWNGRADED id unless listed in the recorded
supersede set, and every FIX_ENABLED rule of the new release is trusted (shipped built-in by byte identity, or — in Wave 3c —
a valid fix-certification). CHANGED FIX_ENABLED rows must satisfy the same trust test. Carried Enterprise modules must pass
`inventory.carry_forward_compat`. Activation itself reuses `cli/kap_release.activate` (atomic pointer swap, rollback on
fault); failure leaves the previous release active and is recorded as ROLLED_BACK/FAILED.

## C4. Task split
3b: B1 pipeline (pair key, retained adapter, GIT_ENTERPRISE registration, module inventory emission) | B2 acquire.py
(plan -> fetch_commit -> specs/source_meta, credential/offline/auth statuses) | B3 capability.py + activation.py.
3c: orchestrator + CLI update/status/history (needs 3b) | certification wiring (ops/build/import/load) + D3 import grandfathering.
3d: unified migrate dependency resolution + confidentiality-aware rendering; integration tests; wheel; docs.

---
# Addendum D (D8 design review, Sonnet) — fixer-bearing candidates: NOT implemented as requested

Owner answer (Wave 3c): generate fixer-bearing candidates for replacement/removal classes. Design review finding: **as stated it
cannot be done safely under the existing Feature 011 contracts, so it is BLOCKED; nothing was weakened.**
1. `extract/rename.py`, `ledger/dispositions.py`: RENAMED_CANDIDATE and REPLACEMENT_CANDIDATE are `confirmed:false` always; the
   ONLY way to confirm one is a MANUAL (human) `confirm` disposition (CONFIRMABLE). Auto-certifying a candidate replacement would
   let an unconfirmed heuristic pair become an auto-fix, contradicting the ledger contract and the owner rule that official
   evidence alone never enables a fix. Certification proves the transformation implements `old -> new`; it cannot prove `new`
   is the correct replacement.
2. The earlier T06a class mapping (REPLACEMENT_CANDIDATE -> replace_call_name/replace_attribute) is therefore WRONG and must be
   changed before any issuance is possible: eligible classes become derived classes that carry their own proof —
   `REPLACEMENT_CONFIRMED` (ledger entry confirmed by a recorded MANUAL disposition) and `DELEGATING_ALIAS` (static proof: the
   old method still exists in the new source and its body is a single call that forwards its arguments to the replacement);
   remove_decorator: `IDENTITY_DECORATOR_REMOVED` (the removed decorator was an identity function in the old source);
   remove_keyword: no safe class today (dropping a keyword argument changes behaviour unless proven a no-op) => disabled.
3. Safe paths, none requiring a trust relaxation: (S1) generate a fixer-bearing candidate only from a *confirmed* replacement
   (one-time human knowledge decision persisted in the ledger, not a routine update approval), then auto-certify the
   mechanical transformation; (S2) extractor support for DELEGATING_ALIAS proof; (S3) extractor support for
   IDENTITY_DECORATOR_REMOVED proof. S2/S3 need new extractor logic (body analysis of python_orm/api definitions) and tests.
4. Until the owner picks S1/S2/S3 (or all): generated rules stay DETECT_ONLY; the verification wiring (build/import/load) and
   `rule certify` for maintainer-authored rules proceed; no FIX_ENABLED is created automatically.

---
# Addendum E (orchestrator design) — decisions recorded
- `--dry-run` reads remote *metadata* exactly like `check` (read-only ls-remote, no object download) unless `--offline` is also
  given (then zero network); it never downloads sources, builds, installs, activates, or appends history. This refines section 3
  ("zero network"): a useful dry run needs the remote SHAs, and ls-remote is the same read-only operation D1 already authorises
  for `check`.
- Update-level lock `<kb-home>/updates/.update.lock` (flock, bounded wait -> BLOCKED CONCURRENT_UPDATE) serialises runs; the
  pipeline's own kb-home lock and the per-identity fetch locks still apply.
- NOOP requires BOTH the planner's NOOP and `needs_build(...)` == False against the persisted `details["build_inputs"]` of the last
  ACTIVE/NOOP history record; if no previous build inputs exist the run builds (never a guessed no-op).
- Build uses one stable work label `update`; carried sources go through RetainedSnapshotAdapter with the installed snapshot
  digests; the semantic supersede policy is always set; its approvals are also passed to `activation.evaluate(supersede=...)`
  so rotated ids are not reported as lost capabilities (anything without an equivalent replacement still blocks).
- Enterprise carry compatibility: `inventory.carry_forward_compat(old, new)` per version over the active and new releases'
  inventory/*.json; findings => BLOCKED ENTERPRISE_COMPAT.
- Result type: `model.UpdateResult` (schema `odooflux.knowledge-update/1`); production certification is always NOT_GRANTED.

---

# Addendum F (automatic FIX_ENABLED pipeline design, Sonnet) — supersedes Addendum D items 2-4 and the A4 template classes
Verified against the code: (a) `fix_templates.eligible` accepts only origin BUILTIN/MANUAL, so a GENERATED row can never qualify today;
(b) certification exercises `transformers.python` primitives, but the loader runs `fixer_ref` functions from `BINDABLE_MODULES`
(`rules/python/generic.py` has rename/remove keyword, remove_decorator, rewrite_attribute_access; none equals the certified primitives and they
resolve names differently) so the certified code is not the executed code; (c) the primitives match LITERAL dotted text (`api.multi`,
`self.m`), unsound for custom code (any `api`, any receiver); (d) `safety._verify_record` passes `record.get("change_class")`, a self-declared class;
(e) `accept()` refuses fixer/FIX_ENABLED and step 9 `_fix_trust_findings` runs BEFORE step 10 writes `release/provenance` (gate 1 would fail closed).
All five are fixed below. Real run mechanism: `bind_rule` gives each of detector/fixer the `params` keys it accepts (`_split_params`), unknown keys
are errors, `fixer_ref` must be a function in a `BINDABLE_MODULES` module with signature `(document, ctx, *, ...)`; `KnowledgeRule.fix` ->
`fixing_transform` -> `apply_edits`. So a rule runs with NO special fixer: `fixer_ref=odooflux.rules.python.certified:<fn>`, `params` = its keywords.
## F1. Soundness criteria (strict; any unmet condition => stay DETECT_ONLY with a coded reason, never a guess)
Scope (all classes): only top-level module symbols (function, decorator function) of ONE python module, qualified by `module` = dotted name derived
from the snapshot path by one pure function (`odoo/x/y.py` -> `odoo.x.y`, `__init__.py` -> package, `odoo/addons/<a>/...` -> `odoo.addons.<a>...`).
Method, field, attribute, class, XML/JS subjects, cross-module moves and keyword changes are OUT of scope (receiver type is not statically
provable; rename of `self.m` would also bypass custom overrides). Common preconditions C1-C6:
 C1 pair sources VERIFIED, official (gate 1 recomputes), pinned; ledger entry has `confirmed:false` untouched and class as stated; entry is 1-1
    (not UNKNOWN/ambiguous); both blobs rehash to the location `sha256`; parse OK on both sides (`ast`, no exec/compile); file in scope, not TOO_LARGE.
 C2 `module` identical on both sides; no top-level `__getattr__`, no `from x import *` in either version of that module.
 C3 names are plain identifiers, not keywords, `old != new`, <=120 chars (`fix_templates` validators reused).
 C4 each def is top-level, sync, has NO decorators (S1/S2) and no nested definition named `old`/`new` anywhere in the module.
 C5 the symbol bindings asserted below are checked against ALL top-level bindings (def/class/assign/import/for/with/global) of that module.
 C6 evidence row exists, official, has `content_sha256` for the proof file, rule_ids = the rule, applicability recorded (gate 2).
S1 REPLACEMENT_BODY_IDENTICAL (derived class name `REPLACEMENT_CONFIRMED`, machine variant; ledger class must be REPLACEMENT_CANDIDATE with
 `detail.source` in docs|migration, i.e. an official text names old->new; RENAMED_CANDIDATE by similarity score NEVER qualifies): old def exists in
 FROM and not in TO; new def exists in TO and not in FROM; full-def dumps equal after normalising only the def name (args, defaults,
 annotations, body, async-ness); free names of the body (Name loads minus params/locals) must each be a builtin or bound by an import statement
 whose dump is identical in both versions; ANY other module-global reference (including recursion by name) => refuse S1_GLOBAL_REF; the TO module's
 docstring hint of the new def names `old` (re-checked by regex on the new def docstring).
S2 DELEGATING_ALIAS (ledger class BEHAVIOUR_CHANGED or DEPRECATED for `old`; the official TO source is the evidence): `old` and `new` both
 top-level in TO; `old` has `new`'s exact signature (names, order, defaults, kinds); body = optional docstring, optional ONE
 `warnings.warn(<str const>, DeprecationWarning|FutureWarning[, stacklevel=<int const>])`, then exactly `return new(<forward>)` where `<forward>` passes
 every parameter once, same names/order (`p`, `*args`, `k=k`, `**kw`), no other expression, no `await` in a sync def; `new` != `old`; `new` is
 not itself a forward to `old` (cycle) and its own body is not another alias chain longer than 1 (resolve one level only).
S3 IDENTITY_DECORATOR_REMOVED (ledger class REMOVED, kind function): FROM def has exactly one positional param `p`, no defaults/varargs/kwargs/
 decorators, body = optional docstring + `return p` ONLY (no attribute set, no wrapper); TO module binds nothing named `old` (C5 incl. imports,
 `__all__` strings, star imports refused by C2). Applies only to a BARE decorator use (`@name`, `@alias.name`), never `@name(...)`.
Call-site rule (shared by the three fixers): resolve a Name/Attribute chain to a qualified name ONLY through top-level `import`/`from-import` of the
 same file; if the root name is bound twice, assigned, a parameter, a def/class name or a comprehension/loop target anywhere in the file, the whole
 FILE gets zero edits; `from M import old [as a]` is rewritten together with every bare use of `a` (rename of the import name; an alias keeps `a`);
 string literals, comments and docstrings are never touched. Anything unresolved is left as is (detector still reports it).
Disabled with reason (no sound static proof): keyword rename/removal, any method/field/attribute rename, RENAMED_CANDIDATE by score, MOVED,
 BEHAVIOUR_CHANGED without S2 shape, any AI-proposed pair. Extractor facts to carry: per function fact add `attrs.decorators` (exists),
 `module`, `def_digest` (dump with name normalised), `free_names`, `import_digests`, `top_level_bindings_digest`, `is_async`, `forward_shape`,
 `identity_shape`, `docstring_replaces` (list); all computed by `knowledge/extract/proofs.py` from source text, none by AI.
## F2. Machine confirmation `odooflux.machine-confirmation/1`
Separate artifact, NEVER a ledger `confirmed:true`, NEVER actor MANUAL. File `<release>/knowledge/confirmations/<rule_id>.json` (inside the
manifest digest, like `certifications/`). Keys (closed set, extra/missing refused): `schema, policy_version, rule_id, change_id, derived_class
(S1|S2|S3 name), ledger_entry{class, confirmed:false, entry_digest = digest of the entry without history}, subject{domain,kind,subject_key},
module, old, new, witness{facts above, STRUCTURAL ONLY: names, flags, digests; no source text}, witness_digest, sources[{side, source_id,
snapshot_id, revision, path, blob_sha256, line}], evidence[{id,digest}], proof_tool{id:"proofs/1", source_digest = sha256 of proofs.py text},
derived_params, record_digest`. Sole writer: `knowledge/update/autofix.py` during a pipeline build (no CLI writer exists or is added).
Audit: one `Ledger.append_history` entry per confirmation (`actor "MACHINE:machine-confirmation/1"`, action `machine_confirm`, to_value =
record_digest); the entry's disposition becomes RULE_CREATED naming the fix rule (history keeps the earlier HUMAN_REVIEW).
Re-verification, recomputed never trusted: L1 (EVERY boundary: build G-SAFE, import P10, loader cap; needs only the release tree) = schema +
closed keys, `record_digest`, `proof_tool.source_digest == live proofs.py digest`, `derived_params` re-derived from the witness by
`proofs.check_witness` (pure; reruns every class condition on the facts), rule row (`params`, `evidence`) equals derived_params and evidence digests,
`rule_digest` of the rule is bound (confirmation lists `rule_digest`; the rule digest already covers params, refs, evidence), evidence official via
gates 1-2, release ledger entry digest equal when `ledgers/` is shipped (Haiku C must check; else binding is the witness+evidence
`content_sha256`). L2 (build step 9 and update pre-activation, where the store/retained snapshots exist) = reread blobs by `blob_sha256` through
the verified retained snapshot, rehash, re-parse, rerun `proofs.prove`, compare `witness_digest` byte for byte; a missing or tampered blob => demote.
Trust uses the CONFIRMED class (`derived_class`), never `record["change_class"]`: `safety._verify_record` must pass `confirmation.derived_class`.
Why `CONFIRMABLE` (RENAMED/REPLACEMENT_CANDIDATE, MANUAL only, once) is untouched: `dispositions.confirm`, `Ledger.create` (drafts never confirmed),
`merge`, `promote` (still refuses `auto-cert:`) and generator rules (`replacement_suggestion` still needs `confirmed:true`) are unchanged; a candidate
stays unconfirmed in the ledger; the machine path creates a derived-class fact backed by a proof, in its own artifact, labelled machine.
## F3. Data flow (core modules stay stdlib+odooflux; no parsers/transformers import in knowledge/)
1 step 3 `extract` (`driver`, unchanged contract): unchanged; facts gain the F1 fields via `extract/domains/python_orm.py` calling `extract/proofs.py`
  (stdlib `ast`, allowed: python_orm already imports ast; no `compile/exec`; the no-customer-code and extract-boundary guards stay green).
2 step 4 `classify`: no change (ledger classes only; counts). Hints stay REPLACEMENT_CANDIDATE.
3 step 6 `candidates` (pipeline `_candidates`), after `gen.generate`+`accept` for ordinary candidates, new `autofix.plan_pair(ctx, pair, ledger, tree)`:
  for each ledger entry in an eligible class read both blobs from `BlobStore(ctx.path("store"))` (retained snapshots feed the same store; blob
  `sha256` rechecked), `proofs.prove(...)`; on success write `confirmations/<id>.json` and a FIX-PENDING rule row via new
  `accept.accept_fix_rule` (DETECT_ONLY, `fixer_ref` None, final detector_ref/params, origin GENERATED, review_required true, official evidence shipped
  with `ship_linked_evidence` rules) and skip the ordinary detect-only candidate for that change (`gen.generate(skip_change_ids=...)`). Failure =>
  refusal reason in `summary["autofix_refused"]` (coded) and the ordinary candidate flow continues. Steps 7-8 validate the pending rows as DETECT_ONLY.
4 step 9 `rule-tests`: first call `_write_release_provenance(ctx)` (idempotent, depends only on VERIFIED records; fixes finding (e)), then
  `autofix.promote_certified(ctx, tree)`: for each pending row run `confirmation.verify` L1+L2; then `cert.issue(row, evidence_rows,
  source_confidentiality=cert.source_confidentiality_from_index(index), change_class=confirmation.derived_class)` (executor = the one attached at the
  composition root, via `trusted_executor()`; core never imports it); write `certifications/<id>.json`; set on the row `fixer_ref`, `maturity
  FIX_ENABLED`, `review_required false`, `approval = cert.reference(record)`, `tests {positive,negative,idempotence: "auto-cert:<check>"}` (labels for
  gate 3, not trusted); then the existing `_fix_trust_findings` is the final authority. A row failing issue or trust is DEMOTED to its pending form
  (fixer/approval/cert removed, reason in `rule-tests` output `autofix_demoted`); it never blocks the build. Insufficient evidence = never reaches 3.
5 steps 12-17 unchanged (manifest covers `confirmations/` and `certifications/`; P10 import and loader call `fix_row_trusted`).
6 `fix_row_trusted`: for origin GENERATED a row is governed iff `approval` is `auto-cert:`; it then REQUIRES a verified confirmation (L1) in addition to
  gates 1-5 and the cert; a GENERATED row without confirmation is never FIX_ENABLED. `fix_templates.eligible(row, class, *, confirmation_verified)`
  admits GENERATED only when True; `executor.eligible` receives that flag from `cert._build` (new keyword, default False).
7 Execution-equals-certification: templates gain `fixer_ref`, `detector_refs`; `eligible` requires `row.fixer_ref == template.fixer_ref` and detector in
  the set. New non-core `transformers/imported.py` (resolver + `rewrite_imported_symbol`, `remove_imported_decorator`) and `rules/python/certified.py`
  (bound fixers `rewrite_imported_symbol(document, ctx, *, module, old, new)`, `remove_imported_decorator(document, ctx, *, module, name)`; detectors
  `flag_imported_symbol(..., module, old)`, `flag_imported_decorator(..., module, name)`; names must follow `FIXER_PREFIXES`) added to
  `BINDABLE_MODULES`. `FixCertifier.exercise` runs the BOUND rule fixer through `Document`+`RuleContext`+`apply_edits` (the loader path), getting
  functions from the module table passed by `builtins.build_context` (`FixCertifier(modules=BINDABLE_MODULES)`); `transformer_identity` digests the
  fixer, the primitive and the resolver sources. The old literal templates (`replace_call_name/replace_attribute/remove_decorator`) get
  `change_classes=()`; templates become `python.rewrite_imported_symbol {module,old,new}` (S1,S2) and `python.remove_imported_decorator {module,name}` (S3).
  Fixtures include: import+call positive, shadowed-name negative (zero edits), string/comment negative, alias import, idempotence, conflict probe.
## F4. Task split (max 3 concurrent Haiku; disjoint files; Sonnet reviews each handoff)
A (core proofs and confirmation, pure): `knowledge/extract/proofs.py`, `knowledge/extract/domains/python_orm.py` (facts only), `knowledge/update/machine_confirmation.py` (`prove`, `check_witness`, `build`, `verify`, `derived_class`), `knowledge/schemas/machine_confirmation.schema.json`; tests `tests/unit/knowledge/kap/test_proofs.py`, `tests/unit/knowledge/update/test_machine_confirmation.py`. Accept: every F1 clause has a positive and a refusal test (>=30 cases incl. recursion,
  global ref, star import, decorator present, alias with extra statement, `__getattr__`); every witness/record field flip fails L1; digest deterministic;
  import-graph, extract-boundary and no-customer-code guards green. Extractor drafts byte-identical for existing fixtures (existing extract tests pass).
B (non-core execution): `transformers/imported.py`, `rules/python/certified.py`, `rules/bindable.py`, `transformers/fix_templates.py`, `transformers/certify_exec.py`, `builtins.py` (attach only), existing `tests/unit/knowledge/update/test_certification.py`, and the fix-template/certify tests; new `tests/unit/transformers/test_imported_primitives.py`, `tests/unit/rules/test_certified_fix_rules.py`. Accept: resolver cases (alias, shadow, double-bind, string, comment, decorator stack) ; engine run through
  `bind_rule`+`fixing_transform` equals certification output; certification issue/verify green for S1-S3 params with `confirmation_verified=True`, refused without;
  `detector_table` still validates; GENERATED refused when flag False; old templates refused with reasons.
C (pipeline and trust wiring): phase 1 (independent of A/B): `knowledge/pipeline.py` (provenance-before-step-9, hooks), `knowledge/candidates/generator.py` (`skip_change_ids`),
  `knowledge/candidates/accept.py` (`accept_fix_rule`), `knowledge/release/safety.py`, `knowledge/update/certification.py` (`confirmation_verified`, class from
  confirmation), `knowledge/loader.py` only if its cap path needs the confirmation arg; phase 2 (after A and B merge): `knowledge/update/autofix.py`, tests
  `tests/unit/knowledge/update/test_autofix.py`, `tests/unit/knowledge/kap/test_safety_confirmation.py`, `tests/integration/kap/test_autofix_e2e.py`. Accept: tampered
  confirmation/cert/rule/blob each => KAP_FIX_CAPPED at load, P10 at import, SAFETY_NOT_VERIFIED at build, `promote` still refuses `auto-cert:`.
Order: A and B and C-phase-1 in parallel; C-phase-2; then full suite + `tools/ci_check.sh` + Sonnet security review before any claim. Interface contract is fixed by F2/F3 names.
Integration spec `test_autofix_e2e.py` (synthetic only, local git repos, tmp kb-home, no network): repo v1/v2 with `odoo/tools/helpers.py` (S1 `old_round` -> `new_round` with
`Replaces ``old_round``` docstring, identical bodies; S2 `legacy_sum(a, b)` delegating to `new_sum` in v2), `odoo/api.py` (S3 identity `multi` removed in v2), plus decoys (S1
without hint; body referencing a module constant; method rename; keyword removal). Run `update`/build -> release INSTALLED -> activate -> `migrate --fix` on a fixture custom module
(import+call sites, a file shadowing `old_round`, string/comment mentions). Assert: S1-S3 rules are FIX_ENABLED with `auto-cert:1:` approval, confirmation+cert files present, ledger entries still
`confirmed:false` with a `machine_confirm` history entry; decoys DETECT_ONLY with the coded reasons; fixture output exactly expected, shadow file untouched, second `--fix` is a no-op, rebuild is
byte-identical; negative: conflicting custom rule on the same span applies one edit, other rejected; tamper (each of: witness field, record_digest, rule params, cert approval ref, confirmation of another
rule swapped in, deleted confirmation, corrupted snapshot blob) => capped DETECT_ONLY at load and refused at import/activation; migrate still detects. Insufficient-evidence run keeps DETECT_ONLY end to end.
## F5. Owner decisions (only genuinely new) and contract notes
D-F1 (security/licensing) Witness holds facts and digests, no source text (Odoo CE is LGPL, Enterprise OEEL); consequence: source re-proof (L2) happens only where the retained snapshots exist (build, update pre-activation); on a customer machine L1 + the manifest/provenance chain is the trust root. Decided: accept; owner may veto and require deep re-verification at import.
D-F2 Enterprise-sourced pairs may produce FIX_ENABLED rules in the INTERNAL release only (never exported; confirmation shows symbol names exactly as rule messages already do, see verification.md finding 2).
Decided (no owner action unless you want Enterprise excluded). Decided here, no owner action: ledger contract unchanged; contracts/release-lifecycle gains `confirmations/`; A4 literal templates superseded; GENERATED
origin may be fix-eligible only with a verified confirmation; step count stays 17; `promote` stays human-only.

