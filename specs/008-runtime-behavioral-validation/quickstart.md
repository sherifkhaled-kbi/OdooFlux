# Quickstart: Runtime and Behavioral Validation (validation scenarios)

Planned commands (not implemented).

1. **Decision table**: `python -m unittest tests.unit.validation.test_status_decision` (offline).
2. **Static only**: `odooflux migrate --source 16.0 --target 17.0 tests/golden_fixtures/... --dry-run` → `STATIC_VALIDATED`, report shows L4/L5 unavailable or skipped.
3. **Runtime install** (opt-in): `ODOOFLUX_RUNTIME_TESTS=1 python -m unittest tests.runtime.test_install` → install fixture `INSTALL_VERIFIED`; broken-view fixture `FAILED/view_validation`.
4. **Limits**: `tests.runtime.test_limits` → loop fixture `FAILED/timeout`; `docker ps -a --filter label=odooflux.run=<id>` is empty afterwards.
5. **Behaviour**: `tests.runtime.test_behavior_compare` → 1 regression, 1 pre-existing failure, 1 pass-both.
6. **RNG**: with and without `lxml` installed, `tests.unit.validation.test_rng` → FAIL vs UNAVAILABLE.

## Measured baseline

Measured on the development host (Linux, 12 CPUs, 15.6 GB RAM, Docker 29.7.2) with odoo:19.0 (digest
`odoo@sha256:5db447482177ca598b97539bc186b61f5f271371ab3a90f3940ecf33b63af7b0`) and postgres:16 (digest
`postgres@sha256:71e27bf60b70bded003791b5573f8b808365613f341df20ffcf0c1ed7bc13ddf`). Resource values were sampled with
`docker stats` every 0.5 s during two real `install_ok` installs, so the peaks are sampled, not exact.

| Measurement | Value |
|---|---|
| `install_ok` install duration (adapter `duration_ms`, two runs) | 10.4 s, 11.4 s |
| Database readiness (prepare, two runs) | 1.5 s, 1.6 s |
| Odoo container peak memory (sampled) | 96 MiB, 88 MiB |
| PostgreSQL container peak memory (sampled) | 55 MiB, 54 MiB |
| Odoo container peak CPU (sampled, 100% = one core) | 62%, 61% |
| `install_loop` killed at the 60 s wall-time limit | killed at 60.1 s, exit 137, class `timeout`, nothing left behind |

Chosen defaults (`odooflux.validation.runtime.docker_env.Limits`): `cpu=2.0`, `memory_mb=2048`, `pids=512`,
`network=none`, `wall_time_s=900`. The memory and CPU defaults are a ceiling with about 20x headroom over the
observed `install_ok` peak. The wall-time default is for larger module sets and is not derived from this measurement.
Larger installs (up to 300 modules per job, plan.md) have not been measured yet.

## Verification log (T028)

Observed on the development host (Linux, Docker 29.7.2, lxml not installed). Default suite:
`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -t .`. Opt-in suite:
`ODOOFLUX_RUNTIME_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests/runtime -p 'test_*.py' -t .`.

| # | Scenario | Command | Expected | Observed |
|---|---|---|---|---|
| 1 | Decision table | `python -m unittest tests.unit.validation.test_status_decision` | every row; sweep matches oracle; row 7 never reached | OK (sweep of about 40,000 combinations) |
| 2 | Static only | `python -m unittest tests.integration.validation.test_static_only` | L4 and L5 in `layers_unavailable` with reasons; no runtime-verified status | OK. A migrating module with legacy manifest-version warnings is `NEEDS_REVIEW`; a module with nothing to migrate is `STATIC_VALIDATED`. |
| 3 | Runtime install | `ODOOFLUX_RUNTIME_TESTS=1 … tests.runtime.test_install` | `install_ok` INSTALL_VERIFIED; `broken_view` FAIL `view_validation`; `acl_missing_model` FAIL `access_rights`; `enterprise_dep` SKIPPED | OK, 4 tests. Image odoo:19.0, postgres:16, both by digest. |
| 4 | Limits | `ODOOFLUX_RUNTIME_TESTS=1 … tests.runtime.test_limits` | `install_loop` FAIL `timeout` at the 60 s limit; no labelled containers, volumes or networks left | OK, killed at about 60 s, exit 137; `docker ps -a`, volume and network listings filtered by `odooflux.run` were empty afterwards |
| 5 | Behaviour | `ODOOFLUX_RUNTIME_TESTS=1 … tests.runtime.test_behavior_compare` | 1 regression, 1 fail_both, 1 pass_both; L5 FAIL on 18.0 to 19.0; no baseline gives coverage partial and never VERIFIED_SUCCESS | OK, 2 tests |
| 6 | RNG | `python -m unittest tests.unit.validation.test_rng` | FAIL with lxml present (injected fake), UNAVAILABLE without lxml | OK. lxml absent here, so the UNAVAILABLE branch ran against the real import failure. |

Other opt-in tests (`tests.runtime.test_upgrade`) also passed: install then `-u` on one run id.

Re-run 2026-11-07 (Docker 29.7.2 available; images odoo:17.0, odoo:18.0, odoo:19.0 and postgres:16 were already cached, nothing was pulled):
`ODOOFLUX_RUNTIME_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests/runtime -p 'test_*.py' -t .` ran 9 tests in 159 s, all OK
(install, upgrade, limits, behaviour compare 18.0 to 19.0, placeholder gate). Afterwards `docker ps -a --filter label=odooflux.run` listed nothing.
This is a pass of the framework runtime fixtures only.

Matrix: T029-gen (generator that marks `RUNTIME_VALIDATED` only from a valid passing record in `compatibility/runtime_runs.json`) is implemented and
tested. T029-data is NOT done: no run record is shipped (`runs: []`), so the matrix marks no step. The fixtures above are synthetic, not a golden
migration of a step; adding a record would overclaim. Pending, see tasks.md and register item WSF-001.
