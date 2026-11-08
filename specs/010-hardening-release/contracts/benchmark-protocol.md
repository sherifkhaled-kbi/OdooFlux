# Contract: Benchmark Protocol

- **Corpus**: `tests/benchmarks/corpus_gen.py --seed 1 --modules 300 --files-per-module 30` generates the corpus deterministically from golden-fixture templates (Python, views, data, JS, manifest, ACL). The generator and seed are committed.
- **Reference machine profile**: recorded in `tests/benchmarks/REFERENCE_MACHINE.md` during P2: CPU model, cores, RAM, storage, OS, Python version.
- **Modes**: `serial` (`--jobs 1`), `parallel` (`--jobs <cores>`), `incremental` (second run, unchanged corpus). Each mode runs 5 times; the median is reported.
- **Metrics**: wall time (s), peak RSS per worker (MiB), files parsed, report digest (sha256 excluding timing fields).
- **Budgets**: `tests/benchmarks/budgets.json` = P2 baseline median × agreed headroom factor (recorded with rationale and approver). CI fails if a median exceeds its budget or regresses more than 20 % against the stored baseline.
- **Output**: `tests/benchmarks/results/<date>-<sha>.json`. Results are never committed with customer data.
