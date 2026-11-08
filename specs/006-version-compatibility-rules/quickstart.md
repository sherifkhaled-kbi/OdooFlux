# Quickstart: Version Compatibility Rules (verification guide)

```bash
# Knowledge base valid (rules + new evidence)
python -m odooflux knowledge validate

# Rule coverage: every loaded rule has positive/negative/idempotence tests
python -m unittest tests.unit.rules.test_rule_coverage

# All rule tests
python -m unittest discover -s tests/unit/rules

# Golden multi-step migrations (14.0…18.0 → each later target)
python -m unittest tests.integration.test_golden_migrations

# Matrix reflects reality
python -m odooflux knowledge matrix --check

# Manual smoke: analyse a 17.0 golden module for 19.0 (no writes)
python -m odooflux --module tests/golden_fixtures/17.0/kbi_demo --from-version 17.0 --to-version 19.0
```

Expected results:
- The coverage test reports `missing=0`.
- Golden migrations report 100 % byte match.
- The matrix shows steps 14-15…18-19 as `RULES_TESTED` (or documents every exception as a gap).
- The smoke run lists `_sql_constraints` and `@api.returns` findings as review-required with
  evidence IDs, and reports module status `NEEDS_REVIEW`.
