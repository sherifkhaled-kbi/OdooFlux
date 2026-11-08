# Profile summary (T014, REQ-PRF-001, REQ-PRF-004), 2026-11-07

Reference machine: see `../REFERENCE_MACHINE.md`. Command: `bench_analyze.py` (analysis only, `--from-version 14`).

| Corpus | Before | After |
|---|---|---|
| P2 `generate_repo.py` corpus, 300 modules (seed 20260106) | 10.9 s | 6.8 s (RSS 53 to 59 MiB) |
| P9 `corpus_gen.py` corpus, 300 x 30 (seed 1) | 21.5 s | 13.3 s (RSS 141 to 148 MiB) |

The P2 baseline (1.07 s, `BASELINE.md`) predates the knowledge rules wired in the planner; analysis is still about
6 times slower than that figure on the same corpus. The remaining cost is real rule work (23 knowledge rules over every
file), XML parsing, and report rendering (`json.dumps(indent=2)` runs in pure Python). Parallel mode (12 workers) takes
3.8 s on the P9 corpus; an unchanged incremental re-run takes 2.5 s and parses 0 files.

## Hot spots found (cProfile, P9 corpus) and what changed

1. `parsers/python/document.py::_token_offset`: 650 000 calls, scanned each line character by character. Replaced by
   precomputed line content ends; token spans are now built only when `PythonDocument.tokens` is read.
2. `ast.walk` repeated by eight callers on the same tree (1.9 million node visits). `utils/astnodes.py` caches the node
   list and a per-type bucket on the tree, and memoises `ast.parse` by source text so the rules, the L3 integrity check
   and the risk inventory share one tree.
3. `Names(tree)` (import bindings) rebuilt for each of 63 000 rule calls: cached per parsed document.
4. `KnowledgeRule.detect` built an engine `Document` per rule and file (200 700 times): one shared Document per file.
5. `file_kind` called 938 700 times: memoised.
6. JavaScript lexer ran five times per file: memoised by text.
7. Incremental index: `os.walk` hashing instead of `pathlib`, no deep copy on lookup, no rewrite when nothing changed.

Equivalence is pinned by `tests/integration/hardening/test_hotpath_equivalence.py` (token spans against the old algorithm,
node buckets against a filter, work counters) and by the existing suite.

## Not optimised (open for the owner)

- `JsonRenderer` uses `indent=2`, which disables the C encoder (about 2 s of a 300-module run with `--report-format json`).
  Changing it needs a byte-identical output proof.
- Peak RSS is about 400 MiB with `--report-format json` for 300 modules (the report model is built in memory).
