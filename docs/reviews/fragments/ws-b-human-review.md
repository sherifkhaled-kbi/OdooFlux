# Register fragment: workstream B (pipeline wiring and packaging)

Status of every item: PENDING_HUMAN_REVIEW. Nothing here records an approval. IDs are provisional (`WSB-nnn`);
the orchestrator assigns the final `FHR-nnn` on consolidation. Technical parts are IMPLEMENTED and VERIFIED
(ADR-019); the certification parts below stay open.

## WSB-001 REQ-MAN-002 wording and the version-prefix opt-out

- **Task / requirement:** 006 T084 (certification part), FR-019, REQ-MAN-002, OD-4.
- **Component:** `specs/001-safety-stabilization/spec.md` (REQ-MAN-002 text), rule `*.manifest.version-prefix`, `src/odooflux/core/orchestrator/run_inputs.py`.
- **What to review:** REQ-MAN-002 reads "unless opts out" while the rule is opt-in and DETECT_ONLY. Decide the wording (opt-in matches current behaviour) and whether any FIX_ENABLED promotion is ever wanted. The wording was NOT changed by this workstream.
- **Why:** the wording and the shipped behaviour disagree; only the owner can settle which governs. Automatic prefix rewriting (D-A3) is not approved (ADR-018).
- **Evidence / tests:** `tests/integration/test_planner_wiring.py` (target reaches the rule through the CLI only with `--enable-rule`; the written manifest is byte-identical with and without the opt-in under `--fix`; missing run input yields an INFO gap). `tests/unit/rules/test_bind_run_params.py`.
- **Risk:** LOW. Detect-only INFO finding, opt-in, no fixer is ever bound on this path.
- **Reviewer qualifications:** project owner or maintainer with authority over requirement text.
- **Certification impact:** none on release readiness while it stays opt-in; a change to FIX_ENABLED would need a new decision, evidence and golden tests.

## WSB-002 Wheel contents and size

- **Task / requirement:** 010 T025-T027 (certification part), FC A-10, OD-5.
- **Component:** `pyproject.toml` (`package-data`), `MANIFEST.in`, `tests/integration/packaging/`.
- **What to review:** the choice to ship all knowledge data in the wheel: 246 JSON files, wheel `odooflux-0.2.0-py3-none-any.whl` is 1,382,820 bytes (405 entries; `src/odooflux/knowledge` is about 6.7 MB on disk, mostly 200 evidence records). Alternatives: ship evidence separately or trim it.
- **Why:** the loaders read these files at runtime; before the fix 244 assets were missing from the wheel, so an installed tool could not load its own knowledge.
- **Evidence / tests:** `tests/integration/packaging/test_wheel_assets.py` (offline build via `pip wheel --no-deps --no-build-isolation`; compares source assets and files opened by the real loaders, traced with an audit hook, against the wheel; red before the fix with 244 missing, green after). `test_wheel_install.py` (opt-in `ODOOFLUX_PACKAGING_INSTALL=1`): ran once, 4 tests OK: fresh venv without system site-packages, `pip install --no-index --no-deps` of the wheel, imports from site-packages, `odooflux --help`, `odooflux knowledge validate` (exit 0), analysis of the p0 fixture from a directory outside the repo with a JSON report that has findings.
- **Risk:** LOW to MEDIUM. Distribution size and the question of whether evidence text may be redistributed under its upstream licences (not assessed here).
- **Reviewer qualifications:** maintainer with packaging and licensing responsibility.
- **Certification impact:** none for framework completion; a licensing finding could block publication of the wheel.

## WSB-003 Dependency scanner now runs by default in every migrate run

- **Task / requirement:** 006 T082, FR-020, REQ-DEP-001, FR-022.
- **Component:** `src/odooflux/dependencies/scan.py`, `core/orchestrator/run.py` (`build_run_context`).
- **What to review:** the scanner is on by default (no flag). It adds `*.deps.unknown-dependency` and `*.deps.removed-with-successor` findings (DETECT_ONLY, never an edit) next to the L3 `integrity.missing_module` finding for the same dependency, so one unresolved dependency can appear twice with different rule ids. Decide whether to de-duplicate or keep both. The successor data comes from two evidence-backed entries only (EV-520, EV-521); every other removed module reports "no successor known".
- **Why:** changes visible report content (more findings) for modules with unresolved dependencies. The 17.0 provisional corpus is unaffected (no finding).
- **Evidence / tests:** `DependencyScannerWiringTests` in `tests/integration/test_planner_wiring.py` (successor reaches the CLI report; sibling modules of one run are not flagged; missing core list gives an INFO gap).
- **Risk:** LOW. Findings only.
- **Reviewer qualifications:** maintainer familiar with the report model and the L3 integrity checker.
- **Certification impact:** report-count expectations in the final golden set must include these findings.

## WSB-004 New CLI option `--enable-rule`

- **Task / requirement:** 006 T080, FR-017, FR-019.
- **Component:** `src/odooflux/cli/main.py`, `cli/migrate.py` (minimal edits), `builtins.py` (registers `run_rule_binder` on the registries).
- **What to review:** the opt-in mechanism and name (`--enable-rule RULE_ID`, repeatable; an id that is not a run-input rule is a usage error, exit 2). It is a contract addition to `contracts/cli.md`, not yet documented there.
- **Why:** the requirement says version-prefix stays opt-in, and the CLI had no opt-in channel.
- **Evidence / tests:** `VersionPrefixWiringTests`; `tests/integration/test_cli_contract.py` still passes (legacy options unchanged).
- **Risk:** LOW.
- **Reviewer qualifications:** CLI contract owner.
- **Certification impact:** the CLI contract document needs a matching line before release.
