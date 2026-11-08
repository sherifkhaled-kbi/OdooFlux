# R3 end-to-end review (automated, independent; not human approval)
Installed wheel odooflux 0.2.0 (venv, --no-index --no-deps), run from /tmp. Note: no `analyze` command exists; analyze = `migrate` without --fix.
| Scenario | Command (abridged) | Exit | Result | Discrepancy |
|---|---|---|---|---|
| wheel/help/validate | odooflux --help; knowledge validate | 0/0 | 200 records, 91 rules, 0 errors; ai/catalog/providers.json + view_index/12..19.json in wheel | none |
| analyze 17->18 | migrate --module kbi_demo | 1 | digest unchanged; 30 findings; json/sarif/html written | exit 1 from findings (legacy mapping) |
| provisional | + --provisional-corpus | 1 | label in terminal, json, sarif, html | none |
| verification | same | 1 | L1-L3 ran; L4/L5 "Not run (runtime_not_requested)"; no "equivalen" claim in any format | none |
| dry-run diff | --fix --dry-run --diff | 1 | no writes; patch -p1 applies on pristine copy (3 files) == fix result | `--dry-run` without --fix gives empty diff (note printed) |
| fix + rollback | --fix; rollback RUN | 0/0 | backup in ~/.cache/odooflux/runs/ID/backup (outside addons); log present; rollback byte-identical | 2nd rollback: "conflict" x3, exit 1 (not "already rolled back") |
| resume | resume RUN (rolled back) | 4 | "run was rolled back; start a new run" | no status command; only `versions` |
| 16.0->18.0 | plan; migrate --fix --dry-run | 0/1 | two steps 16->17, 17->18, READY; no writes | none |
| unknown target | --to-version 99.0 | 2 | usage error | ok |
| target older | 18.0 -> 17.0 | 2 | usage error | ok |
| no __manifest__.py | --module nomanifest/foo | 0 | "No issues found! Module looks clean." | DEFECT: false clean |
| Enterprise dep | depends web_studio | 1 | integrity.missing_module, Enterprise notice | ok |
| missing dep | depends kbi_nonexistent | 1 | L3 warning | ok |
| --ai no consent / provider / model / budget | migrate --ai ... | 2 | stops pre-transport, one missing requirement per run | ok; --ai-authorize path not reached (catalog has no models) |
| --api-key | --api-key sk-x | 1 | deprecation warning shown twice; key not echoed | cosmetic |
| --enable-rule NOPE | | 2 | usage error | ok |
| report inside module | --report/--sarif/--html/--diff in module | 2 | refused (REQ-SEC-003), nothing written | ok |
| serial/--jobs 4/--incremental | json digest | 1/1/1 | all equal (0382909b...); incremental re-run skips unchanged module | none |
| support-statement --check | installed | 1 | default path resolves to venv/lib/python3.12/docs/planning/... | DEFECT; also with explicit --out repo file: "out of date" |
| SUPPORT_STATEMENT.md | read | - | "No path is supported" (0 supported, 16 experimental, 12 unsupported) | none |
## Ranked defects
1. Module dir without __manifest__.py exits 0 "Module looks clean". Repro: `mkdir -p x/foo; echo a=1>x/foo/a.py; odooflux migrate --module x/foo --from-version 17.0 --to-version 18.0; echo $?`
2. `support-statement --check` default path is relative to site-packages (nonexistent docs/ dir under venv); useless when installed. Repro: `odooflux support-statement --check`.
3. Installed generator output differs from committed statement (PROVISIONAL column absent: marker from repo tree not in wheel), so --check always fails. Repro: `odooflux support-statement --out /tmp/s.md; diff /tmp/s.md docs/planning/SUPPORT_STATEMENT.md`.
4. Fixing an already fixed copy reports 25 open vs 24 after first fix (second `--fix` run not idempotent in counts); minor. Also repeat rollback reports conflicts instead of "already rolled back".
5. Fixture kbi_demo contains expected/ inside the module dir, so it gets scanned if copied whole (my copy included it).
## Not run
Real --ai transport/authorization (catalog has empty models, no network); interrupted-run resume (no way to interrupt safely); L4/L5 runtime (no Odoo); `--exit-codes v1` and specs cli.md comparison: no specs/*/contracts/cli.md except specs/003-core-architecture/contracts/cli.md, not read in detail (exit-code mapping vs doc unverified, 010 has no cli.md).
Scratch /tmp/e2e-review left in place; repo untouched. Runs also left state in ~/.cache/odooflux/runs.
