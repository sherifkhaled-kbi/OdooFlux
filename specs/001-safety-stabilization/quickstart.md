# Quickstart: Verifying Safety Stabilization (P0)

Use these steps after implementation to check the P0 outcome. Run them from the repository root.

1. Run the regression suite:
   `python -m unittest discover -s tests -p "test_p0_*.py" -v`
   Expected: all tests pass, offline.
2. Prove analyze mode is read-only:
   ```bash
   T=$(mktemp -d); cp -r tests/golden_fixtures/p0_kbi_demo_v14 $T/kbi_demo
   find $T -type f -exec sha256sum {} + | sort > /tmp/before
   python odooflux.py --module $T/kbi_demo --from-version 14 --no-color
   python odooflux.py --module $T/kbi_demo --from-version 14 --fix --dry-run --no-color
   find $T -type f -exec sha256sum {} + | sort | diff /tmp/before - && echo READ-ONLY-OK
   ```
3. Prove fix mode writes only valid files and keeps backups outside the addons path:
   ```bash
   S=$(mktemp -d)
   python odooflux.py --addons-path $T --from-version 14 --fix --backup --state-dir $S --no-color
   ls $T                                  # only kbi_demo
   python -m py_compile $T/kbi_demo/models/demo.py && echo PY-OK
   python -c "import xml.etree.ElementTree as E;E.parse('$T/kbi_demo/views/demo_views.xml');print('XML-OK')"
   ls $S/runs/*/backup/ $S/runs/*/log/run_log.jsonl
   ```
4. Check exit codes: `--fail-on critical` exits 0 when only warnings remain. A state dir inside
   `$T` exits 4.
