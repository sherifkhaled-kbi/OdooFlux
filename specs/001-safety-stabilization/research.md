# Research: Safety Stabilization (P0)

All Odoo-specific facts cite [OFFICIAL_EVIDENCE_REGISTER.md](../../docs/planning/research/OFFICIAL_EVIDENCE_REGISTER.md).
Defects cite [ODOO_MODULE_UPGRADER_AUDIT.md](../../docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md).

## R-01 Validation gate placement

- **Decision**: Validate in `analyze_and_fix_file` (`odooflux.py:915`) after the fixer chain and
  before `write_text` (`:946`). Validators: `ast.parse` (`.py`), `xml.etree.ElementTree.fromstring`
  on bytes (`.xml`), `ast.literal_eval` (manifests). The AI path (`:1495`) already validates Python
  and is extended with the same gate for every file type.
- **Rationale**: This is the single choke point for regex fixes (F-VAL-1).
- **Alternatives**: Validating per fixer was rejected because combined fixes can break files that
  individual fixes do not.

## R-02 Atomic write

- **Decision**: `tempfile.NamedTemporaryFile(dir=target.parent, delete=False)` → write → `flush` +
  `os.fsync` → `os.replace(tmp, target)`. Preserve file mode with `shutil.copymode`. On exception,
  unlink the temporary file.
- **Rationale**: `os.replace` is atomic within one filesystem (F-SAFE-4).
- **Alternatives**: Writing in place plus a backup gives no atomicity.

## R-03 State directory and backups

- **Decision**: ADR-013. Add `--state-dir`, defaulting to `$XDG_CACHE_HOME/odooflux` or
  `~/.cache/odooflux`. The run ID is a UTC timestamp plus 6 random hex characters. Backups go to
  `runs/<run-id>/backup/<module-name>/` via `shutil.copytree`. Verification compares file lists and
  SHA-256. The tool refuses a state dir that resolves inside any scanned path.
- **Rationale**: Fixes F-SAFE-2 (sibling backup becomes an addon) and F-SAFE-3.
- **Alternatives**: A zip archive was rejected for P0 (slower restore, same location problem); a
  sibling directory is the defect itself.

## R-04 Fix attribution by re-scan

- **Decision**: After the validated write, re-run `check_content` on the new content. A pre-fix
  finding counts as fixed when no post-fix finding has the same category within the line window
  shifted by the edit's line delta. If uncertain, it stays `OPEN`.
  `_mark_auto_fixes_applied` (`:901`) is replaced.
- **Rationale**: F-REP-1. Under-reporting is safe; over-reporting is not (Principle IV).

## R-05 Version-correct handling of legacy rules

| Construct | Evidence | P0 behaviour |
|---|---|---|
| `@api.multi` | EV-101 (removed 13.0) | Keep whole-line removal (safe: it was a no-op default); fix indentation handling |
| `@api.one` | EV-101 | Detect-only, review finding (semantics change, F-PY-4) |
| `@api.returns` | EV-102 (exists ≤18.0, removed 19.0) | Target ≥19: remove whole line plus review finding; target 18: detect/review only (F-PY-3) |
| `.sudo(user)` | EV-103 (12.0 `sudo(user)`, 13.0+ `sudo(flag)` + `with_user`) | Rewrite only when source ≤12 and the argument is not `True`/`False`/`flag=`; otherwise unchanged (F-PY-5) |
| `odoo.exceptions.Warning` | EV-110 (alias 12–13, subclass 14–16, removed 17) | Keep the existing fix (correct for 17+ targets); correct the message to "removed in 17.0" |
| `attrs=`/`states=` | EV-109 (rejected from 17.0) | `attrs` detect-only; the `states=` fix drops the in-tag comment and is skipped if `invisible=` exists |
| `<tree>` | EV-112 (`list` from 18.0) | Unchanged in P0; correct detection gating (F-VER-1) |

## R-06 `size=` removal

- **Decision**: Use a tokenize-based removal of the `size=<int>` keyword argument plus exactly one
  adjacent comma (the preceding one, or the following one if it is first). Validate the result with
  `ast`.
- **Alternatives**: Regex only — this is the current defect (F-PY-2).

## R-07 Exit codes

- **Decision**: 0 is success; 1 means findings at or above `--fail-on` remain; 3 means an edit was
  rejected in write mode; 4 means a tool error or a blocked module (FR-010, precedence 4 > 3 > 1 > 0).
  Code 2 is left to argparse (F-REP-3). This supersedes an earlier draft that used 3 for tool errors.
