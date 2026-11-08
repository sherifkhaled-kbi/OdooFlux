# Verification evidence: Official Source Intelligence (P3, feature 004)

Run from the repository root with `python3` (this sandbox has no `python` alias). Knowledge data
is untracked in git (`docs/` and `src/odooflux/knowledge/` are new), so immutability of the data
during the dry-run was checked by hashing every file before and after.

## Results

| Criterion | Evidence | Result |
|---|---|---|
| SC-001 (all records validate; count = files) | `python3 odooflux.py knowledge validate` → `records=52 rules=0 errors=0 warnings=0`, exit 0 | Pass |
| SC-002 (every register/research ID exists as data) | `test_seed_reconciliation`: 52 EV IDs and 19 G-R IDs exist; claims and cited paths match | Pass |
| SC-003 (version 20.0 is data only) | `test_adding_20_is_data_only_and_appears_in_the_graph`; P2 `test_synthetic_version` | Pass |
| SC-004 (refresh 4/4 cases) | `test_four_cases_are_classified`: unchanged, moved (1→13), missing (file deleted), unavailable (unknown SHA) | Pass |
| SC-005 (byte-identical generation; committed check) | `test_two_generations_are_byte_identical`; `python3 odooflux.py knowledge matrix --check` → exit 0 | Pass |
| SC-006 (validation < 5 s) | `validate_knowledge` on shipped data: 0.01 s; opt-in test `test_full_validation_under_five_seconds` | Pass |

Quickstart (`specs/004-official-source-intelligence/quickstart.md`):

1. `validate` → `errors=0`, 52 records.
2. `python3 -m unittest discover -s tests/unit/knowledge` and `tests/integration/knowledge` → OK.
3. `matrix --check` → exit 0.
4. Refresh dry-run against a pinned clone (`/tmp/p3/repos/odoo-18.0`, commit 75d6abe, not a fresh full
   clone): 111 locations checked, 38 unchanged, 73 unavailable (the other branches' commits are not in that
   clone), 0 moved, 0 missing. Knowledge files byte-identical before and after (sha256 over the tree).

Full suite: `python3 -m unittest discover -s tests -p "test_*.py"` → 193 tests OK (2 opt-in benchmarks skipped).

## Verification of the planning register (new finding)

The seed build checked every present location against its pinned commit. One claim failed:

- **EV-204 (UNVERIFIED).** The register says Odoo's view-arch validation uses `lxml.etree.RelaxNG`
  at `odoo/addons/base/models/ir_ui_view.py` lines 9 and 301–302. At the pinned 18.0 commit, `RelaxNG` does
  not occur in that file. Line 9 is `import re`. Only the lxml import (line 13) is confirmed. The record is
  `UNVERIFIED` with a note; re-research before any rule depends on it.

## Deviations from the task list

| Task | What was done | Why |
|---|---|---|
| T010 | Rule loader (`rules/shared/loader.py`) enforces evidence and caps maturity. Capped rules are returned as warnings to the caller. They are not yet wired into the migration run report. | Migration does not consume rule metadata until feature 006 populates it. |
| T014 | `KnowledgeBase.versions` reads `compatibility/versions.json`, the same file the P2 registry loader reads. No second copy. | One source of truth. |
| T017 | Records are verified mechanically (every location checked at its SHA). `detection_method`, `proposed_transformation`, `risk`, and `required_validation` were set per record from the register's transformation and risk columns, not individually curated. | Time; the fields are advisory until rules use them. Recorded here. |
| T023 | `docs/planning/VERSION_COMPATIBILITY_MATRIX.md` is regenerated. Statuses and evidence IDs match the original planning table. **Lost:** the original file was overwritten before a copy was saved, and `docs/` is untracked, so no git copy exists. Free-text annotations on gap cells (for example "(sudo semantics)") and some sentence wording are not in the regenerated file. The annotations are not statuses or evidence IDs. | Caught after the overwrite. Disclosed here. |
| T016, T025 | The seed importer ran once, then was removed from the package. A copy is kept outside the repository at `/tmp/p3/archive/seed_migration.py`. Its idempotence test was removed with it. The reconciliation test keeps the migrated data tied to the register. | Per T025. |
| T019/T020 | Refresh uses only commits already in the clone (`GIT_NO_LAZY_FETCH`-equivalent check via a local object listing). Candidate-path search is opt-in (`--search-candidates`): a whole-tree search took 18 s per location on a partial clone. | Measured. |
| T002 | `docs/planning/research/RESEARCH_PROCEDURE.md`. The peer check (a second agent following it) has not been run. | Needs a person. |

## Unresolved risks

- Refresh results depend on the clone: a branch's locations are checked only where that branch's commit is
  present. One clone per branch is needed for a full refresh.
- Registry-level claims in `versions.json` (`python_min`, `online_releases`) have no per-field evidence IDs yet.
- The matrix's rule catalogue (38 candidates) is data but not yet linked to rule metadata (feature 006).

`.specify/feature.json` now points at `specs/004-official-source-intelligence` (it was left on 001).
