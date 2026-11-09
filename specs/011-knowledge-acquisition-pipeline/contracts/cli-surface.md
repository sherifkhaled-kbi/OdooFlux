# Contract: CLI Command Surface

All under the existing entry point `odooflux knowledge ...` (`cli/knowledge.py` registers groups; each group lives in its own module with `register(subparsers)`). Existing `validate`, `refresh`, `matrix` unchanged. Common options: `--kb-home PATH`, `--json`, `--quiet`. No command except `source fetch` may open a socket.

## Exit codes (reuse `cli/exit_codes.py` values where they exist; VERIFY, add only missing ones)

| Code | Meaning |
|---|---|
| 0 | ok (PARTIAL completeness is ok with warnings) |
| 1 | validation or gate failure |
| 2 | usage error / network not allowed |
| 3 | package rejected |
| 4 | source unavailable or pinned revision missing |
| 5 | release integrity failure |

## Commands

| Command | Contract |
|---|---|
| `knowledge source add --file spec.json` / `list` / `show ID` / `remove ID` | edit the registry file `<workdir>/sources.json` |
| `knowledge source acquire [ID...] [--registry F]` | offline snapshot from local inputs (contracts/source-adapter) |
| `knowledge source verify [ID...]` | re-hash blobs |
| `knowledge source fetch ID --allow-network` | only networked command; allow-list enforced |
| `knowledge extract --from SNAP --to SNAP --step NN-NN` | diff, accounting, ledger drafts |
| `knowledge ledger show|list|set-disposition|confirm|verify` | contracts/change-ledger |
| `knowledge candidates generate|list|accept|reject|resolve` | contracts/candidate-rule-generation |
| `knowledge ai propose [--provider P --grant ...]` | optional, D-08 grants, off by default |
| `knowledge rule create|edit|disable|enable|retire|inspect|validate|history|link-evidence|add-test|promote|resolve` | contracts/manual-rule-cli |
| `knowledge coverage show|gates` | contracts/coverage-and-gates |
| `knowledge release build [--dry-run] [--from-step N] [--allow-failed]` | contracts/release-lifecycle |
| `knowledge release list|show ID|diff A B|activate ID|deactivate|rollback|remove ID|audit-verify` | kb-home management |
| `knowledge package export ID -o FILE` | deterministic `.ofkp` |
| `knowledge package validate FILE [--expect-digest SHA]` | reader checks only, installs nothing |
| `knowledge package import FILE [--activate] [--downgrade-unverified] [--expect-digest SHA]` | atomic |
| `knowledge package list|inspect FILE` | manifest summary |
| `odooflux migrate ... --kb-home PATH --require-complete-kb` | contracts/migration-integration |

## Output rules

Deterministic ordering; human text one finding per line (`CODE severity subject message`, as `knowledge validate`); `--json` is canonical JSON. Errors never print file contents, secrets, or absolute paths of untrusted packages (relative entry names only).

## Tests

`test_cli_help_lists_groups`, `test_existing_commands_unchanged`, `test_network_only_in_fetch`, `test_exit_codes`, `test_json_output_canonical`, one smoke test per group.
