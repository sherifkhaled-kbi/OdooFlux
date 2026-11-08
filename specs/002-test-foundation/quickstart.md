# Quickstart: Test Foundation (P1)

```bash
# 1. Default offline suite (no network, no Docker)
python -m unittest discover -s tests -v

# 2. Only the characterisation suite
python -m unittest tests.integration.test_characterisation -v

# 3. Regenerate expectations after an intended change (refuses on a dirty tree without --force)
python tools/update_expectations.py && git diff --stat tests/golden_fixtures

# 4. Opt-in suites
ODOOFLUX_RUNTIME_TESTS=1 python -m unittest discover -s tests/runtime -v
ODOOFLUX_AI_TESTS=1      python -m unittest discover -s tests -p "test_ai_*.py" -v
```

Expected: step 1 exits 0 and lists runtime and AI tests as skipped, with the flag name in the
reason.
