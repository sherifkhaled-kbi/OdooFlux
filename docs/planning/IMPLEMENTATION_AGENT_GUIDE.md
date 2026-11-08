# Implementation Agent Guide

Entry point for any agent (human or AI) implementing an OdooFlux roadmap phase. Read this
document fully before touching code.

Tooling facts verified during planning: Spec Kit **1.3.1**, Claude integration, `sh` scripts,
sequential feature numbering, **no git branches are created by Spec Kit** (ADR-015). The active
feature is selected by `.specify/feature.json`.

## 1. Identify the next approved phase

1. Open [SPECKIT_READINESS.md](SPECKIT_READINESS.md). The next phase is the lowest-numbered
   phase whose readiness is `READY`. A phase in `READY_WITH_DEPENDENCIES` is ready only once every
   phase listed under its dependencies has recorded exit evidence.
2. Check [PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md): every decision
   (`D-NN`) listed as blocking that phase must be marked approved. If not, **stop** and ask the
   maintainer.
3. Confirm the previous phase's exit evidence exists in its feature directory
   (`specs/<NNN>/verification/EXIT_EVIDENCE.md`, see §6).

## 2. Files to read (in this order)

1. `.specify/memory/constitution.md` (version 2.0.0). Principles I–X are binding.
2. The phase handoff: `docs/planning/phase-handoffs/PHASE_<NN>_*.md`.
3. The feature: `specs/<NNN>-<name>/spec.md`, `plan.md`, `research.md`, `data-model.md` (if
   present), `contracts/` (if present), `quickstart.md`, `tasks.md`, `checklists/`.
4. [architecture/CONTRACTS.md](architecture/CONTRACTS.md) and
   [ARCHITECTURE_DECISIONS.md](ARCHITECTURE_DECISIONS.md).
5. For any Odoo-specific behaviour: [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md)
   (and, from P3 on, the knowledge base under `src/odooflux/knowledge/`).

## 3. Inspect prerequisites

From the repository root:

```bash
# Point Spec Kit at the phase's feature directory (example: P0)
printf '{\n  "feature_directory": "specs/001-safety-stabilization"\n}\n' > .specify/feature.json

# Verify plan.md and tasks.md exist and list available docs
.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks

# Baseline: the full default suite must pass before you start (from P1 onwards)
python -m unittest discover -s tests
```

Also check that:
- the working tree is clean, or the user has approved working on top of local changes;
- the entry criteria in the handoff and in [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)
  are met;
- every checklist in `specs/<NNN>/checklists/` is fully checked. `/speckit-implement` stops and
  asks if one is not.

## 4. Follow the tasks

- The implementation command is **`/speckit-implement`** (Claude Code skill
  `speckit-implement`). It reads `.specify/feature.json`, runs
  `check-prerequisites.sh --json --require-tasks --include-tasks`, gates on checklists, and executes
  `tasks.md` phase by phase. Planning agents never run it; implementation agents run it only
  for the approved phase.
- Execute tasks in the order and dependency structure of `tasks.md`. Tests are written first
  and must fail before implementation (Principle V).
- Every task line references `REQ-…` and, for tests, `TST-…`. Do not add work that has no
  requirement; if you find missing work, see §8.
- Do not implement anything listed under "Prohibited changes" in the handoff. Do not edit
  another phase's scope.
- Odoo-specific behaviour must come from evidence records. If a needed fact is not in the
  register or knowledge base, stop and report a research gap (§8). Never rely on memory.

## 5. Run the required tests

| Suite | Command | When |
|---|---|---|
| Default (offline) | `python -m unittest discover -s tests` | Every task that changes code; before marking any task done |
| Single module | `python -m unittest tests.unit.test_<name>` | While iterating |
| Runtime (containers) | `ODOOFLUX_RUNTIME_TESTS=1 python -m unittest discover -s tests/runtime` | P7+, when D-03 is approved and Docker is available |
| AI (live provider) | `ODOOFLUX_AI_TESTS=1 python -m unittest discover -s tests -p "test_ai_live*.py"` | P6, with credentials from environment only |
| Benchmarks | `python -m unittest discover -s tests/benchmarks` | P2 baseline, P9 |

The exact suite names per phase are in each `quickstart.md`.

## 6. Record verification evidence

Create `specs/<NNN>-<name>/verification/EXIT_EVIDENCE.md` containing:
- commit SHA(s) implementing the phase;
- for each exit criterion: the command run, the date, its result (pass/fail counts), and a
  link to the test file;
- for each `TST-…` ID: pass/fail;
- benchmark numbers (if the phase defines any), with machine description;
- any deviations from the plan, with the approving decision.

Raw logs may be stored under `specs/<NNN>-<name>/verification/logs/`, with secrets redacted.

## 7. Update task status

- Mark a task `[X]` in `tasks.md` only when its "Done when" criterion is met and its tests pass.
- Do not edit checklist markers in `checklists/` (they are review artefacts).
- Update the phase row in [SPECKIT_READINESS.md](SPECKIT_READINESS.md) to note
  "Implementation complete – exit evidence: <link>" when all exit criteria pass.

## 8. Report failures and stop conditions

Stop and request clarification (do not redesign) when:
- an entry criterion or a blocking decision `D-NN` is not satisfied;
- a task is ambiguous, contradicts the spec/contract, or requires changing a contract
  (`CONTRACT_VERSION`);
- an Odoo-specific fact is needed but has no evidence (open a gap `G-R-NN`);
- a test cannot be made to pass without weakening an acceptance criterion;
- the work would modify files outside the phase's expected files, or customer data;
- a constitution principle would be violated.

Report failures as a short note in `verification/EXIT_EVIDENCE.md` (section "Blocked") with the task ID,
symptom, evidence, and the question to the maintainer.

## 9. Hand off to the next phase

1. All tasks are `[X]` and all exit criteria are recorded as passing.
2. `python -m unittest discover -s tests` passes on a clean checkout.
3. Readiness dashboard updated (§7).
4. Update `.specify/feature.json` only when the next phase is started, not before.
5. Summarise in the next handoff's "Repository context" what changed (new files, contracts),
   if it differs from the plan.

## 10. Quick reference

| Phase | Feature directory | Handoff |
|---|---|---|
| P0 | `specs/001-safety-stabilization` | [PHASE_00_SAFETY.md](phase-handoffs/PHASE_00_SAFETY.md) |
| P1 | `specs/002-test-foundation` | [PHASE_01_TESTING.md](phase-handoffs/PHASE_01_TESTING.md) |
| P2 | `specs/003-core-architecture` | [PHASE_02_ARCHITECTURE.md](phase-handoffs/PHASE_02_ARCHITECTURE.md) |
| P3 | `specs/004-official-source-intelligence` | [PHASE_03_OFFICIAL_SOURCES.md](phase-handoffs/PHASE_03_OFFICIAL_SOURCES.md) |
| P4 | `specs/005-structured-transformations` | [PHASE_04_TRANSFORMATIONS.md](phase-handoffs/PHASE_04_TRANSFORMATIONS.md) |
| P5 | `specs/006-version-compatibility-rules` | [PHASE_05_VERSION_COMPATIBILITY.md](phase-handoffs/PHASE_05_VERSION_COMPATIBILITY.md) |
| P6 | `specs/007-ai-assistance` | [PHASE_06_AI.md](phase-handoffs/PHASE_06_AI.md) |
| P7 | `specs/008-runtime-behavioral-validation` | [PHASE_07_VALIDATION.md](phase-handoffs/PHASE_07_VALIDATION.md) |
| P8 | `specs/009-reporting-ux` | [PHASE_08_REPORTING.md](phase-handoffs/PHASE_08_REPORTING.md) |
| P9 | `specs/010-hardening-release` | [PHASE_09_HARDENING.md](phase-handoffs/PHASE_09_HARDENING.md) |
