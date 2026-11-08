# Contract: RuntimeEnvironment (refines [CONTRACTS.md § RuntimeEnvironment](../../../docs/planning/architecture/CONTRACTS.md#runtimeenvironment-layer-45))

| Member | Obligation |
|---|---|
| `name`, `contract_version` | Registry key and version check |
| `available() -> (bool, reason)` | Without side effects, e.g. checks that the docker CLI exists and the daemon responds |
| `prepare(version, modules_ro_path, limits) -> EnvHandle` | Creates isolated DB and Odoo environment for `version`; image reference must resolve to an allow-listed, digest-pinned image; labels all resources with `run_id` |
| `install(handle, module_names) -> RuntimeRun` | Odoo CLI equivalent of `-i <modules> --stop-after-init` on a fresh database (options verified to exist at EV-303) |
| `upgrade(handle, module_names) -> RuntimeRun` | `-u <modules> --stop-after-init` |
| `run_tests(handle, module_names, tags) -> RuntimeRun` | `--test-enable` / `--test-tags` (EV-303); per-test outcomes parsed (format research: G-R-23) |
| `teardown(handle)` | Idempotent; removes containers/networks/volumes with the run label; must run on every exit path |

`Limits`: `cpu` (cores), `memory_mb`, `wall_time_s`, `network` (`none` default | `allowlist`), `pids`.

`RuntimeRun`: `exit_code`, `duration_ms`, `log_path` (state dir), `log_excerpt`, `errors[]` (`class`, `message`, `file?`, `xml_id?`, `line?`), `killed_reason?` (`timeout`, `oom`).

Isolation obligations: the module mount is read-only; no host paths other than the module copy and a per-run scratch volume; no host network; no privileged mode; non-root user inside the container where the image allows.
