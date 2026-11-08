# Research: Test Foundation (P1)

## R-01 Runner and layout

- **Decision**: stdlib `unittest`, discovery from `tests/`, one package per suite directory
  (`__init__.py` in `tests/` subfolders only). Suites: `unit`, `integration`, `regression`,
  `contract` (empty until P2), `runtime` (opt-in), `benchmarks` (opt-in).
- **Rationale**: ADR-016; constitution I keeps the core stdlib-only.
- **Alternatives**: pytest was rejected as a requirement (it is a dependency), but it remains
  usable as a runner.

## R-02 Characterisation strategy

- **Decision**: Black-box via subprocess (`python odooflux.py …`), not by importing internals.
  Normalise the JSON report:
  - replace absolute paths with `<MODULE>`;
  - replace `timestamp` and `elapsed_seconds` with constants;
  - sort issues by (file, line, category).

  Compare fixed trees by relative path and SHA-256.
- **Rationale**: Survives the P2 restructuring, because only the CLI contract is pinned
  (REQ-ARC-004).
- **Alternatives**: Importing `odooflux` functions was rejected: it breaks at cut-over and pins
  internals.

## R-03 Fixture content per source version

Constructs are chosen only where an evidence record exists, or where the construct is generic.

| Fixture | Constructs (evidence) |
|---|---|
| `v12` | `@api.multi`, `@api.one` (EV-101), `.sudo(user)` (EV-103), `Warning` alias import (EV-110), manifest `qweb` key (EV-124 is 14.0; for 12.0 recorded as UNVERIFIED and used only as a detection sample) |
| `v13` | `.sudo(flag)`/`with_user` (EV-103), `Warning` (EV-110), `attrs` |
| `v14` | Audit Appendix A module (from P0) |
| `v15` | Manifest `assets` (EV-123), `fields_view_get` override (EV-107) |
| `v16` | `<act_window>` tag (EV-117), `name_get` (EV-011, EV-104), `SavepointCase` test (EV-111), field `states=` (EV-108) |
| `v17` | `<tree>` view (EV-112), `numbercall` cron (EV-113), `group_operator` (EV-118), `kanban-box` (EV-119), `rpc` service usage (EV-120), `user_has_groups` (EV-105) |
| `v18` | `groups_id` usage (EV-114), `type='json'` route (EV-115), `_sql_constraints` (EV-116), `@api.returns` (EV-102), `read_group` (EV-004) |

Fixtures are inputs for *current* (legacy) behaviour. They also provide samples for P5 rules.

## R-04 Opt-in gating

- **Decision**: A `tests/_support/optin.py` module with decorators `requires_runtime`,
  `requires_network`, and `requires_ai` that use `unittest.skipUnless(os.environ.get(...) == "1", reason)`.

## R-05 Byte-exact fixture storage

- **Decision**: `tests/golden_fixtures/.gitattributes` with `* -text` prevents EOL conversion
  (edge case in the spec).
