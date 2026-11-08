# Quickstart: Official Source Intelligence (verification guide)

These steps verify feature 004 once it is implemented. Run them from the repository root.

```bash
# 1. Validate the shipped knowledge base (expects errors=0)
python -m odooflux knowledge validate

# 2. Run the feature's tests (offline)
python -m unittest discover -s tests/unit/knowledge
python -m unittest discover -s tests/integration/knowledge

# 3. Confirm the matrix is generated, not hand-edited
python -m odooflux knowledge matrix --check

# 4. Refresh dry-run against local official clones (maintainers only; network to clone)
git clone --filter=blob:none --no-checkout --branch 18.0 https://github.com/odoo/odoo /tmp/odoo-18.0
python -m odooflux knowledge refresh --repo odoo/odoo=/tmp/odoo-18.0 --report /tmp/refresh.json
# Expected: no knowledge files modified; report lists unchanged/moved/missing/unavailable
git status --short src/odooflux/knowledge   # must be empty
```

Expected results:
- Step 1 prints `records=<n> … errors=0`, where `n` is ≥ 52 (EV-001…015, 101…125, 201…212).
- Step 3 exits 0.
- Before P5, every matrix cell is `NOT_ASSESSED` or `RESEARCH_SEEDED`.
