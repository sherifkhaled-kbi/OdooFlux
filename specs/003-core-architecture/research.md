# Research: Core Architecture (P2)

Architecture decisions are already recorded as ADRs in
[ARCHITECTURE_DECISIONS.md](../../docs/planning/ARCHITECTURE_DECISIONS.md). This file covers the
P2-specific choices.

## R-01 Package bootstrap without shadowing (ADR-001)

- **Decision**: Create `src/odooflux/__init__.py` and sub-package `__init__.py` files in P2. The root
  `odooflux.py` becomes:

  ```python
  sys.path.insert(0, <repo>/src)
  from odooflux.cli import main
  ```

  It is executed as a script only. When the package is installed via pyproject, the console
  script `odooflux` points at `odooflux.cli:main`.

  Name clash: running `python odooflux.py` puts the repo root on `sys.path[0]`, so
  `import odooflux` would resolve to the root script itself. The launcher therefore inserts
  `src/` **before** the root and removes the root entry, and a test asserts
  `odooflux.__file__` is under `src/` (TST-003-040).
- **Alternatives**: Renaming the root script was rejected, because the brief forbids changing the
  entry point before cut-over.

## R-02 Contracts as dataclasses and Protocols

- **Decision**: `dataclasses` (frozen where immutable) for data contracts; `typing.Protocol` for
  behaviour (`Rule`, `Validator`, `ParserAdapter`, `RuntimeEnvironment`, `AIProvider`,
  `Renderer`). `CONTRACT_VERSION = 1` lives in `core/contracts/__init__.py`.
- **Rationale**: stdlib only; structural typing lets plugins avoid inheriting from core classes.

## R-03 Registries

- **Decision**: One generic `Registry[T]` with `register(entry, *, contract_version)`, `get(id)`,
  `all()` (sorted by ID for determinism), and contract checks. Built-ins register at import of
  `odooflux.builtins`. External plugins load only from explicit `--plugin module:attr` or the
  config file (never by entry-point auto-discovery, which is a security choice).
- **Alternatives**: `importlib.metadata` entry points were rejected for P2 (implicit code
  execution); this may be reconsidered in P9.

## R-04 Version data before P3

- **Decision**: Ship `src/odooflux/knowledge/versions.json` with 12.0–19.0 records. Research status
  comes from [VERSION_COMPATIBILITY_MATRIX.md](../../docs/planning/VERSION_COMPATIBILITY_MATRIX.md),
  Python ranges from EV-125, and online releases from EV-001 headings (ADR-007). P3 adds schema
  validation and evidence links.
- **Note**: A minimal stdlib schema check (required keys, types, enum values) is enough for P2.

## R-05 Workspace and promotion (ADR-013)

- **Decision**: `runs/<run-id>/work/<module>/` is a `copytree` of the source (symlinks not
  followed). Steps run in memory on Documents loaded from `work/`. Validated outputs are written
  to `work/`. Promotion per module:
  1. verified backup to `runs/<run-id>/backup/<module>/`;
  2. for each changed file, a temp file in the target directory, then `os.replace`, then a run-log
     entry;
  3. on any failure, restore the already-promoted files of that module from backup.
- Checkpoint: `runs/<run-id>/state.json` updated atomically after each module with
  `{module: status, files: [hashes]}`.

## R-06 Run log format

- **Decision**: JSON Lines, extending the P0 `odooflux.runlog/0` format to `odooflux.runlog/1`.
  New fields: `edit_ids` and `step`. P0 logs remain readable by rollback (reader accepts both).

## R-07 Legacy rule adapter

- **Decision**: `rules/shared/legacy_adapter.py` wraps each legacy rule tuple as a `Rule`:
  - step `legacy-<from>-<to>`;
  - maturity `DETECT_ONLY` unless the legacy fixer exists and P0 kept it;
  - evidence = the EV IDs from P0 messages, or `[]` with status `UNVERIFIED`.

  The P3 evidence requirement (REQ-EVD-001) is waived **only** for `legacy-*` rules, and only
  until P5. Each such waiver is listed in the report.
- **Rationale**: Characterisation parity (REQ-ARC-004) without blocking on P5.

## R-08 Determinism

- Sort findings by (path, start, rule_id); sort edits by (path, start).
- Finding IDs are SHA-256 of `rule_id|path|start|end|matched_text` (first 16 hex).
- `json.dumps(sort_keys=True, ensure_ascii=False, indent=2)`; timestamps confined to
  `started_at`, `finished_at`, and `durations`.

## R-09 Benchmark generator

- **Decision**: `tests/benchmarks/generate_repo.py` creates N synthetic modules (default 300 × 30
  files: models, views, a manifest, JS) from templates with a fixed seed. `bench_analyze.py`
  records wall time and `resource.getrusage` peak RSS (POSIX; `tracemalloc` fallback).

## R-10 Import-graph enforcement

- **Decision**: A test walks `src/odooflux/**.py` with `ast`. For core packages, every import must
  be in `sys.stdlib_module_names` (Python ≥3.10) or start with `odooflux.` and target a core
  package. Adapter packages are exempt but may not be imported by core.
