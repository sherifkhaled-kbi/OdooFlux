# Contract: `odooflux knowledge` command group

Planning contract for the maintainer-facing commands delivered by feature 004. Exit codes:
`0` success, `1` validation findings, `2` usage error, `3` tool error.

## `odooflux knowledge validate [--path DIR]`

Validates all files under `src/odooflux/knowledge/` (or `DIR`).

Output (stdout, one line per problem, sorted):
`<file>:<json-pointer>: <code>: <message>`

Codes:
- `E001` schema violation
- `E002` url not in allow-list
- `E003` invalid revision
- `E004` duplicate id
- `E005` rule missing evidence
- `E006` unknown evidence id
- `E007` registry ordering
- `W001` maturity capped
- `W002` identical claim duplicated

A final summary line: `records=<n> rules=<n> errors=<n> warnings=<n>`.

## `odooflux knowledge refresh --repo NAME=PATH [...] [--revision BRANCH=SHA ...] [--apply] [--report FILE]`

- `--repo` maps repository names (`odoo/odoo`) to local clones.
- `--revision` sets the revision to check per branch (defaults to the record's own revision).
- Without `--apply`, files are never modified (dry-run by default).
- With `--apply`, `moved` records are updated and `missing` ones set to `CONFLICTING`;
  `checked_on` and `checked_by` are updated.

Report (JSON): `{ "checked": n, "results": [{ "id", "location_index", "result":
"unchanged|moved|missing|unavailable", "old_line", "new_line", "candidates": [] }],
"demoted_rules": [] }`.

## `odooflux knowledge matrix [--check] [--output FILE]`

Generates the matrix markdown (default output
`docs/planning/VERSION_COMPATIBILITY_MATRIX.md`). `--check` writes nothing and exits `1` if the
committed file differs from the generated content.

## `odooflux knowledge migrate-seed --register FILE --research FILE` (one-off)

Parses the planning register tables and the feature 004 research table into evidence and gap
JSON files. It is idempotent: running it twice produces no changes. The command is removed after
P3 exits.
