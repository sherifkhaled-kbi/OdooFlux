# Verification: 005 Structured Transformations (Phase 7)

Commit: `c9914e6ec92f394777597e2e77d22a4a4c3e3634` (HEAD on `main`). The working tree is dirty
(005 and 006 work is uncommitted), so this SHA alone does not pin the tested state.

Test command: `cd "/home/sherif-khaled/Desktop/KBI Projects/OdooFlux" && PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .`

## T030: parse + locate perf (opt-in, `ODOOFLUX_BENCH=1`)

Run: `ODOOFLUX_BENCH=1 PYTHONPATH=src python3 -m unittest -v tests.benchmarks.test_parse_perf`

| Case | Result | Budget |
|---|---|---|
| 5,000-line generated Python: parse + `remove_decorator` (624 spans) | 0.348 s | < 1 s, PASS |
| 5,000-line generated XML: parse + `find` (833 elements) | 0.067 s | < 1 s, PASS |

Without the variable both tests skip (`OK (skipped=2)`). The gate is `ODOOFLUX_BENCH=1`, the convention used by the other benchmarks in `tests/benchmarks/`, not `ODOOFLUX_PERF`.

## T031: idempotence and byte-preservation harness

New runner: `tests/regression/test_corpus_preservation.py`.

- Preservation: 254 files under `tests/golden_fixtures/transformations/` (python, xml, converter, js) and `tests/golden_fixtures/p0_kbi_demo_v14/`. Each file gets the fixed-seed random non-overlapping edits from `test_preservation_fixtures`. Result: 0 violations, and the round-trip is byte-identical for every file.
- Idempotence, converter: 71 cases re-converted from their own `expected.xml` yield 0 edits. Result: 0 violations.
- Idempotence, python: `tests/unit/transformers/test_python_helpers.py::test_corpus_edit_cases_are_idempotent`. Result: 0 second-pass edits.
- Idempotence, feature 002 fixtures: covered by the preservation pass above. Edit idempotence on these fixtures is not separately asserted.

Gaps, not closed:
- XML corpus (26 cases): closed with a synthetic harness, since corpus `meta.json` has no rule operations. New `tests/regression/test_xml_corpus_idempotence.py` applies `set_attr` (`data-odf-idem="1"`) to every element of every parseable XML corpus input (24 of 26; 2 have `parse_error` and are skipped), requires well-formed output, a second pass of 0 edits, and `remove_attr` twice yields 0 edits on the second pass. Result: 24 files, 61 elements edited, 0 violations. Covered (same file, 3 tests): `set_attr`, `remove_attr`, `rename_tag` (every element renamed to a fixed name; second pass 0 edits; well-formed), `replace_element` (root element replaced twice with the same XML; output stable and well-formed, since the helper always emits an edit, idempotence is output stability). Not covered: `convert_element` (lives in `transformers/modifiers.py`, covered by the 71-case converter corpus idempotence above) and real rule operations (none exist for this corpus). 2 of 26 corpus inputs have `parse_error` and are skipped.
- JS corpus: no edits are produced (detect-only), so there is no idempotence to check.

T031: 0 violations on all corpora, with the harness scope stated above. Commit SHA: `c9914e6` (dirty tree, see header).

## T032: quickstart.md (re-run with `-t .`)

Run from the repo root with `PYTHONPATH=src`; all commands use `-t .`.

| Command | Actual |
|---|---|
| `discover -s tests/unit/engine -t .` | Ran 55, OK |
| `discover -s tests/unit/parsers -t .` | Ran 60, OK (skipped=5: adapter tests) |
| `discover -s tests/unit/transformers -t .` | Ran 31, OK |
| `tests.regression.test_audit_transformations` | Ran 14, OK |
| `ODOOFLUX_JS_ADAPTER_TESTS=1 ... -p 'test_js*'`, venv `/tmp/odf-venv` (lxml 6.1.3, tree-sitter 0.26.0, tree-sitter-javascript 0.25.0) | Ran 38, OK (5 real adapter tests ran) |
| `ODOOFLUX_JS_ADAPTER_TESTS=1 ... -p 'test_js*'`, system python without the extra | Ran 38, FAILED (failures=5): by design, adapter tests fail when enabled but the extra is missing |

Expectations: converter corpus (71 cases) 0 failures; byte-preservation and idempotence harness 0 violations; the adapter-enabled run now exercises the real tree-sitter adapter. Remaining deviations from quickstart.md as written: the commands need `-t .`, and (resolved, see T032 re-run below) `ODOOFLUX_DISABLE_JS_ADAPTER` is now read by the adapter.

## T002/T027/T028 (D-02 approved)

`pyproject.toml` extras: `js = tree-sitter>=0.23,<0.27, tree-sitter-javascript>=0.23,<0.26`; `xml`/`rng = lxml>=5.0,<7`. Core `dependencies = []`. Adapter: `src/odooflux/parsers/javascript/treesitter_adapter.py` (lazy import, `available()`, `parse`, `query`, `has_errors`); `rng.available()` added for lxml. `pip install` of the three libs into the venv succeeded; `pip install -e '.[js]'` is verified in the T002 section below.

## Full suite

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .`: Ran 356, FAILED (errors=3, skipped=4). The 3 errors are the pre-existing `tests/contract` import errors. The count rose from 343 to 356 (2 new runner tests, 2 new skipped perf tests, plus 006 work that is landing concurrently). No new failures.

Latest run (after T027/T028/T031 work): Ran 870, FAILED (failures=2, errors=3, skipped=17). Errors: the 3 known `tests/contract` import errors. Failures: `test_import_graph` (offenders: `odooflux/dependencies/core_modules.py` importing `validation.dependency.integrity`, from concurrent 008 work) and `test_no_version_literals` (`rules/manifest/hygiene.py:50`); neither touches the files of this task. `treesitter_adapter` imports nothing outside the stdlib at module import (`tree_sitter` not in `sys.modules` after import).

## T002 re-verification (fresh venv outside repo)

```
python3 -m venv /tmp/odf-t002
/tmp/odf-t002/bin/pip install -e ".[js]"    # then ".[xml]", ".[rng]"  -> all rc=0
/tmp/odf-t002/bin/pip list   # lxml 6.1.3, tree-sitter 0.26.0, tree-sitter-javascript 0.25.0, odooflux 0.2.0 (editable)
cd /tmp && /tmp/odf-t002/bin/python -c "import tree_sitter, lxml, odooflux"   # imports ok
ODOOFLUX_JS_ADAPTER_TESTS=1 /tmp/odf-t002/bin/python -m unittest discover -s tests/unit/parsers -p 'test_js*' -t .   # Ran 42, OK (5 real adapter tests run)
/tmp/odf-t002/bin/pip show odooflux   # Requires: (empty); pyproject dependencies = []
```

`src/odooflux.egg-info` was produced by the editable install; it is covered by `.gitignore` (`*.egg-info/`, confirmed with `git check-ignore`). T002 Done-when met.

## T032 re-run: ODOOFLUX_DISABLE_JS_ADAPTER

Spec source: quickstart.md ("With the adapter masked (`ODOOFLUX_DISABLE_JS_ADAPTER=1`), JS corpus cases report detect-only findings and `NEEDS_REVIEW`"). Implemented in `treesitter_adapter.available()`: any value other than empty or `0` makes it return False (so `has_errors` returns None, validator reports UNAVAILABLE, detect-only/NEEDS_REVIEW path). Tests first: `tests/unit/parsers/test_js_adapter_disable.py` (4 tests; red before, green after). Quickstart commands re-run: engine 55 OK, parsers 64 OK (5 skipped), transformers 31 OK, audit_transformations 14 OK, js adapter run in venv 42 OK; with the variable set in the venv the js tests are 42 OK and the validator reports UNAVAILABLE. Converter corpus and byte-preservation/idempotence results are those recorded above (71 cases, 0 violations). Full suite: Ran 940, FAILED (failures=1: `tests.contract.test_plugin_exception`, outside my ownership), skipped=17.
