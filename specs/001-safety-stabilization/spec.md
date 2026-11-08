# Feature Specification: Safety Stabilization (Phase P0)

**Feature Branch**: `001-safety-stabilization`

**Created**: 2026-11-06

**Status**: Draft — planned, not implemented

**Input**: Roadmap phase P0 ([IMPLEMENTATION_ROADMAP.md](../../docs/planning/IMPLEMENTATION_ROADMAP.md#p0--safety-stabilization)):
stop the legacy `odooflux.py` from damaging customer modules, based on the audit
[ODOO_MODULE_UPGRADER_AUDIT.md](../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Analysis never changes my modules (Priority: P1)

A developer runs OdooFlux in analyze mode or with `--dry-run` on a module or an addons path and
gets a report. Nothing inside the scanned paths is created, modified, renamed, or deleted.

**Why this priority**: Today, analyze mode writes `__manifest__.py` (F-SAFE-1). Read-only
analysis is the minimum trust requirement.

**Independent Test**: Hash every file and the directory listing of the Appendix A fixture
before and after an analyze run and a `--dry-run --fix` run; they are identical.

**Acceptance Scenarios**:

1. **Given** a module with `__openerp__.py` and no `__manifest__.py`, **When** the user runs
   analysis without `--fix`, **Then** no `__manifest__.py` is created and the rename is reported as
   a planned action.
2. **Given** any fixture, **When** the user runs with `--fix --dry-run`, **Then** no file in the
   scanned paths changes and the report lists the edits that would have been applied.

---

### User Story 2 - Fix mode never writes a broken file (Priority: P1)

A developer runs `--fix`. Every file the tool writes is syntactically valid for its type. A
transformation that would produce invalid output is rejected, reported with the parser error,
and the original file is kept.

**Why this priority**: Today the fixer writes Python that does not compile and XML that is not
well-formed (F-PY-1, F-PY-2, F-XML-1, F-VAL-1).

**Independent Test**: Run `--fix` on the Appendix A fixture; every written `.py` compiles, every
written `.xml` parses, and every written manifest passes `ast.literal_eval`.

**Acceptance Scenarios**:

1. **Given** a fixer whose output fails to parse, **When** fix mode runs, **Then** no file of that
   module is written, a `REJECTED` edit record with the parser message is reported, the module's
   findings stay open, and other modules are still processed.
2. **Given** `fields.Char(size=64, string='X')`, **When** fix mode runs, **Then** the output is
   `fields.Char(string='X')` and it compiles.
3. **Given** `<button ... states="draft"/>`, **When** fix mode runs, **Then** no comment is placed
   inside the tag and the file is well-formed.

---

### User Story 3 - Backups are safe and writes are atomic (Priority: P1)

Every `--fix` run backs up each module before writing to it, unless the developer passes
`--no-backup`. The backup is created in a tool-owned state directory outside every scanned path and
verified before any write. If backup or verification fails, the module is
not touched. Interrupted writes never leave truncated files.

**Why this priority**: Backups inside the addons path become duplicate installable modules
(F-SAFE-2). A failed backup currently continues writing (F-SAFE-3). Writes are not atomic
(F-SAFE-4).

**Independent Test**: Run `--fix --backup --addons-path` on a temp addons tree; no new directory
appears in the addons path, the backup exists under the state directory with matching checksums,
and a re-scan finds only the original modules.

**Acceptance Scenarios**:

1. **Given** `--addons-path A --fix --backup`, **When** the run completes, **Then** the backup lies
   under `<state-dir>/runs/<run-id>/backup/` and not under `A`.
2. **Given** a backup that fails or fails verification, **When** fix mode runs, **Then** the module
   is reported `BLOCKED` and zero files are modified.
3. **Given** a crash injected between writing the temporary file and replacing the target,
   **When** the run is inspected, **Then** the target file is either the original or the complete new
   content.
4. **Given** a `--state-dir` inside a scanned path, **When** the tool starts, **Then** it refuses to
   run with a clear error.
5. **Given** `--fix` without `--backup`, **When** the run completes, **Then** a verified backup exists
   for every module that was written to.
6. **Given** `--fix --no-backup`, **When** the run completes, **Then** no backup is made and the report
   and run log mark the run as non-reversible.

---

### User Story 4 - Version-correct, honest fixes (Priority: P2)

The developer sees fixes only where they are correct for the requested source→target pair, and
a finding is reported as fixed only if a re-scan of the written content no longer produces it.

**Why this priority**: Wrong fixes (F-PY-3/4/5, F-XML-2) and inflated fix counts (F-REP-1) hide
real problems.

**Independent Test**: Run `--fix` on the fixture; the report's fixed count equals the number of
findings present before and absent after a re-scan; semantics-changing constructs are reported
for review, not rewritten.

**Acceptance Scenarios**:

1. **Given** `@api.returns(...)` and target 18, **When** fix mode runs, **Then** the decorator is kept
   and a review finding cites EV-102. **Given** target 19, **Then** the decorator line is removed with
   correct indentation, and a review finding remains about return-value semantics.
2. **Given** `@api.one`, **When** fix mode runs, **Then** it is not removed automatically; a review
   finding (EV-101) explains the required loop or `ensure_one()`.
3. **Given** `.sudo(False)` or `.sudo(True)`, **When** fix mode runs, **Then** it is unchanged.
   **Given** `.sudo(user)` with source 12, **Then** it becomes `.with_user(user).sudo()` (EV-103).
4. **Given** an `attrs=` attribute, **When** fix mode runs, **Then** it is left unchanged and reported
   as a manual or P4 item (detect-only until the converter exists).
5. **Given** manifest version `14.0.2.3.1` and target 19, **When** fix mode runs, **Then** it
   becomes `19.0.2.3.1`.

---

### User Story 5 - Run log and exit codes for automation (Priority: P3)

A CI pipeline gets a run log listing every written file (pre-hash, post-hash, edit IDs, backup
path), and an exit code chosen by `--fail-on`.

**Why this priority**: Recovery and CI depend on it. Full rollback arrives in P2.

**Independent Test**: After a fix run, the run log lists all and only the written files with
correct hashes; `--fail-on critical` exits 0 when only warnings remain.

**Acceptance Scenarios**:

1. **Given** a fix run that writes N files, **When** the run log is read, **Then** it has N entries
   with SHA-256 before/after matching the files on disk.
2. **Given** only INFO findings, **When** run with default `--fail-on`, **Then** exit code is 0.

### Edge Cases

- Module with both `__openerp__.py` and `__manifest__.py`: no copy; finding reports the duplicate (F-SAFE-5).
- Write fails part-way through a module (e.g., read-only file, disk full): files already written in
  that module are restored from its verified backup, the module is reported `BLOCKED`, and the exit
  code is 4. With `--no-backup` the restore is impossible; the report lists the written and unwritten
  files of that module.
- Non-UTF-8 file: not rewritten (decoding with `errors="replace"` would corrupt it); reported.
- State directory on a different filesystem from the module: atomic replace still happens in the
  target directory (temporary file created next to the target).
- `.sudo(flag=False)` keyword form: unchanged.
- Decorator followed by comment lines before `def`: removal keeps the comments and the `def` indentation.
- Two fixers touching the same file: validation runs on the combined result.
- `--backup` and `--no-backup` passed together: usage error (exit 2).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Analyze mode and `--dry-run` MUST NOT write, create, rename, copy, or delete any
  path inside scanned modules or addons paths, including the `__openerp__.py` copy.
  Traces: REQ-SAF-001, REQ-MAN-001
- **FR-002**: Before writing any file, the tool MUST validate the new content: Python by
  `ast.parse`, XML by a well-formedness parse, manifests by `ast.literal_eval`. On failure it MUST
  NOT write and MUST record a rejected-edit entry with the parser message.
  Traces: REQ-SAF-002, REQ-VAL-001
- **FR-003**: Backups MUST be created under `<state-dir>/runs/<run-id>/backup/<module>/`.
  `<state-dir>` defaults to `$XDG_CACHE_HOME/odooflux` or `~/.cache/odooflux` (ADR-013) and is
  refused if inside any scanned path. Backups MUST be verified by file count and SHA-256.
  Traces: REQ-SAF-003
- **FR-004**: Backup failure or verification mismatch MUST block all writes for that module.
  Traces: REQ-SAF-004
- **FR-014**: Fix mode MUST back up every module before its first write by default. `--no-backup`
  MUST be the only way to skip it; such a run MUST be marked non-reversible in the report and in
  every run log entry. `--backup` stays accepted as a no-op for compatibility.
  Traces: REQ-SAF-003, REQ-SAF-006
- **FR-015**: Writes MUST be all-or-nothing per module. The tool MUST compute and validate the new
  content of every changed file in a module before writing any of them. If any file is rejected, no
  file in that module is written and the module's edits are reported `REJECTED` (exit 3). Other
  modules continue.
  Traces: REQ-SAF-002, REQ-SAF-005
- **FR-005**: Every write MUST go to a temporary file in the target's directory, be flushed with
  `fsync`, and replace the target with `os.replace`.
  Traces: REQ-SAF-005
- **FR-006**: Every write MUST be appended to `<state-dir>/runs/<run-id>/log/run_log.jsonl` with
  path, pre-hash, post-hash, rule/edit identifiers, and backup location.
  Traces: REQ-SAF-006
- **FR-007**: The unsafe fixes MUST be corrected or disabled:
  - remove the in-tag comment from the `states=` fixer (F-XML-1), and skip it when `invisible=` exists (F-XML-4);
  - remove decorators as whole lines (F-PY-1);
  - make `size=` removal comma-aware (F-PY-2);
  - leave `.sudo(<bool>)` and `.sudo(flag=…)` unchanged (F-PY-5);
  - stop injecting JS comments into Python (F-PY-6);
  - stop the JS `@odoo-module` header injection (F-VER-6);
  - make the `attrs=` fixer detect-only (F-XML-2/3);
  - make `@api.one` detect-only with review (F-PY-4, EV-101);
  - remove `@api.returns` only when the target is ≥19.0 (EV-102), detect/review otherwise.

  Traces: REQ-SAF-010
- **FR-008**: A finding MUST be marked fixed only if it is absent from a re-scan of the validated
  content that was written. Each resolved finding is matched by rule category and nearest line
  after edits.
  Traces: REQ-TRF-005
- **FR-009**: Manifest version rewriting MUST keep the module's own suffix (`<src>.x.y.z` →
  `<target>.x.y.z`) and MUST accept single- and double-quoted strings.
  Traces: REQ-MAN-002
- **FR-010**: `--fail-on {critical,warning,info,none}` MUST control the exit code. The default is
  `critical`. Edits rejected in write mode MUST exit 3; tool errors and blocked modules MUST exit 4, so
  argparse's 2 is not reused for findings (final table: [REPORTING_AND_UX.md](../../docs/planning/REPORTING_AND_UX.md)).
  Traces: REQ-REP-005
- **FR-011**: The tool MUST NOT write logs, AI debug files, or caches inside customer modules;
  `ai_response_debug.txt` moves to `<state-dir>/runs/<run-id>/log/`.
  Traces: REQ-SEC-003
- **FR-012**: Each resolved audit finding MUST have a regression test that names the finding ID.
  Traces: REQ-TST-005, REQ-SAF-010
- **FR-013**: Rule messages that state wrong version facts MUST be corrected:
  - `@api.one`/`@api.multi` removed in 13.0 (EV-101);
  - `Warning` removed in 17.0 and deprecated 14.0–16.0 (EV-110);
  - `@api.returns` removed in 19.0 (EV-102).

  Traces: REQ-SAF-010

### Key Entities

- **Run**: one invocation; run ID, state directory, mode, modules, start/end, `reversible`
  (false only when `--no-backup` was used).
- **Run log entry**: one written file; path, pre/post SHA-256, rules applied, backup path, timestamp.
- **Rejected edit**: file, rule category, reason (validator name + message).
- **Backup manifest**: module, file list, checksums, verification result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the Appendix A fixture, 0 written Python files fail `py_compile` and 0 written XML
  files fail to parse (today: 1 and 1).
- **SC-002**: Analyze and dry-run produce 0 byte changes on all P0 fixtures (today: 1 file
  created).
- **SC-003**: 0 backup directories appear inside scanned paths after `--fix --backup` (today: 1
  per module).
- **SC-004**: The reported fixed count equals the re-scan difference on every P0 fixture
  (today: 22 reported against fewer actually fixed).
- **SC-005**: Each of F-SAFE-1/2/3/4/5, F-PY-1/2/4/5/6, F-XML-1/2/4, F-REP-1, F-MAN-1, F-AI-6
  (debug file location) has one passing regression test.
- **SC-006**: In fault-injection runs (rejected file, write failure mid-module), 0 modules are left
  with a mix of old and new files, and every `--fix` run without `--no-backup` has a verified backup
  for each module it wrote to.

## Assumptions

- P0 patches the legacy single file `odooflux.py` in place. No package restructuring happens
  until P2 (ADR-001).
- The full `attrs` → expression converter is delivered in P4 (REQ-XML-002). Until then, `attrs=`
  is detect-only.
- Full rollback and resume are P2 (REQ-SAF-008/009). P0 delivers the log they need.
- `--fail-on` default `critical` is a behaviour change from today (exit 1 on any finding). It is
  recorded in the change record. D-10 covers further CLI deprecations at cut-over.
- Atomic replace is guaranteed only on POSIX and Windows filesystems that support `os.replace`.

## Clarifications

### Session 2026-11-06

- Q: Should P0 keep any `attrs=` auto-fix? → A: No. Every current output is wrong for 17+
  (F-XML-2). Make it detect-only; P4 delivers the converter.
- Q: Where do backups go? → A: `<state-dir>/runs/<run-id>/backup/`, with the state dir from ADR-013
  and `--state-dir` to override; refuse a state dir inside scanned paths.
- Q: Is `@api.returns` removal ever correct? → A: Only for targets ≥19.0, where it no longer exists
  (EV-102). It is still a review finding because return-value conversion changes.
- Q: What does "fixed" mean in reports? → A: Absent from a re-scan of the written content (FR-008).
- Q: Default exit-code threshold? → A: `--fail-on critical`; exit 3 for rejected edits, exit 4 for tool errors and blocked
  modules.
- Q: Should `--fix` always back up, or only with `--backup`? → A: Always by default; `--no-backup`
  opts out and the run is flagged non-reversible (FR-014). `--backup` is kept as a no-op.
- Q: If one file's fix is rejected, are the module's other fixed files still written? → A: No.
  Writes are all-or-nothing per module; other modules continue (FR-015).
- Q: Does P0 remove `--api-key`? → A: No. Deprecation is decided at cut-over (D-10). P0 only moves
  the debug file out of modules.
