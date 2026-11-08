# Contract: Registries and Plugins (P2)

Refines [CONTRACTS.md § Plugin registration](../../../docs/planning/architecture/CONTRACTS.md#plugin-registration).

## Registry kinds

| Registry | Entry contract | Key | Built-ins in P2 |
|---|---|---|---|
| `versions` | `OdooVersion` | `id` | 12.0–19.0 from `knowledge/versions.json` |
| `rules` | `Rule` | `id` | Legacy adapter rules (`legacy-*`) |
| `parsers` | `ParserAdapter` | `language` | `python` (stdlib), `xml` (well-formedness only; spans in P4), `manifest` |
| `validators` | `Validator` | `id` | `syntax.python`, `syntax.xml`, `syntax.manifest`, `static.rescan` |
| `runtimes` | `RuntimeEnvironment` | `id` | none (P7) |
| `ai_providers` | `AIProvider` | `name` | none in core; the legacy Anthropic call is wrapped as `legacy-anthropic` until P6 |
| `renderers` | `Renderer` | `format_id` | `json`, `terminal-legacy` |

## Registration obligations

- `entry.contract_version` must equal `CONTRACT_VERSION`; otherwise `PluginContractError(plugin,
  expected, actual)` is raised and logged, and the entry is skipped.
- IDs are unique; a duplicate is `DuplicateRegistrationError`.
- `all()` returns entries sorted by key (determinism).
- Plugins are loaded only from `--plugin` or the config `plugins = [...]`. No automatic discovery.
- Exceptions raised by plugin callables during a run become findings (`RULE_ERROR`,
  `VALIDATOR_ERROR`), and the module status is capped at `NEEDS_REVIEW`.

## Contract tests (tests/contract/)

For each kind, a sample plugin under `tests/contract/samples/` plus a test that registers it, runs
a fixture, and asserts its effect is visible in the report. One negative test per kind uses
`contract_version = 99`.
