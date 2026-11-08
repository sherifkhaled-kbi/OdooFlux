# Implementation Plan: Official Source Intelligence

**Branch**: `004-official-source-intelligence` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-official-source-intelligence/spec.md`

## Summary

Deliver the knowledge base that every migration rule depends on:
- JSON data for versions, revisions, allow-list, evidence, step research, gaps, and rule
  metadata;
- a stdlib schema validator;
- loader integration that enforces evidence and caps rule maturity;
- an offline refresh tool;
- a deterministic matrix generator;
- migration of the planning seed (EV-001…EV-212, G-R-01…G-R-19).

Design decisions are in [research.md](research.md); data shapes are in [data-model.md](data-model.md).

## Technical Context

**Language/Version**: Python 3.10+ (tool interpreter; constitution Technical Constraints)
**Primary Dependencies**: Python standard library only (`json`, `re`, `subprocess` for `git show`, `pathlib`, `hashlib`)
**Storage**: JSON files under `src/odooflux/knowledge/`
**Testing**: `unittest`; fixture git repositories created at test time in a temp directory
**Target Platform**: Linux/macOS/Windows developer machines and CI
**Project Type**: CLI tool (library + command group)
**Performance Goals**: Full validation < 5 s (SC-006); refresh of all records < 60 s with local clones
**Constraints**: No network in tests; core must not import non-stdlib packages (REQ-ARC-001)
**Scale/Scope**: ~250–2,000 evidence records over the product lifetime; 8–9 versions; 7–8 steps

## Constitution Check (v2.0.0)

| Principle | Check | Status |
|---|---|---|
| I Dependency-light core | Stdlib only; JSON instead of YAML | PASS |
| II Safe, reversible | Refresh is dry-run by default; `--apply` only touches knowledge files | PASS |
| III Deterministic first | No AI involvement in evidence | PASS |
| IV Honest reporting | Matrix generated from data; cannot over-claim (FR-009) | PASS |
| V Test-backed | Every validator code path and refresh outcome has tests | PASS |
| VI Official evidence only | Allow-list + immutable revisions enforced (FR-002) | PASS |
| VII Layered validation | `VERIFIED` requires a runtime test reference | PASS |
| VIII Business logic limits | Risk field + `review-only` transformations recorded | PASS |
| IX Modular | New versions are data-only (SC-003) | PASS |
| X Phase delivery | Depends on P2 exit; P1 data entry allowed | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/004-official-source-intelligence/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/knowledge-cli.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
src/odooflux/knowledge/
├── __init__.py                  # loader API: load_knowledge(path) -> KnowledgeBase
├── validator.py                 # stdlib schema checker + allow-list/revision/ID checks
├── refresh.py                   # location re-verification against local clones
├── matrix.py                    # deterministic matrix generator
├── seed_migration.py            # one-off planning-register importer (removed after P3)
├── schemas/*.schema.json
├── official_sources/{allow_list.json, revisions.json}
├── evidence/EV-*.json
├── compatibility/{versions.json, <step>.research.json}
└── gaps.json
src/odooflux/rules/shared/loader.py      # (exists from P2) — extended: evidence enforcement, maturity cap
src/odooflux/cli/knowledge.py            # `odooflux knowledge {validate,refresh,matrix,migrate-seed}`
tests/unit/knowledge/                    # validator, loader cap, matrix, refresh unit tests
tests/integration/knowledge/             # CLI tests with fixture repos
tests/golden_fixtures/knowledge/         # fixture knowledge bases (valid/invalid/version-20)
docs/planning/VERSION_COMPATIBILITY_MATRIX.md   # becomes generated output
docs/planning/research/RESEARCH_PROCEDURE.md    # implementer procedure (new)
```

**Structure Decision**: Single project per [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md); knowledge code and data co-located under `src/odooflux/knowledge/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| One-off `migrate-seed` command | Avoids hand-transcribing 70+ records (error-prone) | Manual transcription cannot be verified by a reconciliation test |
