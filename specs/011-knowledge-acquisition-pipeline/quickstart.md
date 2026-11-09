# Quickstart: Knowledge Acquisition Pipeline

Command flow, checked against the built CLI by `tests/integration/kap/test_quickstart.py` (T089). All steps run offline on local inputs. `WORK` is a scratch directory, `KB` is the kb-home (`export ODOOFLUX_KB_HOME=$KB`). Every command takes `--kb-home` (or the environment variable). The source registry defaults to `./sources.json` in the current directory; pass `--registry FILE` to choose another.

## 1. Maintainer: build a release from two pinned local clones

```bash
odooflux knowledge source add --file ksrc-17.json --kb-home $KB   # one spec object per call; local: URL, pinned 40-hex SHA, official + expected_origin (see below)
odooflux knowledge source add --file ksrc-18.json --kb-home $KB   # second source (odoo 18.0)
odooflux knowledge source acquire --kb-home $KB                   # snapshots into $KB/snapshots; exit 4 if a pinned SHA is missing
odooflux knowledge source show odoo-community-17.0 --json         # the snapshot_id of each acquired source
odooflux knowledge extract --from $KB/snapshots/<snap17>.json --to $KB/snapshots/<snap18>.json --step 17-18 --blobs $KB/snapshots --out $WORK/ledger --kb-home $KB
odooflux knowledge ledger list --ledger $WORK/ledger/17-18.ledger.json --disposition UNRESOLVED
odooflux knowledge candidates generate --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json --source ksrc-17.json --checked-on 2026-11-08 --author maintainer
odooflux knowledge candidates list --path $WORK/tree --json
odooflux knowledge candidates accept <CR-ID> --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json --author maintainer   # one call per CR-ID; there is no bulk accept
odooflux knowledge rule create --path $WORK/tree --from-file my-rule.json --evidence EV-ID --author maintainer   # optional manual rule
odooflux knowledge release build --plan build-plan.json --dry-run --kb-home $KB   # prints the 17 steps
odooflux knowledge release build --plan build-plan.json --kb-home $KB            # runs them, prints the outcome, completeness and release id
odooflux knowledge coverage show --release <kr-id> --kb-home $KB
odooflux knowledge package export <kr-id> -o odoo-17-18.ofkp --kb-home $KB
```

`build-plan.json` holds `label`, `sources` (the two source specs), `pairs` (`[{"step": "17-18", "from": "odoo-community-17.0", "to": "odoo-community-18.0"}]`), `source_meta` (`{"<source_id>": {"repository": "owner/name"}}`), and optionally `created_at`, `checked_on` and `author`.

Expected: `coverage show` prints the 8 metrics as fractions with denominators, and `completeness COMPLETE` or `PARTIAL` with limits; never a recall number without a benchmark name.

### Source identity for `candidates generate`

Evidence names the repository of its source as an `org/name` slug. `candidates generate --source FILE` takes it one of two ways. Without either, the command exits 2, names both ways in its message, and writes nothing.

1. **Official clone (the example above).** The spec has `"official": true`, `"kind": "GIT_COMMUNITY"` and `"expected_origin": "https://github.com/odoo/odoo"`. The clone's `origin` remote must be that URL: `git -C <clone> remote add origin https://github.com/odoo/odoo`. The slug is `odoo/odoo`, taken from `expected_origin` (the host is stripped; an ssh form such as `git@github.com:odoo/odoo.git` gives the same slug). Evidence url: `https://github.com/odoo/odoo/tree/<revision>`.
2. **Unofficial source.** The spec gives `repository` as `org/name` in the `--source` file. The registry does not accept a `repository` key, so keep a separate candidate-source file next to the registered spec, then run:

```bash
odooflux knowledge candidates generate --path $WORK/tree --ledger $WORK/ledger/17-18.ledger.json --source ksrc-17-unofficial.json --checked-on 2026-11-08 --author maintainer
```

Evidence from an unofficial source stays `official: false` and its candidates are `review_required`. Its url is `source:<source_id>@<revision>` when the spec has no `expected_origin`, so the local clone path never appears in evidence.

`candidates accept` follows `candidates generate`; one call per CR-ID.

Expected: `coverage show` prints the 8 metrics as fractions with denominators, and `completeness COMPLETE` or `PARTIAL` with limits; never a recall number without a benchmark name.

## 2. Consumer: install and use offline

```bash
odooflux knowledge package validate odoo-17-18.ofkp --expect-digest <release_digest>   # the release_digest (release.json, release show), not the sha256 of the file
odooflux knowledge package import odoo-17-18.ofkp --activate --kb-home $KB2   # see note below
odooflux knowledge release list --kb-home $KB2
odooflux migrate --module <module-dir> --from-version 17 --to-version 18 --kb-home $KB2 --report report.json --report-format json   # report shows release id and digest
odooflux knowledge release rollback --kb-home $KB2   # needs a previous release (exit 1 otherwise)
odooflux knowledge release deactivate --kb-home $KB2   # back to the built-in knowledge
```

Note on `package import`: a release built from the built-in tree carries built-in FIX_ENABLED rules. The import accepts a carried row only when it is byte-identical to the shipped built-in rule, checked against the verified shipped baseline (never by id); those rows stay FIX_ENABLED and the decision is recorded in the `release_installed` audit entry as `details.inherited_trust` (`rule_ids`, `baseline_digest`). Any other FIX_ENABLED row that fails the gates is refused (exit 3, code P10) and nothing is installed. `--downgrade-unverified` is an optional cap: it caps the refused rows to DETECT_ONLY, and it is not needed for a pipeline-built release.

With no release activated, every command and output behaves exactly as before KAP.

## 3. Safety behaviours to try

| Try | Expected |
|---|---|
| `package import` of an archive with `../x` | exit 3 (`P01: dot segment`), nothing installed |
| import a pipeline-built package with carried built-in FIX_ENABLED rules | exit 0, installed; the byte-identical built-in rules stay FIX_ENABLED and are listed in the audit entry (`details.inherited_trust`). A FIX_ENABLED row that is not a shipped row and fails the gates: exit 3, P10 named, nothing installed |
| `source fetch ID` without `--allow-network` | exit 2 (`needs the explicit --allow-network flag`), no socket call |
| pinned SHA absent from the clone | exit 4, no snapshot written |
| `release remove <active-id>` | exit 1 (`is ACTIVE; deactivate or activate another`) |

## Notes

- **`package import` does not need `--downgrade-unverified` for a pipeline-built release.** The built-in FIX_ENABLED rules carried into the release are accepted under owner decision D3 (OD-K13, implemented by feature 012) when they are byte-identical to the shipped built-in rules; the decision is recorded in the `release_installed` audit entry. `--downgrade-unverified` remains an optional cap for rows that are refused: with it they are capped to DETECT_ONLY, the release is recomputed, and the install gets a different release id from the package (the import prints the new id, and the downgrade is audit-logged). `--expect-digest` checks the package's own release digest, not the installed id.
- **Section 3 values** are those the CLI prints for the fixtures in `test_quickstart.py`; the exit codes are the contract, the message wording may vary.
- **Unofficial evidence does not reach a release yet.** `release build` refuses evidence whose url is outside the official allow-list (E002). An unofficial source can therefore generate and accept candidates, but its evidence cannot be packaged until that owner decision is made.

## 4. Tests

```bash
python -m unittest discover -s tests/unit/knowledge/kap -v
python -m unittest discover -s tests/integration/kap -v
# opt-in only:
ODOOFLUX_KAP_CLONES=/path/to/clones ODOOFLUX_KAP_LIVE_TESTS=1 python -m unittest tests.integration.kap.test_live_sources
```

Do not run the full suite as part of KAP task execution; `tools/ci_check.sh` runs once in T090.
