# Human review fragment: workstream D (feature 009 reporting and UX)

Register IDs are proposed (`WSD-nn`); the orchestrator assigns final IDs when consolidating. Nothing here records an
approval. Every item is `PENDING_HUMAN_REVIEW` under ADR-019. Reviewer qualifications are for a human reviewer; no agent
may sign. Reports built from provisional corpora carry a `provisional` field and render a `PROVISIONAL RUN` banner; the
orchestrator must supply it (`build_report(..., provisional=...)` or `state["provisional"]`), the CLI does not set it yet.

## WSD-01: Mockup parity (009 T025)

- Task / requirement: 009 T025 (original stays unchecked); REQ-REP-002, REQ-REP-006. Technical part implemented and verified.
- Component: `src/odooflux/reporting/terminal/ansi.py`, `src/odooflux/reporting/html/html.py`, mockups in `docs/planning/REPORTING_AND_UX.md` sections 3 and 4.
- What to review: run the CLI with `--ui ansi` and `--html` on a real module and compare each mockup (progress, per-module summary, file detail with evidence, rejected edits, verification scope, AI usage, recovery, HTML page outline) with the output. Decide whether each documented deviation is acceptable: (1) plan line shows no per-step research status; (2) progress is derived from the final model, with no live detect/fix counters; (3) verification scope lists layers, not sub-validators such as the RNG check; (4) recovery has no backup path and no resume line; (5) layer outcomes are words (`L1 PASS`), not check marks; (6) narrow widths (below 110 columns) use a stacked per-module layout instead of the table.
- Why: parity with a design mockup is a judgement about usability and wording, not something a test can certify.
- Evidence and tests available: `tests/unit/reporting/test_mockup_checklist.py` (required sections and labels), `tests/unit/reporting/test_terminal_snapshots.py` with 60 snapshots in `tests/golden_fixtures/reports/snapshots/` (10 golden models, colour and plain, widths 60/80/120), `tests/unit/reporting/test_html.py`.
- Risk if unapproved: the output may be correct and still not match what the project owner wants; wording or layout rework after sign-off.
- Reviewer qualifications: project owner or a maintainer who owns the UX design; one daily CLI user of the tool.
- Certification impact: blocks certification of 009 T025 only; no effect on counts, schema or exit codes.

## WSD-02: SARIF consumer acceptance

- Task / requirement: 009 T012/T015 (technical part done), REQ-REP-004, SC-001.
- Component: `src/odooflux/reporting/exporters/sarif.py`.
- What to review: upload a SARIF file produced by `--sarif` to the code-scanning UI the team uses (for example GitHub code scanning) and confirm results appear with the right level, file and line, and that the rule help links work. Confirm that two modules with the same relative file name and line do not collapse, and that `kind: pass` results with `--sarif-include-fixed` are shown or ignored sensibly.
- Why: validity against the SARIF 2.1.0 schema does not prove a given consumer accepts or displays the file. Consumer-specific limits (result count caps, size caps, required fields such as `endLine`) are not tested. The exporter omits `endLine`/`endColumn` and rule `properties.step` because the model carries no such data.
- Evidence and tests available: `tests/unit/reporting/test_sarif.py` validates every golden model against the vendored official SARIF 2.1.0 schema (`tests/golden_fixtures/schemas/`, retrieved 2026-11-07, sha256 in `PROVENANCE.json`) with an in-repo stdlib validator; level mapping, fingerprints, URI encoding and invocation exit code are asserted. No upload to any consumer was tested.
- Risk if unapproved: CI users may see rejected uploads, missing annotations or truncated results.
- Reviewer qualifications: CI or DevSecOps engineer who operates the code-scanning platform.
- Certification impact: blocks any claim of "accepted by code-scanning UIs"; does not affect the JSON report or exit codes.

## WSD-03: Terminal rendering on real terminals

- Task / requirement: 009 T007/T010/T011, REQ-REP-002, F-REP-2.
- Component: `src/odooflux/reporting/terminal/ansi.py`, `rich_adapter.py`, `options.py` (`display_width`, `sanitize_text`).
- What to review: view colour and plain output in at least one Linux terminal, macOS Terminal or iTerm, Windows Terminal, and a CI log viewer; with `NO_COLOR=1`, at 60/80/120 columns, with East Asian and combining characters in module names, and with `--ui rich` when `rich` is installed. Check that colours are readable on light and dark themes and that nothing relies on colour alone.
- Why: snapshots prove the bytes, not how a terminal draws them. Wide-character width uses `unicodedata.east_asian_width`, which can differ from a terminal's own tables (emoji, ambiguous width). Rich output was tested only with a throwaway install, not across rich versions.
- Evidence and tests available: `test_terminal_snapshots.py` (layout identical in colour and plain, every line within the width), `test_terminal_escaping.py` (ANSI and control-character injection neutralised), `test_terminal_rich.py` (rich 5/5 when installed, fallback when absent).
- Risk if unapproved: misaligned columns or unreadable colours on some terminals; hostile-terminal behaviour beyond the tested escape classes is unknown.
- Reviewer qualifications: developer who uses the CLI on the target platforms; for the escaping part, a security reviewer familiar with terminal injection.
- Certification impact: blocks certification of terminal UX on real terminals (009 T007/T010 certification part); none on data.

## WSD-04: Exit-code default and legacy mapping (D-10)

- Task / requirement: 009 T016, FR-006, REQ-REP-005, SC-005.
- Component: `src/odooflux/cli/exit_codes.py`, `src/odooflux/cli/report_outputs.py`, option `--exit-codes {legacy,v1}`.
- What to review: decide when the default flips from the characterised legacy mapping to the documented v1 table. Under v1 a module that cannot run L3 (for example no manifest) is `BLOCKED`, exit 4; the legacy mapping returns 0 or 3 for it. Two existing tests encode the legacy result: `tests.regression.test_p0_reporting.ExitCodeTests.test_fail_on_thresholds` and `tests.contract.test_plugin_kinds.PluginKindsTests.test_validator_effect_rejects_the_edit`.
- Why: FR-006 says exit codes follow the table; D-10 says the legacy mapping stays for one minor release. Flipping the default needs an owner decision and an update of those tests.
- Evidence and tests available: `tests/unit/cli/test_exit_codes.py` (full table, `--fail-on` matrix, exhaustive precedence), `tests/integration/reporting/test_cli_exports.py` (default legacy, v1 opt-in), `tests/regression/test_reporting_findings.py` (F-REP-3, F-VER-4).
- Risk if unapproved: CI users get the old mapping by default; users of `--fail-on-status` or `--exit-codes v1` get the new table.
- Reviewer qualifications: project owner (policy); a CI maintainer for impact.
- Certification impact: blocks declaring FR-006 fully met by default behaviour.

## WSD-05: Diff export limits

- Task / requirement: 009 T019, REQ-REP-004, SC-003.
- Component: `src/odooflux/reporting/exporters/diff.py`, `--diff`.
- What to review: (1) a dry run exports an empty patch because the orchestrator computes edits only in mode `fix`; decide whether dry-run planned edits must be computed (an orchestrator change outside workstream D). (2) The patch is built from the pre-run backup, so `--fix --no-backup --diff` is refused. (3) A module with rejected edits or a blocked module is excluded as a whole and listed in the index. (4) A rename is exported as delete plus create.
- Why: US3 acceptance wording says "Given a dry-run", which the current pipeline cannot satisfy.
- Evidence and tests available: `tests/integration/reporting/test_diff_apply.py` (`patch -p1`, byte-for-byte, LF, CRLF, no final newline, rename, every corpus fixture including the provisional 17.0 one); quickstart record.
- Risk if unapproved: reviewers cannot get a diff before writing.
- Reviewer qualifications: maintainer of the orchestrator; a reviewer who reads patches daily.
- Certification impact: blocks US3 acceptance scenario 1 as written (dry-run).

## WSD-06: Offline HTML in real browsers and untrusted-content handling

- Task / requirement: 009 T020/T021/T022, REQ-REP-003, REQ-SEC-004.
- Component: `src/odooflux/reporting/html/html.py`.
- What to review: open the file offline (network disabled) in a current Chrome/Firefox/Safari, print it, and check the sections, the `<details>` collapsing and the PROVISIONAL banner; review escaping against payloads from your own corpus.
- Why: tests parse the HTML with the stdlib; they do not render it or run a browser's HTML parser quirks. No content-security-policy header can be set on a file; the file relies on escaping alone.
- Evidence and tests available: `test_html.py` (no scripts, no external resources, only https evidence anchors), `test_html_escaping.py` (seven payload classes in every text field), cross-renderer count test.
- Risk if unapproved: a browser-specific parsing quirk could make an escaped payload active; layout may differ on print.
- Reviewer qualifications: web security reviewer for the escaping; any developer for the layout.
- Certification impact: blocks certification of the HTML report as safe for untrusted module content.

## WSD-07: Verification wording and provisional label

- Task / requirement: 009 T008, FR-007, REQ-BIZ-003; ADR-019 item 4.
- Component: terminal and HTML scope blocks, `provisional` model field.
- What to review: the "Why not verified" and Limit wording (does it avoid over-claiming), that UNAVAILABLE reads differently from FAIL, and that a run using a provisional corpus is labelled. The label appears only when the producer of the model supplies `provisional`; the orchestrator does not set it yet.
- Why: honesty of claims is a judgement call and the provisional wiring is outside workstream D.
- Evidence and tests available: `test_terminal_sections.py`, `test_html.py`, `test_model_extensions.py` (unrun layers never PASS, a module blocked before analysis shows L1/L2 SKIPPED).
- Risk if unapproved: a provisional run could be shown without the label.
- Reviewer qualifications: project owner; QA reviewer.
- Certification impact: any support statement based on the provisional corpus must say so; blocks removal of the provisional label.
