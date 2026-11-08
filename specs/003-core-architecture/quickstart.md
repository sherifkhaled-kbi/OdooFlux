# Quickstart: Core Architecture (P2)

```bash
# Full offline suite (characterisation + contract + unit + failure injection)
python -m unittest discover -s tests -v

# Plan a path (no file access beyond reading manifests)
python odooflux.py plan --from 14.0 --to 19.0 --addons-path tests/golden_fixtures/v14_kbi_demo/input
python odooflux.py versions

# Fix run on a temp copy, then rollback
T=$(mktemp -d); cp -r tests/golden_fixtures/v14_kbi_demo/input/kbi_demo $T/
S=$(mktemp -d)
python odooflux.py --module $T/kbi_demo --from-version 14 --to-version 19 --fix --backup --state-dir $S --report-format json --report $S/r.json
RUN=$(ls $S/runs); python odooflux.py rollback $RUN --state-dir $S
diff -r $T/kbi_demo tests/golden_fixtures/v14_kbi_demo/input/kbi_demo && echo ROLLBACK-OK

# Baseline benchmark (opt-in)
ODOOFLUX_BENCH=1 python -m unittest tests.benchmarks.bench_analyze -v
```
