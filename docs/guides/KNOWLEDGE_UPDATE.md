# Knowledge base update (developer guide)

This guide describes how the knowledge base is kept current with the official Odoo sources: the commands, the trust rules, what an update can and cannot do, and how to recover. It documents feature 012 as implemented. The specification is [spec.md](../../specs/012-knowledge-base-auto-update/spec.md); the command reference with sample output is [quickstart.md](../../specs/012-knowledge-base-auto-update/quickstart.md).

Nothing in this guide has been verified against live upstream repositories, a real Enterprise repository or a production source. The offline behaviour was run; the online behaviour is described from the code and its synthetic-repository tests.

## 1. Mental model

- **One knowledge base.** There is one active Knowledge Release at a time, with one rule registry and one `migrate` pipeline. Community and Enterprise are two *source families* that feed the same release. A family is a label on a source, not a separate store.
- **Sources come from a catalog.** `src/odooflux/knowledge/update/catalog.json` lists one Community and one Enterprise source for each of 12.0 to 19.0 (18 entries). Each entry is a branch of an allow-listed official repository. No commit SHA is stored; the commit is resolved when the update runs.
- **Activation is all or nothing.** An update builds a complete candidate release and swaps the active pointer once, atomically. Anything less leaves the previous release active.
- **Nothing is assumed.** A new upstream version is reported, never migrated to. A rule is trusted by a stated predicate, never by its own claim.

## 2. Commands

| Command | Network | Writes | Purpose |
|---|---|---|---|
| `knowledge check` | `ls-remote` only (none with `--offline`) | nothing | Compare the official branch heads with the installed release. |
| `knowledge update --dry-run` | `ls-remote` only (none with `--offline`) | nothing, no lock | Show what an update would do. |
| `knowledge update` | yes (none with `--offline`) | release store, pointer, history | Discover, acquire, build, evaluate, activate. |
| `knowledge status` | none | nothing | Show the installed release and its limitations. |
| `knowledge history` | none | nothing | Show the verified update history, newest first. |

`migrate` never uses the network. It reads whichever release is active.

Exit codes and outcomes are listed in [quickstart.md](../../specs/012-knowledge-base-auto-update/quickstart.md#7-exit-codes).

## 3. Fresh install

There is no separate installer. On a kb-home with no installed release:

1. `knowledge check` reports every changed source and notes that a fresh install would be built. The Community sources must be readable.
2. `knowledge update` acquires the Community sources (and Enterprise sources only when credentials are present), builds a release, evaluates it and activates it.
3. Without credentials the release is Community-only. Enterprise sources are reported as `SKIPPED_NO_CREDENTIALS` and nothing is carried, because nothing was installed.

Until a release is activated, `migrate` uses the built-in knowledge shipped in the wheel. `knowledge status` says so: `active release: none (built-in knowledge only)`.

Offline, a fresh install is impossible: an offline update is `BLOCKED` with `CHECK_UNAVAILABLE` and records that in the history.

## 4. Checking for changes

```bash
odooflux knowledge check              # online: one ls-remote per repository
odooflux knowledge check --offline    # no network; exit 4 with CHECK_UNAVAILABLE
```

`check` makes exactly one `git ls-remote --heads --refs` call per distinct repository. It reads branch heads only; it never downloads objects, and it never writes. It reports per source one of `OK`, `SKIPPED_OFFLINE`, `SKIPPED_NO_CREDENTIALS`, `AUTH_FAILED` or `UNAVAILABLE`. These are never merged into one status.

Two rules govern the overall verdict (`knowledge/update/discovery.py`):

- `NO_UPDATE` is claimed only when every Community source was read and matches, no new version exists, and no installed Enterprise source was unreadable.
- Freshness of Enterprise knowledge is `FRESH` only after a successful read. Without a read it is `STALE_UNVERIFIED` (installed) or `NOT_INSTALLED`.

## 5. Updating existing knowledge

```bash
odooflux knowledge update --dry-run   # read-only plan
odooflux knowledge update             # apply
```

For an installed release, an update:

1. Compares the catalog with the installed release's recorded revisions (`release.json` `sources`) and snapshot digests.
2. Plans per source (`knowledge/update/planner.py`): `ACQUIRE` when the source is not installed or its remote head changed; `CARRY_FORWARD` when the head is unchanged, or when the source is installed but cannot be read (any family, including an Enterprise source without a token); `SKIP` otherwise (for example a Community source that is new but cannot be read, or an Enterprise source that is not installed and has no token).
3. Acquires only what the plan requires. Each fetch is by commit SHA, verified against the requested SHA, and placed in a managed cache under `<kb-home>/updates/cache`. The cache is never a working tree and never executed.
4. Builds the candidate release with the existing 17-step pipeline in `<kb-home>/staging/update/`.
5. Evaluates activation (section 7). If allowed, swaps the pointer once.

### When an update is a no-op

`NOOP` requires both:

- the planner says nothing changed, and
- the build inputs (source SHAs, snapshot digests, catalog digest, extractor and rule-schema versions, build configuration, parent release) equal the ones persisted in the last `ACTIVE` or `NOOP` history record.

If no such record exists, the update builds. A planner `NOOP` alone never skips a build.

### Scoped update (`--from N --to M`)

`odooflux knowledge update --from 16 --to 17` acquires only the Community sources of the selected pair (16.0 and 17.0), and Enterprise sources of those versions only when credentials are configured. Other catalog versions are not downloaded, do not block the run, and an already installed one keeps its trusted revision. The catalog itself stays complete, and an unscoped `knowledge update` still acquires every catalog version. A first fetch of `odoo/odoo` is a few hundred MB; on a slow link set `ODOOFLUX_FETCH_TIMEOUT` (seconds, 60 to 7200, default 300) and, if brief stalls abort a transfer, `ODOOFLUX_FETCH_LOW_SPEED_TIME` (seconds the transfer may stay under 1000 bytes/s, 60 to 900, default 60; applied to that git process only, never written to a git config). A stalled transfer still fails.

### Pairs and transitions

Source pairs are per transition (for example 16.0 to 17.0), one per family. A pair is built only when both of its sources are available for the run (acquired or carried). An unavailable source leaves that transition out of the build; the report says so, and completeness reflects it. Pair keys are unique within a build: two pairs sharing a step need distinct keys, otherwise the pipeline raises `ValueError` (`duplicate pair key(s)`).

## 6. New upstream versions

A new numeric major branch (for example `20.0`) is discovered from the remote and reported as `NEW_VERSION_DISCOVERED`. The report then says `Migration support: not established`.

- It is never an automatic migration target. The planner builds only the transitions the catalog names.
- Adding a version to the catalog is a maintainer change to `catalog.json`, validated by `catalog.py` (exact contract, licence fields, no URL with credentials, no placeholder licence). Adding it does not make a transition supported; the knowledge for that transition (ledger, evidence, rules and tests) must exist and pass the release gates.
- Treat a new version as a separate piece of work. Follow the process in [ADDING_A_VERSION.md](ADDING_A_VERSION.md) and the feature 011 KAP workflow, not the update command.

## 7. Automatic activation rules

An update activates a release only when `activation.evaluate` allows it. A decision is blocked by any of these codes (`knowledge/update/activation.py`, `BLOCKING_CODES`):

| Code | Blocks when |
|---|---|
| `COMPLETENESS_FAILED` | The release completeness is anything other than `COMPLETE` or `PARTIAL` (for example `FAILED`, or not recorded). |
| `CAPABILITY_LOST` | A rule id of the installed release is missing from the candidate, or was retired, and no approved semantic replacement covers it. |
| `CAPABILITY_DOWNGRADED` | A rule's maturity became lower (for example `FIX_ENABLED` to `DETECT_ONLY`). |
| `FIX_NOT_TRUSTED` | A `FIX_ENABLED` row in the candidate is new or changed from a previous `FIX_ENABLED` row and fails the trust predicate (section 9). |
| `ENTERPRISE_COMPAT` | A carried Enterprise module has a dependency that does not resolve in the candidate's inventory, or there is no previous release to compare against. |
| `INTEGRITY` | The candidate release does not verify, or is not installed under the kb-home. |

Rules of the decision:

- `PARTIAL` completeness is allowed only when none of the codes above applies. A warning is attached: `PARTIAL: incomplete coverage; unsupported transitions remain`.
- `FAILED` completeness is never allowed.
- Semantic supersede (section 8) may approve a removed rule id, so a rotated id is not reported as lost.
- A changed `DETECT_ONLY` rule produces a warning, not a block.

A blocked decision appends a `BLOCKED` record and leaves the pointer alone.

Activation itself reuses `cli/kap_release.activate`, the single atomic pointer swap. Fault points `verify`, `lock`, `pointer` and `audit` are covered by tests; each leaves the previous release active and records `ROLLED_BACK` or `FAILED`.

## 8. Detection and fix eligibility (what an update can and cannot change)

This section states the facts without softening them.

- **Detection rules** can be added, changed or removed by a release. A removed rule without an approved replacement blocks activation.
- **Automatic fixes (derived, certified).** During an update build the pipeline can create a `FIX_ENABLED` rule without a human approval, but only for three machine-proven classes, all for one Python module's top-level symbols resolved through the file's own imports: `S1` a documented replacement whose old and new definitions are identical after the name change, `S2` a pure forwarding alias (immutable defaults, at most one deprecation warning), `S3` a removed decorator that was exactly an identity function. Each rule carries a `machine-confirmation/1` record (`knowledge/confirmations/<rule_id>.json`) and a `fix-certification/1` record (`knowledge/certifications/<rule_id>.json`) with approval reference `auto-cert:<policy>:<digest>`. The ledger `confirmed` flag stays false (it is human-only), `promote` refuses `auto-cert:` references, and nothing is trusted from a stored flag: the class is recomputed from the witness and the certificate is recomputed by running the same bound fixer the loader executes, at build, import (P10), load and activation. Any failure demotes the rule to `DETECT_ONLY` with a coded reason; it never fails the build.
- **Ambiguous renames are capped.** When one removed or added subject has many equally good rename partners (thousands of plain fields share identical attributes), the ledger entry is `UNKNOWN` and lists its 10 smallest candidate names; `detail.candidate_count` holds the exact total. Earlier builds listed every candidate, which made a full Odoo pair impractical (hours and tens of GB). `UNKNOWN` entries are never confirmed and never become fixes.
- **Import-time effects.** The proofs read module text, so a module on either side is refused (`MODULE_EFFECT`) when it does anything at import beyond a safe subset: imports, definitions, class bodies of safe statements, a docstring, assignments to plain names, and `if`/`try` around those, where every call is an allow-listed constructor or framework helper (`fields.*`, `api.*`, `getLogger`, `namedtuple`, a few builtins). `os.sep = "x"`, `os.environ.update(...)`, loops, `with`, bare expression statements and calls to anything else keep the pair `DETECT_ONLY`, whether or not they mention the pair.
- **What stays `DETECT_ONLY`.** Similarity-only renames, keyword renames or removals, method/field/attribute changes, moved symbols, AI-proposed pairs, bodies that use reflection, globals or module state, files with star imports, shadowed or re-bound names, stores to the target, string or `__all__` references, and anything without verified official evidence. Coverage is deliberately narrow: it is the safe subset, not every migration change.
- **Shipped `FIX_ENABLED` rules** keep their status by *inherited trust* (D3): a row byte-identical to the shipped baseline is trusted, and the decision is recorded in the audit entry `release_installed.details.inherited_trust`. Any other `FIX_ENABLED` row, new or changed, must pass gates 1 to 5 (official evidence, verified provenance, authoring checks).
- **Certification** is issued only by the pipeline for the classes above (no `knowledge rule certify` command exists). Machine confirmation is self-consistent at import and load (L1); where the retained verified snapshots exist (build and update pre-activation) the witness is re-proven from the source blobs (L2). A package or release without those blobs is trusted only through its manifest digest plus L1, so a release you did not build yourself is as trustworthy as its provenance. Enterprise-sourced pairs yield `FIX_ENABLED` rules only in the internal release, which is never exported.
- **Semantic supersede** (`semantic-replacement/1`) approves the removal of a rule only when a replacement with equal executable semantics and at least equal maturity exists. Built-in, manual, origin-less and retired rows are never approved.

`knowledge status` shows the outcome of this: how many rules are `DETECT_ONLY`, `DRAFT` and `FIX_ENABLED`, and how many are certification-governed (`certification-governed rules: 0` on a fresh tree).

## 9. Trust predicate for FIX_ENABLED rows

One predicate, `safety.fix_row_trusted`, is used by the loader, the build, the importer (P10) and activation:

1. A byte-identical shipped built-in row is trusted (inherited trust). This needs the verified shipped baseline digest.
2. Any other `FIX_ENABLED` row must pass gates 1 to 5. If a certification record governs the row (a file under `certifications/` for its id, or an `auto-cert:` approval), that record must also verify. Certification only adds a requirement.

Trust is never granted by a row's own `origin` field, and a row's own claim that it is official is not evidence.

## 10. Partial knowledge

A release is `COMPLETE` or `PARTIAL`. `PARTIAL` lists explicit limits, and the update output carries the limitation list on every run:

- migration support not established;
- production certification not granted;
- Enterprise freshness unknown without a check.

`PARTIAL` can activate (section 7). The update output does not present it as complete.

## 11. Offline behaviour

Offline is zero network, enforced in code before any credential or CA-bundle handling (`remote_git.network_allowed`):

- `--offline` or `ODOOFLUX_OFFLINE=1` on `check` or `update`;
- `status`, `history` and `migrate` never use the network;
- `update --offline --dry-run` reads nothing from the remote, and an offline apply is `BLOCKED` with `CHECK_UNAVAILABLE` (it records one history entry).

Offline, no token is read. A test asserts this for the acquisition layer (`test_offline_never_reads_the_token`).

## 12. Enterprise credentials

### Configuring a token

Set one of:

- `ODOOFLUX_ENTERPRISE_TOKEN` (the value), or
- `ODOOFLUX_ENTERPRISE_TOKEN_FILE` (a path to a regular file, owner-only, not a symbolic link, at most 4096 bytes, one token with no whitespace or control characters).

If both are set, the environment variable wins. A bad configuration gives one warning with a closed code and the run continues without a token.

### Rules

- The token is attached only to calls whose validated identity is the official Enterprise origin (`https://github.com/odoo/enterprise.git`). Community calls never receive it.
- Git is driven through an OdooFlux-owned `GIT_ASKPASS` stub with the secret in a child-only environment variable. No credential helper configured by the user runs. No token appears in argv, a URL, git configuration, a file or a message.
- `http.sslVerify` is never disabled. `ODOOFLUX_CA_BUNDLE` is applied per call only.

### What happens without credentials

Without a token, or with `--offline`:

- Enterprise sources are reported `SKIPPED_NO_CREDENTIALS` (or `SKIPPED_OFFLINE`). No Enterprise fetch is attempted.
- If an Enterprise release is already installed, its Enterprise components are **carried forward**: their verified snapshots are re-extracted unchanged from the kb-home (`RetainedSnapshotAdapter`), and the new release keeps them.
- Their freshness is `STALE_UNVERIFIED`. It is never reported as `FRESH`, and never as removed.
- The carried components must still resolve: `inventory.carry_forward_compat` checks that every carried Enterprise module's dependencies exist in the new inventory. This is an existence check, not a source verification, and the report says so. Failure blocks with `ENTERPRISE_COMPAT`.
- If the retained snapshot is missing or does not match the digest recorded at install time, the source fails closed. The previous release stays active.

With a token that is rejected, the status is `AUTH_FAILED`, which is distinct from `UNAVAILABLE` and from `SKIPPED_NO_CREDENTIALS`. Installed Enterprise knowledge is carried in that case too. Community is not blocked unless `--require-enterprise` is given, which blocks the update (and records it) when Enterprise cannot be refreshed.

With a token that works, a normal update acquires the Enterprise sources and enriches the same lineage. The parent is the previous release.

## 13. Confidentiality

An Enterprise source is licensed. Its content must stay on the machine that holds the entitlement.

### What the code does

- A release is **internal** when it holds Enterprise-derived material. `release.json` then carries `confidentiality: "internal"`, covered by the release digest. The marker is derived from the sources; it is not a flag an operator sets.
- **Internal and Enterprise-derived releases are never exported.** `package export` refuses them with `EXPORT_REFUSED`, nothing is written, and the message says that no public or Community-only projection of the release exists. There is no `--public` option and no override flag; the Feature 011 `include_enterprise_derived` escape hatch is removed. A release built from Community sources only exports as usual.
- **Internal packages are refused on import** before anything is staged (P12, `INTERNAL_RELEASE_REFUSED`). `package validate` reports P12 too.
- **Reports show ids, not content.** The confidentiality view (`knowledge/release/confidentiality_view.py`) is the one policy. It decides Enterprise status from the verified provenance index only, never from a record's own field, and it never changes stored bytes. It withholds or reduces: Enterprise-derived evidence, change records (location, detail and symbol name; the symbol becomes `<enterprise KIND DIGEST>`) in `ledger list` and `ledger show`, findings in `validate` and `rule validate`, `refresh` candidates, rule `message` and `suggestion` text of Enterprise-derived rules (in migrate reports and `rule inspect`; matching, ids, params and fixers are unchanged), and Enterprise source ids, upstream revisions and snapshot ids in `check`, `update`, `status` and `history` output, text and JSON (replaced by `<enterprise DIGEST>`, stable so rows stay comparable). Fail closed: for an installed release whose provenance index is missing, unreadable, malformed or lists a source twice, findings and rule texts are withheld, `ledger list/show` refuse, and in update output every full commit-like hex string is withheld. Knowledge with no release (the built-in tree) is unaffected.
- **Pipeline step 13** (`validate-package`) is skipped for an internal release with `INTERNAL_NOT_EXPORTABLE`, because there is no package to round-trip.

### Residual leaks (known, not fixed)

1. **Output is scrubbed by known identifiers.** Source ids, revisions and snapshot ids are matched as exact strings taken from the installed releases' provenance (plus the remote revisions read by a check). Free text that merely describes an Enterprise symbol in a place the view does not cover (for example text typed by a human into a rule through `rule create`) is not recognised. A rule's `validate` finding lines for Enterprise evidence files are withheld, but other free-form fields are not inspected.
2. **Which Enterprise editions you use is not hidden from yourself.** The installed provenance and the release manifest keep the full ids and revisions; the view only affects rendered or serialised output.
3. **Detection is for display only.** The view is not a secrecy boundary against someone who can read your kb-home. Never share the kb-home or an internal release; there is no public projection of it.

Also: the internal release **does** ship Enterprise snapshot manifests (paths and content hashes, never content) inside the internal release. This differs from the plan (deviation D-A in [spec.md](../../specs/012-knowledge-base-auto-update/spec.md#deviations-from-the-plan)). The retained blobs stay in the user's kb-home staging area and are never part of any release or package.

## 14. Source provenance

Every acquired source is identified by:

- its catalog `source_id` (`odoo-community-<version>` or `odoo-enterprise-<version>`);
- the allow-listed https origin (`repository` in the catalog, `expected_origin` for the check);
- the pinned 40-hex commit (`revision`) and a snapshot digest over its entries;
- for Enterprise entries, `confidentiality`, `licence_id` and `licence_access`.

The licence identifier is declared by the maintainer. The loader checks its form and refuses placeholders such as `UNKNOWN`. It does **not** verify the licence against the upstream repository. Keep that responsibility in mind when you add an entry.

Provenance entries for public sources keep the Feature 011 shape. The identity of a locally configured remote is a declared identity, not a cryptographic proof (INTEGRATION_NOTES note 14).

## 15. Certification limitations

- No CLI verb creates certification records. No pipeline step issues them.
- An `auto-cert:<policy>:<digest>` reference is labelled automated. It is never a human approval, `promote` refuses it, and it does not satisfy the human approval gate.
- A certification record is recomputed on every verify. A stored pass flag, a changed input, a tampered digest or an executor that was not attached by the composition root is refused.
- Production certification is never granted by an update. Every update report states `production certification: NOT_GRANTED`.

## 16. Failure recovery and rollback

| Situation | What happens | What to do |
|---|---|---|
| Interrupted before the pointer swap | Previous pointer stays. | Run `update` again. Acquired commits in the cache are reused after verification. |
| Failure during the pointer swap | `ROLLED_BACK` (previous pointer) or `FAILED` (pointer unreadable). | Run `knowledge status` and `knowledge release audit-verify`. Use `release activate` or `release rollback` if needed. |
| Gate code stops the build | `BLOCKED` with the gate code. | Read the reason. Fix the input (rule, evidence or source), then update again. |
| Update lock held by another process | `BLOCKED` with `CONCURRENT_UPDATE`. | Wait. Nothing was recorded. |
| History chain edited or truncated | `status`, `history` exit 1; `update` refuses to run. | Restore `updates/history.jsonl` from a backup. Never edit it. |
| Wrong kb-home | The command reads that kb-home (for example a new empty one shows built-in knowledge). | Check `--kb-home` and `ODOOFLUX_KB_HOME`. |

Rollback of an installed release:

```bash
odooflux knowledge release list
odooflux knowledge release rollback      # the previous release becomes active
odooflux knowledge release deactivate    # back to built-in knowledge
```

`release remove` deletes only an installed, inactive release. The update history is append-only: a rollback is recorded by the release audit chain, and the update history keeps the record of the earlier decision.

## 17. Troubleshooting

See the table in [quickstart.md](../../specs/012-knowledge-base-auto-update/quickstart.md#9-troubleshooting). Two additional notes for developers:

- `knowledge refresh --search-candidates` was fixed in this change (the `git grep` output parser and pathspec); a regression test covers it.
- The Feature 011 command `knowledge source acquire` does not register a `GIT_ENTERPRISE` adapter. Enterprise acquisition happens through `knowledge update`, which registers it.

## 18. Tests

The update manager is tested offline with synthetic local repositories and injected remote seams. Relevant modules:

- unit: `tests/unit/knowledge/update/` (catalog, discovery, remote git, credentials, acquisition, planner, inventory, capability, activation, certification, orchestrator, CLI, report, history, supersede policy);
- unit: `tests/unit/knowledge/kap/test_enterprise_provenance.py`, `test_internal_release_export.py`, `test_certified_fix_trust.py`, `test_linked_evidence.py`, `test_confidentiality_view.py`;
- integration: `tests/integration/kap/test_pipeline_unified.py`, `test_pipeline_supersede_policy.py`, `test_update_orchestrator.py`, `test_migrate_unified_inventory.py`, `test_report_confidentiality.py`;
- packaging: `tests/integration/packaging/test_update_wheel.py`, which is opt-in (`ODOOFLUX_PACKAGING_INSTALL=1`) and skipped by default.

Run a module with `python -m unittest tests.unit.knowledge.update.test_orchestrator -v`. The feature's verification status is recorded in `specs/012-knowledge-base-auto-update/verification.md` by its owner.

## 19. Real-source scale (verified on Odoo 16.0 to 17.0)

A full Community 16.0 to 17.0 build was run end to end from official sources (see `specs/012-knowledge-base-auto-update/verification.md`). What it showed, and what changed because of it:

- **Size.** About 157,000 ledger changes, 37,800 changes eligible for the automatic-fix prover, 3,345 rule candidates, 2,877 rules in the release (2,786 generated, all `DRAFT`, plus the 91 shipped).
- **Time.** About 2 minutes to extract and about 36 minutes to accept the 3,345 candidates (whole-tree validation per accepted rule is deliberate and still grows with the tree).
- **Automatic fixes: none.** The prover refused all 37,847 eligible changes. A sample showed 74% are removed files that no longer exist in 17.0, 19% are changed bodies that are not pure forwarding aliases, and 7% are not `python_orm` functions; 44 removed decorators were not identity functions. No requirement was relaxed.
- **Coverage is `PARTIAL`, honestly.** 35,286 changed files (docs, `.po`, `.js`, data) have no parser, 69% of changes are classified and 1.7% have a disposition. 559 candidates were refused by the duplicate check (`A002`: same step, detector and params as an accepted rule) and their changes stay `UNRESOLVED`.
- **The coverage recompute bundle is compact.** `coverage/inputs.json` keeps only the fields the coverage code reads (`change_id`, `class`, `disposition`, evidence ids, `subject_key`, location paths) in compact JSON: 237 MB became 52 MB, under the 64 MiB per-file package limit (78% of it, so a larger pair could still reach the limit).
- **Evidence ids** are `EV-` plus at least three digits (`EV-1000` follows `EV-999`).
- **Ambiguous renames are capped** (see section 8).

## 20. Platform, verification and certification status

- **Operating systems.** Verified on Linux only. The update lock uses POSIX file locking (`fcntl`), so macOS is expected to work but was not verified, and Windows is not supported for `knowledge update`.
- **Offline guard.** `migrate` is offline by construction; the no-network check is enforced in-process (a test patches sockets), not by the operating system.
- **Real-source verification.** Automatic fixes and the update path are verified on synthetic sources and on local git repositories. The real-source pilot (Odoo Community 16.0 to 17.0, section 19) is recorded in `specs/012-knowledge-base-auto-update/verification.md`. It is one pair, Community only; nothing was verified against Enterprise sources or other pairs.
- **Production certification: `NOT_GRANTED`.** An internal release candidate is not a production migration certification. No Odoo 16 to 17 (or any) migration is certified by this release, Enterprise migration is not verified against real Enterprise sources, and newly discovered versions get detection only until a release has been built and verified for them.
