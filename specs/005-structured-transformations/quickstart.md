# Quickstart: Structured Transformations (verification guide)

```bash
# Core (stdlib) tests — must pass without optional extras
python -m unittest discover -s tests/unit/engine
python -m unittest discover -s tests/unit/parsers
python -m unittest discover -s tests/unit/transformers
python -m unittest tests.regression.test_audit_transformations

# Optional JS adapter tests (CI job with the extra installed)
pip install 'odooflux[js]'        # pinned tree-sitter + tree-sitter-javascript (after D-02)
ODOOFLUX_JS_ADAPTER_TESTS=1 python -m unittest discover -s tests/unit/parsers -p 'test_js*'
```

Expected results:
- The converter corpus reports `cases>=60 failures=0`.
- The byte-preservation and idempotence harness reports 0 violations across all corpus files and
  the feature 002 golden fixtures.
- With the adapter masked (`ODOOFLUX_DISABLE_JS_ADAPTER=1`), JS corpus cases report detect-only
  findings and `NEEDS_REVIEW`.
