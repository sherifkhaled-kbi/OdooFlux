# D: Performance review, P2 analysis hot path

Date: 2026-11-07. Scope: behaviour-preserving optimisation of `odooflux migrate` analysis (dry-run) on the P2 corpus.
Nothing committed or pushed.

## Setup

- Corpus: `tests/benchmarks/generate_repo.py /tmp/perf/p2/repo 300` (300 modules, 30 files each, seed 20260106, 9 000 files).
- Command: `odooflux migrate --addons-path <corpus> --from-version 14 --dry-run --no-color --report-format json --report <file>`
  (same workload as `tests/benchmarks/bench_analyze.py`, plus dry-run and a JSON report).
- Golden check: `tests/golden_fixtures/17.0/kbi_demo` copied without `expected/`, `--module ... --from-version 17 --to-version 18 --dry-run --report-format json`.
- Machine: i5-13420H, Python 3.12.3 (same as `tests/benchmarks/REFERENCE_MACHINE.md`).

## Hotspots (cProfile, cumulative, baseline code, profiler overhead included)

Top 10 by cumulative time that are in the analysis path:

| # | Function | Cum (s) | Calls | Note |
|---|---|---|---|---|
| 1 | `core/engine/step_runner.py::detect` | 8.94 | 9 000 | runs every knowledge rule per file |
| 2 | `core/orchestrator/knowledge_rules.py::KnowledgeRule.detect` | 7.17 | 200 700 | adapter over bound rules |
| 3 | `rules/shared/loader.py::BoundRule.detect` | 6.84 | 200 700 | calls the rule detector functions |
| 4 | `analyzers/risk_inventory.py::inventory_module` | 1.83 | 300 | outside knowledge rules, not changed |
| 5 | `rules/python/generic.py::flag_method_call_str_argument` | 1.74 | 3 000 | includes `Names` build and Python parse |
| 6 | `rules/security/record_rules.py::flag_unrestricted_global_rules` | 1.20 | 3 000 | mostly first-touch XML parse |
| 7 | `validation/dependency/integrity.py::check_integrity` (L3) | 1.20 | 300 | not changed (L3 semantics are out of scope) |
| 8 | `cli/report_outputs.py::finish` / `json_renderer.render` | 1.21 / 1.01 | 1 | `json.dumps(indent=2)`, pure Python; reporting/ is out of scope |
| 9 | `rules/models/renamed.py::flag_python_model` + `flag_xml_model` | 0.74 + 0.68 | 72 000 | 12 rule bindings per file, each re-walks the tree |
| 10 | `discovery/modules.py::iter_module_files` (`pathlib.relative_to`) | 0.84 | 900 | pathlib overhead, not changed |

Parser caches are already effective: an instrumented run showed every XML file (6 000) and every Python file (6 300) is parsed exactly once per run (max one miss per path). Re-parsing is not a hotspot.

## Changes

1. `core/engine/step_runner.py::order_rules`: the topological order depends only on the rule keys and dependency edges, but was recomputed for each of the 9 000 files. It is now memoised by that signature (cycles still raise). Same order, same exception.
2. `utils/astnodes.py::nodes_of`: multi-type and base-class queries re-scanned every node with `isinstance` on each call (about 414 000 scans). The filtered tuple is now memoised per tree and `types` (trees are documented as immutable). Same tuples in `ast.walk` order.

## Numbers (wall time, `time` from shell, 3 runs each, dry-run JSON report)

| | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|
| Before | 6.43 s | 6.36 s | 6.29 s | 6.36 s |
| After | 5.96 s | 6.03 s | 6.08 s | 6.03 s |

Improvement: about 5 %. Far from the 2x target.

## Equivalence proof

- P2 corpus: JSON report, normalised (run ids, timestamps, state dir masked, sorted keys) is identical before and after.
- P2 corpus: default text report, with timestamp and run-id lines masked, is identical (82 518 lines).
- Golden `kbi_demo` (17 to 18): JSON report, normalised, is identical (17 rule findings).

## Tests

- Targeted: `tests/unit/test_knowledge_rule_selection.py`, `tests/unit/test_step_runner_order.py`, `tests/unit/test_legacy_adapter.py`, `tests/unit/knowledge/*`, `tests/integration/hardening/test_hotpath_equivalence.py`: 110 tests OK.
- Full: all 1 510 unit and integration test modules run by dotted name (`PYTHONPATH=src python3 -m unittest <modules>`): OK, 9 skipped.
- Note: `unittest discover -s tests/unit` without `-t` fails at import for package-relative modules. This is a harness issue, not a regression, and it happens before the change too.

## What was NOT changed (and why)

- No rule was skipped, merged or short-circuited. No rule data, knowledge JSON, AI code, L3 dependency-scan semantics, reporting/ or core/recovery.
- The remaining knowledge cost (about 7 s profiled) is the bodies of 22 detectors per file, each doing its own full AST or XML scan (for example `Names` build per file, `renamed` class-body scans, `flag_xml_model` element walks). Removing it needs a design change: one per-file index of AST and XML elements shared by all detectors, with each detector's output re-proven. That is a larger change than this review.
- `JsonRenderer` (`indent=2` disables the C encoder, about 1 s). Needs a byte-identical proof and reporting/ is out of scope.
- `inventory_module` (risk inventory, about 1.8 s profiled) and `check_integrity` (L3, about 1.2 s): outside the knowledge path, and L3 is out of scope.
- `iter_module_files` pathlib use (about 0.8 s profiled): discovery path, not changed.
- Eager tokenisation in `parsers/python/document.py::_parse_document`: laziness would change when tokenize errors surface, so it is not a safe change without a semantics decision.

## Open items

- A 2x gain on this workload needs the shared per-file index described above (owner decision on design).
- The JSON renderer and discovery pathlib overhead are the cheapest remaining wins if their output proofs are accepted.
