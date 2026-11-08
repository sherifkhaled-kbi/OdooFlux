# Documentation verification: KAP (feature 011)

Date: 2026-11-08. Scope: `README.md` (new section 11 and cross-links) and `docs/TECHNICAL_USAGE.md` (new subsections and cross-links).
Code version: 0.2.0 checkout on Linux, Python 3.12, git 2.43.0. No code, test, commit, network, Docker or live AI action was taken.

## Files changed

| File | Change |
|---|---|
| `README.md` | Status bullet; TOC entries; new section 11 "Knowledge Base releases and acquisition (KAP)" (11.1 to 11.9); "Project documentation" renumbered to 12; short KAP notes in 1, 6.1, 6.2 (options, report `schema_version` 1.1.0), 6.7, 6.10 (count predates KAP), 8, 10 (two troubleshooting entries), and KAP rows in the documentation table. About 1,000 lines added. |
| `docs/TECHNICAL_USAGE.md` | TOC entries; new subsections 2.4, 3.3, 4.12, 5.7, 6.11, 6.12, 6.13, 7.9 to 7.14, 9.5, 10.9, 12.8 to 12.12, 13.8; a KAP note in 10.2; two Mermaid diagrams (lifecycle, injection). |
| `docs/reviews/automated/DOC-verification-kap.md` | This report. |

Existing content was not rewritten. The only edited existing lines are TOC lines and the renumbered section 11 heading in the README. `docs/reviews/fragments/kap.md` is linked; it existed at check time (written in parallel by another author, not reviewed here).

## Counts

- Documented KAP surface: 8 groups (`release`, `package`, `source`, `ledger`, `rule`, `candidates`, `coverage`, `ai`) and 1 top-level verb (`extract`). That is **47 verbs**. Each appears in README 11.5.
- Options: **241** option entries across the 47 verbs, taken from `--help` (excluding `-h`). They cover **82 distinct long option names**. README 11.5 tables list **147** of the 241 entries (the key options). Of the 82 distinct names, **72** appear in README section 11 or in the KAP sections of `TECHNICAL_USAGE.md`. The rest are reachable through `--help`. The ten not mentioned: `--ai-budget-file-tokens`, `--ai-budget-job-cost`, `--ai-budget-module-tokens`, `--ai-budget-request-tokens`, `--ai-clear-cache`, `--ai-endpoint`, `--ai-no-cache`, `--ai-provider-type`, `--ai-timeout` (all `ai propose`), and `--output` (alias of `-o`, `package export`).
- Exit-code tables: 0 to 5 for KAP, compared with the migrate table (section 6.1).
- Fail-closed tamper cases in the provenance test: the test file names **eight** subtests, not nine as the brief states (see discrepancies).

## Verification methods

1. **Help dump.** `--help` was captured for every group and every verb with `PYTHONPATH=src python3 -m odooflux knowledge <group> <verb> --help`, from a temporary directory. Exit status 0 for all 47 verbs. Each group's `register()` was read for defaults, required options and exit-code branches (`cli/kap_*.py`).
2. **Command and flag check (script, temporary directory).** Every `knowledge <group> <verb>` mention in code blocks and prose, and every backticked `group verb` in the README tables, was matched against its verb's help: **119** flag references in examples and **149** in table rows. Result: 0 unknown flags. One table row was reported (`ai propose` with `--allow-network`); this was a checker artefact, since exit-code table row 2 names two verbs. A first version of the verb-coverage check searched for bare verb names and reported false results; it was corrected before the figures above were taken. Seven "unknown verb" hits were English prose ("knowledge release is missing") and are not commands.
3. **Global flag check.** Every long flag in README section 11 (72 distinct), the KAP sections of `TECHNICAL_USAGE.md` (50 distinct, of which 46 are KAP or migrate flags; `--check` is in existing `matrix` text, and `--no-optional-locks`, `--no-replace-objects`, `--show-toplevel` are git options from section 12.9), and the README migrate notes was checked against the KAP and migrate help. None unknown.
4. **Examples run.** Every example output shown in the README was produced by a real run. Temporary directory only. Inputs: a copy of `src/odooflux/knowledge` (never the shipped tree), a synthetic 16.0 to 17.0 git repository from `tests/fixtures/kap/make_synth_repo.py`, a copy of the golden sample `tests/golden_fixtures/17.0/kbi_demo` without `expected/`, and fake fixtures written for the test. Paths, IDs, digests and timestamps are shortened in the docs; the shapes match the runs. Details in section "Examples run" below.
5. **Links and anchors (script).** All 181 internal links and anchors in `README.md` and `docs/TECHNICAL_USAGE.md` resolved: 0 broken. Anchors were checked with a GitHub-style slug of each heading.
6. **Paths.** Every path named in the new text was checked by the link check, or by `ls`/`find` against the repository (directory inventory, section 2.4).
7. **Environment variables.** Each name was grepped in `tests/` and `src/`:
   - `ODOOFLUX_KAP_LIVE_TESTS`, `ODOOFLUX_KAP_CLONES`, `ODOOFLUX_KAP_CLONE_REV`, `ODOOFLUX_KAP_FETCH_URL`, `ODOOFLUX_KAP_FETCH_SHA256`, `ODOOFLUX_KAP_DOCKER_TESTS`, `ODOOFLUX_KAP_TEST_KEY`: found in `tests/` only (the KAP test suite).
   - `ODOOFLUX_KB_HOME`, `ODOOFLUX_AI_DISABLE_EXTERNAL`, `ODOOFLUX_AI_FAKE_SCRIPT`, `XDG_DATA_HOME`, `LOCALAPPDATA`: found in `src/`.
   - Skip conditions for the live tests were read from `tests/integration/kap/test_live_sources.py`.
8. **Mermaid.** No renderer is available offline. The two KAP diagrams were checked by eye against `knowledge/pipeline.py` (`REAL_STEPS`, `_build_package`, `_publish`, `_export`, `_import_activate`) and `builtins.py` (lines 86 to 92). Syntax was checked by script: balanced quotes and brackets, and matching `subgraph`/`end` pairs. Not rendered.
9. **Test counts.** Module and function counts come from an AST scan of the test files (no test was executed): unit `tests/unit/knowledge/kap` has 89 modules and 749 functions whose names start with `test`; integration `tests/integration/kap` has 9 modules and 60 such functions.
10. **Test commands.** The commands in section 9.5 were **not executed**, because this pass ran no tests. Their syntax follows the discovery command in section 9.1, and the section says so.

## Examples run (temporary directory, offline)

All ran with `PYTHONPATH=<repo>/src python3 -m odooflux knowledge ...` from a temporary directory, not from the repository root (the repository root holds `odooflux.py`, which shadows the package for `python -c`).

- **Manual rule (README 11.3).** `rule create`, `validate`, `history`, `link-evidence`, `inspect`, `edit`, `disable`, `enable`, `retire`, `promote` (refused with gates 1, 3, 4, 5 and the recorded-approval note). Shapes match. `validate` reported warning A005 (selector overlap with a shipped rule).
- **Build (11.6).** `release build --dry-run` (prints RUN per step, creates no kb-home), a real build (`outcome OK completeness PARTIAL`, exit 0, 2 s), a re-run (REUSE per step), `--from-step 15` (re-runs 15 to 17), a plan missing keys (exit 2), a build on top of an installed parent (`parent_release` set), and a pinned revision that is not in the clone (`SOURCE_REQUIRED_FAILED`, `REVISION_UNAVAILABLE`, exit 4).
- **Lifecycle (11.4).** `release list`, `show`, `audit-verify`, `export`, `package inspect`, `validate`, `list`, `import` (default: refused, exit 3, P10, nothing installed; with `--downgrade-unverified`: installed with a new id), `activate`, `deactivate`, `rollback`, `diff`, and `remove` (ACTIVE refused, exit 1; previous-stack refused, exit 1). Package tamper: byte change gave P04 (exit 3). `--expect-digest` mismatch gave P06 (exit 3). Installed-release tamper gave exit 5 on `activate`.
- **Source (11.5).** `source add`, `list`, `show`, `acquire` (offline, local clone), `verify`, `remove`; `source fetch` without `--allow-network` refused with exit 2. **No `fetch` with the flag was run.**
- **Extract and ledger.** `extract` with snapshot manifest paths (exit 0); `ledger list`, `show`, `set-disposition` (HUMAN_REVIEW and NO_CUSTOM_MODULE_IMPACT), `confirm` (replacement candidate), `verify`, `list --disposition`.
- **Candidates.** `generate` (refused with a confirmed replacement that has no replacement, exit 1; refused with a local `--source` lacking `repository`, exit 2 with a message; success with `repository` added), `list`, `accept`, `reject`, `generate` again (`existing`; the rejected candidate was not revived), and `generate` while a candidate is still PROPOSED (refused, exit 1).
- **Coverage (11.7).** `coverage show --release` and `coverage gates --release`. Shapes match: eight metric lines, a gate table, the completeness decision and limits.
- **AI (11.5, 12.12).** `ai propose` without `--ai` (exit 2). With `--ai` and the kill switch (exit 1, nothing sent). With `--ai --ai-provider fake` and no grant (exit 1, `AI denied: no grant for evidence_excerpt`). With the grant (exit 0, `AI proposals: 0 stored ...`). The last three ran inside `unshare -rn` (empty network namespace), with the packaged `fake` provider and a script file. No external provider was contacted.
- **Migrate with a release (11.2).** `--require-complete-kb` on a PARTIAL active release (exit 4); a PARTIAL active release without the flag (exit 1 because of the module's own findings; report `schema_version` 1.1.0 with `knowledge_release`); a tampered active release (exit 4, `changed file, sha256 or size differs`); an active pointer whose release directory is missing (exit 4); the built-in default through `ODOOFLUX_KB_HOME` with no `active.json` (report `builtin: true`, schema 1.1.0). A non-existent `--kb-home` path also resolved to the built-in knowledge without an error (see ambiguous behaviours).
- **Coverage and kb-home layout.** `find` on a kb-home confirmed the layout in section 6.11 (`active.json`, `audit.jsonl`, `releases/<id>/` with `knowledge/`, `provenance/sources.json`, `snapshots/`, `coverage/`, `release.json`, `state.json`; `staging/`; `snapshots/objects/`). `.lock` was absent between commands.

## Discrepancies between code and `specs/011-knowledge-acquisition-pipeline/contracts/cli-surface.md`

The code was documented. These are the differences.

1. **`ai propose`.** The contract gives `ai propose [--provider P --grant ...]`. The code has no `--provider` or `--grant`. It needs `--ai`, `--ai-consent-send-code`, `--ai-provider NAME`, `--ai-model ID`, `--ai-budget-job-tokens N`, and grants as `--ai-authorize PROVIDER=CAT[,CAT]` (repeatable).
2. **`release build`.** The contract gives `build [--dry-run] [--from-step N] [--allow-failed]`. The code also requires `--plan FILE` (the contract does not define the plan), and adds `--parent ID`, `--supersede ID` and `--kb-home`. The plan format is defined by `cli/kap_release.py:_read_plan` and is documented in README 11.6.
3. **Common options.** The contract says `--kb-home`, `--json` and `--quiet` are common to all commands. In the code: `rule`, `candidates` and `ai` take `--path` and no `--kb-home`. `--quiet` is absent from all `rule`, `candidates` and `ai` verbs. `--json` is on only some `rule` verbs (`inspect`, `history`) and on all `candidates` verbs and `ai propose`. `coverage` accepts `--kb-home`, which it does not use with `--path`.
4. **Socket rule.** The contract says "No command except `source fetch` may open a socket". `ai propose` with an external provider is designed to send minimised source regions to the provider's endpoint (for example the catalog's `https://api.anthropic.com/v1/messages`), when AI is on, consented and granted. That path is not in the contract's rule. It was not exercised here; the statement comes from the catalog and the gateway design. README 11.5 states the scope of `source fetch` accordingly. The contract should be updated.
5. **Additions not in the contract:** `source acquire --i-am-entitled` (ENTERPRISE_LOCAL); `source fetch --sha256`; `release remove --force-previous`; `extract --blobs`, `--out` (required) and `--scope`; `ledger` verbs require `--ledger FILE`; `ledger set-disposition --actor` (required) and `--rationale`; `ledger confirm --reviewer` (required); `candidates generate --path`, `--ledger`, `--source`, `--checked-on` (required); `coverage show|gates --release` and `--path`.
6. **Exit codes.** The table in the contract matches the code for 0, 1, 2, 3, 4 and 5. The mapping of build stop codes to exit codes (section 10.9) is a code detail that the contract does not give.

## Discrepancies between the brief and the code

- **Fail-closed cases.** The brief says nine. `test_fail_closed_tamper_cases` has **eight** subtests. The docs name the eight and list the related tests separately (section 12.8).
- **`extract`.** The brief lists `extract/ledger` as one group. In the code `extract` is a single top-level verb (`kap_extract.py`), and `ledger` is a group of five verbs.

## Ambiguous behaviours (observed)

1. **Mistyped kb-home runs the built-in knowledge.** A non-existent or mistyped `--kb-home` path has no `active.json`, so `migrate` uses the built-in knowledge with no error. Only the report's `knowledge_release.builtin` shows it. Now documented in README 11.2 and section 6.12.
2. **`extract --blobs` pointing at `objects/`.** Passing the `objects/` directory instead of the blob root gave **exit 0** with 9 FAILED files and all 10 changes UNKNOWN. The root is the directory that contains `objects/sha256/`. The docs say so. The command should fail rather than succeed.
3. **`release show` does not re-hash.** A tampered active release still showed as ACTIVE with `release show` (exit 0). `activate` and `migrate` do check it. Documented.
4. **Downgrade changes the release id.** `package import --downgrade-unverified` installs the release under a new id (the digest changes). Documented in 11.4.
5. **Reviewer defaults to actor.** `ledger set-disposition ... NO_CUSTOM_MODULE_IMPACT` without `--reviewer` was accepted; the reviewer defaults to `--actor`, and only `--rationale` is required. Documented in 11.5.
6. **Confirm before generate.** `ledger confirm` accepted a replacement candidate with no replacement, but `candidates generate` then refused the whole ledger (exit 1). The two verbs disagree about what a valid confirmation is.
7. **Local-source candidates.** `candidates accept` succeeded for a candidate whose evidence then failed the tree check with E002 (URL not on the allow-list) and E003 (revision not in the catalogue). `rule validate` exits 1 after that. Accept's checks do not reject this case. Documented in 7.11.
8. **`release deactivate` with nothing active** exits 0 with a message.
9. **`coverage gates`** exits 0 for PARTIAL and 1 for FAILED or for consistency findings (M8 included, though no gate reads it).
10. **Relative defaults.** `source` commands default `--registry` to `./sources.json`, which depends on the working directory. Stated in the help; noted here.
11. **Re-running a build with the same label** reuses the completed steps and does not create a second release. A new label creates a new release even if the content is identical (the label is part of the digest).
12. **`release diff` of two identical releases** printed `counts={} unchanged=332` and exited 0.
13. **`candidates generate` refuses while candidates are PROPOSED** (exit 1). Accept or reject the pending ones first. A second `generate` after an accept was refused for this reason, which the first draft of this report did not expect.
14. **`candidates generate` error for a missing repository** changed during this pass. Earlier it was a schema error (exit 1); the current code gives exit 2 with a message. The docs describe the current code.

## Changes in the code during this pass

KAP source, test and documentation files were modified during this pass by work outside this task (among them `knowledge/pipeline.py`, `knowledge/release/safety.py`, `cli/kap_candidates.py`, `knowledge/candidates/evidence_builder.py`, and several KAP tests, between about 16:12 and 16:31 local time). The first example run predates some of those changes, so the whole example set was run again in a fresh temporary directory after the last change. The results in this report come from that final run (599 lines of log). They match the first run except for items 13 and 14, which the first run did not exercise or which changed. The docs were then edited to the final behaviour. This pass changed only `README.md`, `docs/TECHNICAL_USAGE.md` and this report in the repository. Python cache files written by running the tool are git-ignored.

## Gaps

Not run, and why:

- `source fetch --allow-network`, and any live fetch: network access is out of scope for this pass.
- `source acquire --i-am-entitled` and any ENTERPRISE_LOCAL source: no enterprise source is available.
- `release build --allow-failed` (development only; not run).
- `release remove --force-previous`; `package export --include-enterprise-derived`; the successful `package import --expect-digest` path (only the refusal was run).
- `rule add-test` and `rule resolve`, `candidates resolve`: shapes taken from `--help`; no fixture or build-dir format was verified.
- `ledger list --class`; `extract --scope`; `rule inspect --strict-builtin` and `rule validate --strict-builtin`.
- `coverage show|gates --path` (the fixture tree has no `inputs.json`, so this mode was not run).
- `ai propose` with an external provider, with `--ai-catalog`, with the budget and timeout options, with `--ai-disable-external` set through the environment variable, and with `--ai-secrets-file`. Only the packaged `fake` provider ran, inside an empty network namespace.
- Build adapters other than `GIT_COMMUNITY`: the constraint comes from `GIT_KINDS` in `cli/kap_release.py`, and was not run with another kind.
- Build exit codes 3 (package check during a build) and 5 (integrity during a build): documented from code, not run.
- Live tests (`ODOOFLUX_KAP_*`), Docker, and any real Odoo corpus: not run.
- Test commands in section 9.5: not executed.
- Mermaid diagrams: reviewed by eye and by a syntax script, not rendered.
- Default kb-home on Windows and on macOS: the XDG and `~/.local/share` default was computed with Python only, on Linux.
- git versions other than 2.43.0, and platforms other than Linux: the git adapter tests ran on git 2.43.0 only.

## Claims deliberately not made

The documents do not state or imply: production readiness or certification; verified migration accuracy; that any real corpus has been built; that live AI, network or Docker paths were exercised; or that the owner decisions OD-K1 to OD-K13 are resolved. The README and TECHNICAL_USAGE state that all of these are pending or not run.
