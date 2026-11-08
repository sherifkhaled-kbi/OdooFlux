# Validation and Test Strategy

How OdooFlux proves results (OBJ-009) and how OdooFlux itself is tested (Principle V). The
runtime and behavioural layers are delivered in P7
([specs/008-runtime-behavioral-validation](../../specs/008-runtime-behavioral-validation/)).
The status decision is the normative contract
[status-decision.md](../../specs/008-runtime-behavioral-validation/contracts/status-decision.md).

## Validation layers

Each validator returns `PASS`, `FAIL`, `UNAVAILABLE`, or `SKIPPED` with a reason
([CONTRACTS.md § Validator](architecture/CONTRACTS.md#validator)). `UNAVAILABLE` and `SKIPPED` are
never `PASS`. L1–L3 are mandatory; L4–L5 are opt-in (`--validate runtime|behavior`) unless made
mandatory with `--require`.

### Layer 1 — Syntax validation (mandatory, before any promotion)

| File kind | Validator | Adapter |
|---|---|---|
| Python | `ast.parse` with the tool interpreter (REQ-PY-004) | stdlib |
| XML (views, data, QWeb) | well-formedness via expat/ElementTree | stdlib |
| Manifest | `ast.literal_eval` → must be a dict | stdlib |
| JavaScript | parse with the JS adapter (ADR-006) | optional; else `UNAVAILABLE` → `NEEDS_REVIEW` when JS files changed or have findings |
| CSV (ACL) | `csv` parse, header columns | stdlib |

An edit whose result fails L1 is `REJECTED` and never written (REQ-SAF-002).

### Layer 2 — Static compatibility (mandatory)

- **Re-scan.** All target-step rules run against the validated workspace content. Findings
  absent after re-scan become `FIXED` (REQ-TRF-005); findings still present stay open.
- **View RNG.** Modified view archs are validated against the target version's RNG files when
  the optional `lxml` adapter is present (REQ-XML-004; files per version: EV-302). Otherwise
  this sub-check is `UNAVAILABLE` and is recorded in the verification scope. It does not change the
  status unless the user passed `--require rng`, in which case row 1 of the status table applies
  (`BLOCKED`).
- **Deprecated-construct scan.** OWL, assets, and QWeb rules are covered by the rule catalogue (P5).

### Layer 3 — Dependency integrity (mandatory)

Checks, using scanned modules plus target-version knowledge data:
- `depends` modules exist (core list per version, or scanned custom);
- models referenced by `_inherit`, ACL rows, record rules, and views exist;
- fields used in views, domains, and ACL-related data exist;
- XML IDs referenced by `ref`, `inherit_id`, and menus resolve;
- groups resolve;
- `external_dependencies` Python packages are declared.

If the core-module list for the target version is not in the knowledge base, L3 is `UNAVAILABLE`
(REQ-VAL-003, REQ-DEP-003).

### Layer 4 — Runtime validation (opt-in)

Design per [ADR-011](ARCHITECTURE_DECISIONS.md#adr-011--runtime-validation-in-disposable-containers)
and [runtime-environment.md](../../specs/008-runtime-behavioral-validation/contracts/runtime-environment.md):

- **Environment.** Disposable PostgreSQL and Odoo containers for the target version. The image
  must be allow-listed and digest-pinned; provenance is still to be researched (EV-301, G-R-13,
  G-R-21).
- **Isolation.** The module copy is mounted read-only plus a scratch volume. No host network.
  CPU, memory, pids, and wall-time limits. Not privileged. Every resource carries a run-ID label,
  and teardown is guaranteed.
- **Install.** Fresh database, `-i <modules in dependency order> --stop-after-init` (options:
  EV-303). Optional upgrade check with `-u … --stop-after-init`.
- **Checks derived from logs.** Python import and registry initialisation, model setup, view
  loading and validation, data and ACL loading, asset compilation (when assets are requested in
  a check), and missing Python dependencies.
- **Log analysis.** Classify lines into `import_error`, `registry`, `view_validation`,
  `access_rights`, `data_load`, `asset_compile`, `missing_python_dependency`, `timeout`, `oom`,
  and `unknown`. Patterns are data per version, researched from official source (G-R-22).
- **Intermediate versions.** Validated only with `--validate-intermediate` (ADR-007).

### Layer 5 — Behavioural validation

- **Source baseline.** Run the module's own tests on the source version (needs a source image;
  G-R-21).
- **Target regression.** Run the same tests on the target version with `--test-enable` and
  `--test-tags` (EV-303).
- **Comparison.** Each test is classified `pass_both`, `regression`, `fixed`, `fail_both`,
  `target_only`, or `source_only`. L5 = `PASS` if ≥1 test ran and there are zero regressions;
  `coverage = full` only when the baseline ran.
- **Contract tests.** Optional user-provided scenario tests (tags) for critical flows.
- **Golden fixtures.** OdooFlux's own behavioural fixture (one pass, one regression, one
  pre-existing failure) proves the comparison logic.
- **Security and data-integrity tests.** ACL and record-rule checks via access-test scenarios
  where the module provides them. Data-integrity checks are limited to install-time constraint
  errors (no customer data is migrated).

What **can** be automated: syntax, rule re-scan, reference integrity, install and upgrade on a
fresh database, the module's own tests, and comparison of test outcomes.

What **cannot** be automated, and is always stated in the report's verification scope:
- correctness of business behaviour not covered by tests;
- behaviour on real customer data or data-migration effects;
- Enterprise-dependent modules without Enterprise access (D-05);
- UI behaviour beyond what tests exercise;
- integrations with external systems;
- performance on production data volumes.

These require **manual review**. The report lists every `review_required` finding as a review
checklist.

### Layer 6 — Final acceptance

The status decision below combines layers L1–L5, findings, plan state, and tool state into one
module status, plus `status_reasons[]` and a verification-scope statement (REQ-BIZ-003).

## Result statuses

Consistent with the summary in [TARGET_ARCHITECTURE.md § 4.4](TARGET_ARCHITECTURE.md#44-status-decision);
this table is normative. Evaluate top to bottom; **the first matching row wins**.

| # | Status | Exact condition |
|---|---|---|
| 1 | `BLOCKED` | Plan refused (unsupported or unresearched step without `--allow-unverified`), **or** tool state not ok (backup failed or unverifiable, workspace or promotion failure, internal error), **or** any layer listed in `--require` is `UNAVAILABLE`/`SKIPPED` |
| 2 | `FAILED` | Any layer that ran returned `FAIL`, **or** ≥1 open CRITICAL finding after fixes and re-scan |
| 3 | `NEEDS_REVIEW` | ≥1 open `review_required` finding, **or** ≥1 open WARNING, **or** the plan ran with `--allow-unverified`, **or** a mandatory sub-validator for a file kind present in the module is `UNAVAILABLE` (e.g., JS adapter missing while JS files have findings or edits) |
| 4 | `VERIFIED_SUCCESS` | L1, L2, L3, L4 = `PASS` **and** L5 = `PASS` with `coverage = full` |
| 5 | `INSTALL_VERIFIED` | L1–L4 = `PASS`; L5 `SKIPPED`, `UNAVAILABLE`, or `PASS` with `coverage = partial` |
| 6 | `STATIC_VALIDATED` | L1–L3 = `PASS`; L4 `SKIPPED` or `UNAVAILABLE` |
| 7 | `NEEDS_REVIEW` | Fallback for any unmatched combination, with `status_reason = unmatched_combination`; tests assert this never occurs for valid inputs |

INFO findings never affect status. Rejected edits leave their findings open, and those findings
count in rows 2–3.

## Test strategy for OdooFlux itself

### Test pyramid

| Level | Scope | Location | Runs by default |
|---|---|---|---|
| Unit | Pure functions: rules, span locators, converters, status table, renderers, budgets | `tests/unit/` | yes |
| Contract | Every plugin kind against its contract | `tests/contract/` | yes (live AI providers opt-in) |
| Golden | Fixture modules per source version → expected outputs and reports, byte-exact | `tests/golden_fixtures/` (+ drivers in `tests/integration/`) | yes |
| Integration | CLI and pipeline end to end on fixtures, safety hashes, determinism | `tests/integration/` | yes |
| Regression | One test per resolved finding `F-…` (REQ-TST-005) | `tests/regression/` | yes |
| Runtime | Container install, upgrade, behaviour | `tests/runtime/` | only with `ODOOFLUX_RUNTIME_TESTS=1` |
| AI live | Real providers | `tests/contract/ai/` | only with `ODOOFLUX_AI_TESTS=1` |
| Benchmarks | Performance budgets | `tests/benchmarks/` | only with `ODOOFLUX_BENCHMARKS=1` |

The command is `python -m unittest discover -s tests` (ADR-016). Runs fully offline by default
(REQ-TST-006).

### Fixture strategy

- **Golden modules.** One per source version in scope. Each contains every construct the rules
  for its steps target, plus must-not-match decoys. Expected output tree and expected report
  JSON are stored next to it.
- **Audit reproduction fixture.** `kbi_demo` from Appendix A of the audit becomes the first
  regression fixture (P0/P1).
- **Corpus fixtures.** For converters, e.g. the attrs/domain expression corpus with operators
  `= != in not in < > <= >= | & !` and nesting.
- **Runtime fixtures.** `install_ok`, `broken_view`, `install_loop`, `acl_missing_model`,
  `behavior_compare`, and `enterprise_dep` (P7).
- Fixtures contain no customer code. Synthetic corpora are generated with seeds (P9).

### Rule test obligations

For each rule there are three tests, enforced by a registry coverage test (REQ-TST-002):
- positive (detects; fix result equals expected);
- negative (no finding on a decoy);
- idempotence (fix applied twice equals fix applied once).

### Failure-injection plan

| Injection point | Fault | Expected outcome | Phase |
|---|---|---|---|
| Fixer output | Invalid Python/XML/manifest | Edit rejected; no write | P0 |
| Backup copy | Exception / partial copy | Module `BLOCKED`; zero writes | P0 |
| Backup verify | Checksum mismatch | Module `BLOCKED`; zero writes | P0 |
| Atomic write | Kill after temp write, before replace | Target unchanged | P0 |
| Atomic write | Disk full | Target unchanged; `BLOCKED` | P0, P9 |
| Promotion | Kill mid-module | Rollback restores originals; resume completes | P2, P9 |
| Checkpoint | Corrupt checkpoint file | Resume refuses with a clear error; rollback still works | P2, P9 |
| Rollback | Missing backup file | Rollback stops and reports the files it could not restore | P2, P9 |
| AI | Truncated / malicious / schema-invalid response | Rejected with reason | P6 |
| Runtime | Timeout, OOM, daemon unavailable, teardown failure | `FAILED`/`UNAVAILABLE`; no leftover resources (or cleanup command printed) | P7, P9 |
| Parallel worker | Worker crash | Its modules `BLOCKED`; other modules unaffected | P9 |

### Determinism

Two runs on the same input and configuration give byte-identical JSON reports, excluding timing
and run-ID fields (REQ-ARC-005). This is tested in P2 and re-checked for parallel runs in P9.
