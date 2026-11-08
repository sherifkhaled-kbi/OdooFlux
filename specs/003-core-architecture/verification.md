# Verification evidence: Core Architecture (P2)

Run from the repository root, Python 3.12, Linux. Commands are reproducible as written.

## Suite

```
$ python -m unittest discover -s tests -p "test_*.py"
Ran 137 tests in 3.7s
OK (skipped=1)            # skipped: ODOOFLUX_BENCH benchmark (opt-in)
```

Per suite: `regression/` (P0, 37 tests), `unit/` (72), `integration/` (19), `contract/` (7),
`benchmarks/` (2: generator test; the timed test is opt-in and skipped by default).

P0 regression suite against the cut-over CLI: `OK` (37 of 37). Changes to the P0 tests were limited
to import paths and patch targets, plus one intended difference (D1: analyze and dry-run create
`state.json` and `log/`).

Clean install: `pip install -e .` in a fresh venv installs no third-party package
(`importlib.metadata.requires("odooflux") == None`), and `odooflux --help` runs (T001).

## Success criteria

| SC | Evidence | Status |
|---|---|---|
| SC-001 | P0 suite passes against the cut-over CLI (37/37). The 8 intended differences in `docs/changes/P2_CUTOVER.md` are each observed (`test_cutover_differences`). **The P1 characterisation suite (spec 002) is not built**, so this criterion is evidenced against the P0 suite only. | Partial |
| SC-002 | `test_all_28_pairs_give_consecutive_steps`; synthetic 20.0 plans 19.0→20.0 with no code change (`test_synthetic_version`, `test_adding_version_procedure`) | Met |
| SC-003 | `test_rollback_restores_bytes` (byte-identical on the golden fixture, including the manifest rename). Only one golden fixture exists in the repository. | Met for one fixture |
| SC-004 | `test_resume_equals_uninterrupted_at_each_boundary`: interruption after modules 1 and 2 of a 3-module run. The three modules are copies of one fixture. | Met for that set |
| SC-005 | `test_determinism`: two analysis runs equal; two fix runs equal after normalising the root path. Schema v1 validates (`test_report_model`). | Met |
| SC-006 | `test_every_kind_registers` loads one sample per kind (7). Effects visible in the report: rule finding, validator rejection, renderer output, version listing. Parser, runtime and AI-provider samples are registered and looked up; they have no visible effect in P2 by design. Contract mismatch rejected for every kind (`test_plugin_contract_mismatch`). | Met (with the note above) |
| SC-007 | `tests/benchmarks/BASELINE.md`: 300 modules, 9 000 files. Analysis 1.07–1.10 s (legacy 0.69 s); fix 16.7 s (legacy 7.2 s with backup). | Recorded |

## Performance goal (plan.md: at most 20 % slower than legacy on the P1 fixtures)

- Single-module fixture (Appendix A), average of 10 runs: P2 89 ms, legacy 80 ms (+11 %). **Met.**
- 300-module analysis: +55 %. The 300-module figure is a baseline, not the P1 fixture goal; P9 sets
  the budget. Not met for that workload, and recorded as such.

## Quickstart (spec quickstart, against the fixture that exists)

The spec quickstart names `tests/golden_fixtures/v14_kbi_demo`, which does not exist. The same steps
ran on `tests/golden_fixtures/p0_kbi_demo_v14`:

```
$ python odooflux.py plan --from 14.0 --to 19.0 --addons-path tests/golden_fixtures/p0_kbi_demo_v14/..
Plan 14.0 -> 19.0: READY  (five steps, all RESEARCH_SEEDED)
$ python odooflux.py --module $T/kbi_demo --from-version 14 --to-version 19 --fix --backup \
      --state-dir $S --report-format json --report $S/r.json          # exit 1 (legacy criticals remain)
$ python odooflux.py rollback $RUN --state-dir $S
Rollback of <run>: 3 restored, 0 conflict(s)
$ diff -r $T/kbi_demo tests/golden_fixtures/p0_kbi_demo_v14 && echo ROLLBACK-OK
ROLLBACK-OK
report schema errors: []
```

`ODOOFLUX_BENCH=1 python -m unittest tests.benchmarks.bench_analyze` in the quickstart does not
match this repository layout. The benchmark runs as `tests/benchmarks/test_bench_opt_in.py`.

## Deviations from the spec (decided during implementation)

| Spec says | Implemented | Why |
|---|---|---|
| Promotion failure → module `FAILED` (US3, TST-031) | `BLOCKED` | The normative status table (row 1) lists promotion failure under BLOCKED. P0 already reported write failures as BLOCKED. |
| Mandatory layer L3 unavailable → status not stated | `NEEDS_REVIEW` in report v1; exit code unchanged | Keeps P0 exit codes. The exit code still depends only on open findings at `--fail-on`. |
| `odooflux.cli.main:main` is the console script | `odooflux.builtins:main` (composition root) | The CLI may not import adapters (import rule). |
| `cli/commands/{migrate,plan,…}.py` | `cli/main.py`, `cli/migrate.py`, `cli/commands.py` | Fewer files; the structure test checks top-level directories only. |
| `core/recovery/checkpoint.py`, `core/jobs/{state_dir,workspace,promote}.py` | Checkpointing lives in `RunDir` (`state_dir.py`) | One owner for run-directory I/O. |
| R-08: sort and hash finding IDs | Implemented in `Finding.id` and `finding_id` | — |
| Span-level edits (FR-009) | The engine implements `diff_to_edits` and `apply_edits` (tested). The pipeline writes whole-file outputs and records the spans in state. | Fine spans come in P4 (spec clarification). |
| Uncertain rescan matches stay OPEN (R-04 / FR-016) | Closest-line pairing per rule; one finding accounts for one fixed finding | Keeps the P0 count rule (report fixed count equals rescan delta). |

## Not done

- P1 characterisation suite (spec 002, 28 tasks, 0 done). Its entry is a precondition in the roadmap.
- D-01 and D-09 were not approved by the maintainer. This work treats D-01 as applied (the constitution
  text already exists) and D-09 as approved by the request to implement P2.
- Parallel execution (P9). AI provider beyond the wrapped legacy call (P6).
