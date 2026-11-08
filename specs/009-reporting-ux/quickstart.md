# Quickstart: Reporting and UX (validation scenarios)

Planned commands (not implemented).

1. `python -m unittest tests.unit.reporting` → snapshot, escaping, exit-code tests pass offline.
2. `odooflux migrate … --dry-run --report out.json --sarif out.sarif --html out.html --diff out.patch` on a golden fixture → all files written outside the module; JSON and SARIF validate.
3. `cd <fixture-parent-copy> && patch -p1 < out.patch` → result byte-identical to the expected promoted output.
4. `NO_COLOR=1 odooflux …` → no ANSI sequences.
5. `odooflux … --fail-on warning; echo $?` → 1 when an open WARNING exists.

## Results (T026, recorded 2026-11-07, Linux, Python 3.12.3, `PYTHONPATH=src`)

Fixture: `tests/golden_fixtures/p0_kbi_demo_v14` (copied outside the repo). Commands used the real launcher `odooflux.py`.

| # | Scenario | Result |
|---|---|---|
| 1 | `python3 -m unittest discover -s tests/unit/reporting -t .` and `tests.unit.cli.test_exit_codes` | PASS offline (104 and 15 tests; the optional rich test is skipped when `rich` is absent) |
| 2 | `--fix --dry-run --report out/r.json --report-format json --sarif --html --diff` | PASS: JSON, SARIF, HTML and the diff are written outside the module (validated by the unit/integration suites). Since the WSD-05 follow-up a dry run computes the same edits in memory (`RunOptions.computes_edits`; writes stay fix-only): 4 files, 3966-byte patch, module tree unchanged (`diff -r` against a pristine copy). `analyze` still computes no edits; the CLI prints a note only there. |
| 3 | `patch -p1` of the exported diff against a pristine copy | PASS from the dry-run diff: `cmp` shows it byte-identical to the `--fix --diff` patch, and `diff -r` shows the patched copy IDENTICAL to the write-mode module. Automated in `tests/integration/reporting/test_dry_run_diff.py` and `test_diff_apply.py` (also CRLF, no-final-newline and rename cases). |
| 4 | `NO_COLOR=1 odooflux ... --ui ansi` | PASS: 0 ANSI escape sequences in the output; `MODULE RESULTS` present |
| 5 | `--fail-on warning; echo $?` on a module with an open WARNING | PASS: exit 1 (and 0 for `--fail-on critical`). This is the legacy mapping, the default for this release; `--exit-codes v1` gives the documented table. |

Not run: any real-terminal or CI-UI check (SARIF upload, terminal emulators). Those are human items in `docs/reviews/fragments/ws-d-human-review.md`.
