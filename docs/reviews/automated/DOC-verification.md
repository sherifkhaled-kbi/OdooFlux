# Documentation Verification Report (README.md and docs/TECHNICAL_USAGE.md)

Date: 2026-11-07. Documentation-only round; no production code, KB rule or test was changed. Nothing is committed.

## Result
| Check | Method | Result |
|---|---|---|
| Documented CLI surface | Parsers and `--help` of every command (migrate, plan, rollback, resume, versions, knowledge validate/refresh/matrix, support-statement) | 10 commands (7 top-level plus 3 `knowledge` subcommands), 77 options (1 hidden), counted by the README writer |
| Every `--flag` in the docs exists | Orchestrator script: flags in both documents compared with flags from all `--help` output and parser sources (65 real flags) | README: only `--no-deps`, `--no-index` (pip) and `--version` (documented as absent); TECHNICAL_USAGE: none missing |
| Examples run | README writer re-ran 29 cheap commands incl. a real quick start in a temp dir | 28 matched; the one miss is a real traceback, listed in troubleshooting |
| Relative links | Orchestrator script | README 30 links, TECHNICAL_USAGE 7 links, 0 broken. README writer also checked 96 links and 66 anchors |
| Paths and directories | TECH writer scripted a backtick-path check | All repo paths resolve; remaining flags are placeholders, globs, runtime artifacts |
| Env var names | grep of tests | `ODOOFLUX_BENCH`, `ODOOFLUX_BENCHMARKS` exist; `ODOOFLUX_BENCH_MARKS` does not (earlier session notes wrongly used it; the guide says so) |
| Overclaims | grep for certification wording | Production certification stated as not granted; 0 supported paths; PROVISIONAL label explained |
| Not done (by instruction) | Docker, live AI, full suite | Figures come from the completion report; Mermaid not rendered (checked by eye) |

## Discrepancies and undocumented behaviour (code issues, not fixed here)
- `odooflux plan` crashes with a traceback on out-of-range or backwards versions.
- `rollback` of an unknown run ID, or of a `--no-backup` run, and a missing `--addons-path`, give tracebacks instead of usage errors.
- L3 is not re-checked after deterministic fixes (AI path only).
- `--ai-fix` implies `--fix`; `--ai-provider-type` is not enforced.
- Default legacy exit code is 0 for NEEDS_REVIEW and for L3-unavailable (register AR-R4-4).
- L4/L5 runtime validation, the RNG layer and JS L1 are not wired into `migrate`.
- Planner does not block `RESEARCH_SEEDED` steps; some `FIX_ENABLED` rules cite evidence marked review-only.
- `tests/README` omits `-t .`.
- Full lists: appendices A and B below.

## Coverage gaps
Only Linux and Python 3.12.3 verified. Resume of a truly interrupted run untested. Live AI providers and Docker runs not exercised. Spec `plan.md` files were not re-read (intent from ADRs and docstrings). `tools/verify_evidence.py` not run with arguments.

## Appendix A: README writer notes (verbatim)
# OdooFlux README pass: spec-vs-runtime discrepancies, ambiguities, gaps

Scope: README.md only was edited. All items below were observed in this environment (Linux, Python 3.12.3, version 0.2.0)
unless marked "code reading". Nothing here was fixed in code.

## Defects reproduced (exit codes are real)
1. `plan --from 18 --to 17` -> uncaught UnsupportedVersionError traceback, exit 1. `cli/main.py` only wraps `ctx.graph()`;
   `cli/commands.py::cmd_plan` -> `build_plan` -> `graph.steps` is unguarded. `plan --from 17 --to 20` behaves the same
   ("20.0 is not in the registry"). `migrate` handles both cleanly (exit 2).
2. `plan --module /does/not/exist` prints READY and lists the module; `migrate --module` on the same path exits 4
   ("Not a valid directory"). `plan` does not validate paths.
3. `migrate --addons-path <missing dir>` -> FileNotFoundError traceback, exit 1 (`discovery/modules.py` iterdir unguarded).
   An existing empty folder correctly gives exit 4.
4. `rollback <unknown-id>` -> FileNotFoundError traceback, exit 1 (`core/jobs/state_dir.py::RunDir.open`). `resume <unknown-id>`
   prints a clean `ERROR:` line and exits 4.
5. `rollback` of a `--no-backup` run -> FileNotFoundError traceback on `backup/...`, exit 1. Run state has reversible=false
   and the CLI says "not reversible"; rollback should refuse with a message.
6. `--api-key` deprecation warning is printed twice (`cli/main.py::run` and `cli/migrate.py::run_migrate`).
7. `knowledge validate --path /nonexistent` -> `records=0 rules=0 errors=0`, exit 0 (silent pass).
8. `resume <completed-run>` exits 0 with no output. Unclear whether intended.
9. Discovery records an INFO `NO_MANIFEST` finding for manifest-less children of --addons-path (`discovery/modules.py`), but
   `cli/migrate.py` discards the `findings` list, so the skip is silent. Docstring says "skipped with an INFO finding".
10. `report.recovery.rollback_cmd` = `odooflux rollback <id>` without `--state-dir` (wrong when a non-default state dir was used).
11. Default terminal output (no `--ui`) does not show the PROVISIONAL label; only `--ui`, JSON, SARIF and HTML do.
12. `--dry-run` without `--fix` is treated as analysis, but `run_migrate` still prints `Mode : DRY RUN` (code reading).
13. `odooflux` with no arguments runs `migrate` and fails with a usage error (exit 2), not help (verified).

## Spec-vs-runtime gaps (need owner decision)
14. **L3 is not re-checked after deterministic fixes.** `core/orchestrator/run.py::_process_module` calls `layer3_for` (line
    ~170) on the module before edits are staged/promoted, and no L3 pass runs on the promoted files. Only the AI path has an
    L3 regression check (`ai/integration.py::_layer3_regression`). `ai/integration.py` docstring says "validation (L1, L2
    re-scan, L3)" for AI edits. README states this explicitly.
15. **`--ai-fix` implies write mode.** `cli/migrate.py` sets `args.fix = True` when `--ai-fix` is given without `--fix`
    (prints a WARNING). Not in the help text.
16. `--ai-fix` checks the API key before the kill switch (both exit 2). Ordering only.
17. `ai/providers/legacy_anthropic.py` hard-codes a model constant (`claude-sonnet-4-6`), contradicting the catalog's own
    comment ("No model id or price is in code"). Legacy path is outside the catalog and `--ai-authorize` grants.
18. `--ai-provider-type` is stored in config but never enforced: `ai/gateway.py` and `ai/authorization.py` use the catalog
    entry's `type`.
19. Exit mapping: default legacy exit is 0 for a module in NEEDS_REVIEW, and 0 for L3 UNAVAILABLE when `--fail-on none`
    (verified). Only `--exit-codes v1` maps BLOCKED to 4. Documented as D-10 "one minor release"; a release-gate hazard.
20. `versions` SUPPORT column shows UNSUPPORTED for all 8 versions, while the support statement classifies 16 paths as
    `experimental`. Different concepts with similar wording.
21. `--allow-unverified` currently has no effect on the plan (all 28 registry pairs are READY) but still adds
    `unverified_plan` to every module's status reasons (verified).
22. Stale docstring: `validation/__init__.py` says L3 is "unavailable in P2". L3 is wired (`builtins._layer3`) and runs.
23. Extras: `js`, `xml`, `rng` do not change CLI output (verified with identical findings). The JS syntax validator is not
    registered in `builtins.py`; `validation/static/rng.py::validate_views` is not called from the CLI. `rich` and `ai` and
    `runtime` extras are empty. `pip install .[rich]` installs nothing; `--ui rich` needs `pip install rich`.
24. Runtime (L4/L5): `validation/runtime/*` and `validation/behavioral/*` are imported only by each other and by tests. No CLI
    or orchestrator path calls them. Docker is therefore never used by the CLI.
25. `--ai-verbose` and `--ai-fix` have no help text (verified in `--help`).
26. `--report-format legacy-json` output is byte-size identical to the default `legacy` (likely an alias; low priority).
27. Running `python -c "import odooflux..."` from the repo root imports the launcher `odooflux.py` instead of the package
    (dev gotcha; `python -m` and the launcher are fine).
28. `docs/TECHNICAL_USAGE.md` did not exist when the README was written (linked anyway, as instructed).

## Not verified (gaps)
- Runtime L4/L5 never run (no Docker, not wired). No live AI call was made (by instruction). Legacy `--ai-fix` never executed.
- `resume` of a truly interrupted run was not exercised (no interrupted run created); only the rolled-back refusal was.
- Exit code 3 (rejected edits in write mode) and the v1 "rejected" path were not reproduced.
- `--incremental` invalidation after a file change was not tested (only skip on unchanged files).
- `--ui rich` with `rich` installed was not run in the venv (only the fallback notice was).
- HTML and SARIF were checked for shape and the PROVISIONAL label, not against their external schemas.
- `knowledge refresh` (needs local clones) and `knowledge matrix` write mode were not run; only `--check` and the read-only default.
- `support-statement` was run with `--check` and with `--out` to a temp file only; the committed file was not regenerated.
- Python versions other than 3.12.3 and operating systems other than Linux: not verified.
- Wheel built with default build isolation (downloads setuptools); `--no-build-isolation` not tried.
- `pip install -e .` and the `[js,xml]` extras were tested in a copy of the tree, not in the checkout.
- Individual rules were not reviewed for correctness; the README describes only the observed behaviour of the sample module.

## Verification record
- `/tmp/docgt/verify.sh` re-ran 29 cheap README commands in a fresh temp dir with the wheel-installed binary: 28 matched the
  README; the one mismatch was the nonexistent-addons-path traceback (item 3), which is now in the troubleshooting section.
- Relative links: 96 checked, 0 missing. Anchors: 66 checked, 0 missing. Mermaid: 16 nodes, 15 edges, all references defined.
- Option inventory generated from argparse: 10 commands (7 top-level + 3 knowledge subcommands), 77 options (flags and option
  arguments, excluding -h and positional run IDs), 1 hidden (`resume --api-key`).

## Appendix B: technical guide writer notes (verbatim)
# Technical notes: discrepancies and observations (not part of the guide)

Date: 2026-11-07. Scope: docs/TECHNICAL_USAGE.md. Each item states what was checked. No code or KB data was changed.

## Discrepancies between specs or docs and code

1. **FIX_ENABLED rules cite evidence that says `review-only`.** `src/odooflux/knowledge/compatibility/12-13.rules.json` has `12-13.python.api-multi-removed` at `FIX_ENABLED` (fixer `remove_decorator`) citing `EV-101`. `EV-101.json` has `proposed_transformation: "review-only"` and `status: DOCUMENTED_NOT_TESTED`. `15-16.python.search-args-keyword` (FIX_ENABLED) cites `EV-013`, whose `proposed_transformation` is also `review-only`. Not checked: the other eight FIX_ENABLED rules. Owner should confirm whether the evidence or the maturity is wrong.

2. **Evidence `rule_ids` are not maintained.** `EV-013` and `EV-101` have `rule_ids: []` although rules cite them. The schema allows an empty array, so `knowledge validate` does not flag it. Reverse links are absent for the records checked.

3. **Planner does not block `RESEARCH_SEEDED` steps.** `versions/graph/graph.py` `unresearched` is `research_status == "NOT_ASSESSED"` only (`core/contracts/records.py`). All seven transitions are `RESEARCH_SEEDED` in `compatibility/versions.json`, so `plan --from 17.0 --to 18.0` and `plan --from 12.0 --to 13.0` return READY without `--allow-unverified` (both observed). The completion report and register say 17.0 to 18.0 results are PROVISIONAL pending T025 review. Not checked: the exact planner wording in spec 006 (did not read the plan.md files). Decide whether `RESEARCH_SEEDED` should block.

4. **Runtime L4/L5 is not reachable from `migrate`.** `validation/runtime/pipeline.py` (`run_install`, `run_behavior`) and `validation/behavioral/compare.py` have no call sites outside `tests/`. `builtins.py` registers no `runtimes` entry. ADR-011 and spec 008 describe runtime validation as a layer of the pipeline. The completion report describes an end-to-end run without saying L4/L5 is excluded. The guide labels this "Implemented, not wired".

5. **RELAX NG view validation is not registered.** `validation/static/rng.py` `validate_views` is referenced only by `tests/unit/validation/test_rng.py`. REQ-XML-004 (per module docstring) implies it is part of L2. Not registered in `build_context()`.

6. **JavaScript L1 validator is not registered.** `validation/syntax/javascript.py` has no registration in `builtins.py`. JavaScript rules are detect-only through the stdlib lexer. ADR-006 and REQ-JS-004 (per docstring) imply an L1 check.

7. **`tests/README.md` discovery command omits `-t .`.** The README shows `python -m unittest discover -s tests -p "test_*.py" -v`. Verified: `discover -s tests/unit/knowledge` without `-t .` gives 14 tests with 8 errors; with `-t .` it gives 75 tests OK.

8. **Exit-code default.** `cli/migrate.py` `compute_exit_code` (legacy) returns 0 for a manifest-less module with no open finding; `exit_codes.exit_code` (v1) returns 4 for BLOCKED. The register (AR-R4-4, WSD-04) records this as an owner decision. Not a code bug; documented.

9. **Version support vs path support.** `odooflux versions` shows every version `UNSUPPORTED`, while `docs/planning/SUPPORT_STATEMENT.md` lists 16 experimental paths. These are different levels (version status vs path status). Not a contradiction, but the two are easy to confuse. Guide explains both.

10. **Support statement vs rule maturity.** `SUPPORT_STATEMENT.md` says step 12-13 "rules are NOT_ASSESSED" for 12.0 to 13.0 (experimental), while `12-13.rules.json` contains a FIX_ENABLED rule. Possible wording issue in the statement ("rules" may mean research status); not verified against the matrix generator.

## Defects observed (code)

11. **`rollback` with an unknown run ID raises a traceback.** `odooflux rollback nosuchrun --state-dir DIR` ends in `FileNotFoundError` from `core/jobs/state_dir.py` (`RunDir.open`), exit 1. `cli/commands.py` `cmd_rollback` does not catch it. A usage message with exit 2 is more consistent with other commands. Spec contract not read; the expectation is inferred.

12. **Rename rollback unlinks before writing.** `core/recovery/rollback.py` lines near `if entry.get("renamed_from") and path != source: path.unlink()` followed by `atomic_write_bytes(source, original)`. A failure between the two loses the renamed file. Already in the completion report (AR-R5-1). Confirmed in code. `core/jobs/promote.py` also unlinks the source after writing the destination (line near `os.unlink(edit.path)`).

13. **`tools/verify_evidence.py` with no arguments prints `FAILURES 0`.** It checks nothing and exits 0. Verified by running it with no arguments. Misleading output; the guide warns about it. Suggest a usage message and non-zero exit.

14. **Two redaction modules.** `utils/redact.py` ("secret redaction for log and report text") and `utils/redaction.py` ("redaction and canary scanning") overlap. Not a bug; a maintenance hazard. Not changed.

15. **Brief error (not a code issue).** The brief named `ODOOFLUX_BENCH_MARKS`. No such variable exists. The benchmark switches are `ODOOFLUX_BENCH` (timed benchmarks) and `ODOOFLUX_BENCHMARKS` (end-to-end run). The guide uses the real names.

## Not verified (gaps in this pass)

- The full test suite was not run (instruction). Figures (1734 tests, 34 opt-in skips) are taken from FRAMEWORK_COMPLETION_REPORT.md.
- Spec `plan.md` files were not read beyond their existence; spec intent is taken from ADR text, module docstrings, and contract filenames. Statements about intent are marked as such.
- `tools/verify_evidence.py` was not run with arguments (needs network).
- Live AI providers were not called; no key was used. Catalog endpoints are as declared in `providers.json` and flagged there as unverified.
- Docker runtime tests were not run.
- Rule `detector_ref` resolution at load time was not traced end to end.
- Some tool output in this session was shortened by an output-compression layer. Facts that mattered were re-checked with narrower commands.
- Mermaid diagrams were checked for balanced brackets and module names only; they were not rendered.
