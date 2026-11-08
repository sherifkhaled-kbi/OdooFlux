# P0 change record: Safety Stabilization

Spec: [specs/001-safety-stabilization](../../specs/001-safety-stabilization/spec.md).
Audit findings: [ODOO_MODULE_UPGRADER_AUDIT.md](../reviews/ODOO_MODULE_UPGRADER_AUDIT.md).
Every behaviour change below is user-visible. Read it before running `odooflux.py --fix` in CI.

## Exit codes (FR-010, R-07)

| Code | Before | After |
|---|---|---|
| 0 | no findings | no findings at or above `--fail-on` |
| 1 | any finding | open findings at or above `--fail-on` (warnings-only exits 0 with the default) |
| 2 | critical findings | argparse usage errors only |
| 3 | n/a | an edit was rejected by the validation gate (write mode) |
| 4 | tool errors exited 1 | tool errors, invalid addons path, blocked module (backup or write failure), state dir inside a scanned path |

New option `--fail-on {critical,warning,info,none}`, default `critical`.

## Behaviour changes

| Area | Before | After | Trace |
|---|---|---|---|
| Analysis and `--dry-run` | Analyze mode created `__manifest__.py` | Never writes. The `__openerp__.py` rename is listed as `[planned]`; `--dry-run` lists the files it would change | FR-001, F-SAFE-1 |
| Validation gate | Invalid Python or XML could be written | Each file is parsed before writing (Python `ast.parse`, XML well-formedness, manifest `ast.literal_eval`). A failure rejects the module: no file in it is written, the findings stay open, the report shows `Fix Rejected`, exit 3 | FR-002, FR-015, F-VAL-1 |
| Module write unit | Files written one at a time | All-or-nothing per module. A write error part-way restores the files from the verified backup and blocks the module (exit 4). With `--no-backup` the report lists written and unwritten files | FR-015, SC-006 |
| Backups | Only with `--backup`; a sibling `<module>_backup_<ts>` inside the addons path; failure ignored | On by default with `--fix`. Stored in `<state-dir>/runs/<run-id>/backup/`; verified by file list and SHA-256; a failed backup blocks the module | FR-003, FR-004, FR-014, F-SAFE-2, F-SAFE-3 |
| `--no-backup` | n/a | Skips the backup. The run is marked `reversible: false` in the report and in every run log entry | FR-014 |
| `--backup` | Enabled backups | Accepted, no-op. Combined with `--no-backup`: usage error (exit 2) | FR-014 |
| State directory | n/a | `--state-dir`, default `$XDG_CACHE_HOME/odooflux` or `~/.cache/odooflux`. Refused (exit 4) when inside any scanned module or addons path | FR-003, ADR-013 |
| Run log | n/a | `<state-dir>/runs/<run-id>/log/run_log.jsonl`: one `file_written` entry per changed file with SHA-256 before and after, rules, and backup path | FR-006 |
| Writes | `write_text` in place | Temporary file in the target directory, `fsync`, `os.replace`; temporary file removed on error; file mode kept | FR-005, F-SAFE-4 |
| Duplicate manifests | `__openerp__.py` was copied only when `__manifest__.py` was absent; a duplicate was not reported | Reported as `Duplicate Manifest`; no copy, no rename, no edit to `__openerp__.py` | FR-001, F-SAFE-5 |
| AI debug output and drafts | `ai_response_debug.txt` and `*.ai_draft` written into the module | Written to the run's `log/` directory in the state dir. Invalid AI output is rejected by the same gate as regex fixes | FR-011, F-AI-6 |
| Fixed count | Every auto-fixable finding counted as fixed | A finding counts as fixed only when a re-scan of the written content no longer reports it. On the Appendix A fixture: 19 reported unpatched, 12 patched (the rest are now detect-only or still present) | FR-008, F-REP-1 |
| `states=` (XML) | Comment injected inside the tag; converted even when `invisible=` existed | No comment. Tags that already have `invisible=` are left alone and their finding stays open | FR-007, F-XML-1, F-XML-4 |
| `attrs=` (XML) | Rewritten to inline domain attributes (wrong for 17+) | Detect-only. Finding is `NEEDS_REVIEW` with a Python-expression hint. Converter deferred to P4 | FR-007, F-XML-2, F-XML-3 |
| `@api.multi` | Removed as a whole line | Same result, now through the shared tokenize-based helper that also handles `@api.returns` (F-PY-1) | FR-007, F-PY-1 |
| `@api.returns` | Removed for every target | Removed only for `--to-version 19`. A `Returns Semantics (review)` finding stays open for both targets | FR-007, FR-013, EV-102, F-PY-3 |
| `@api.one` | Removed | Never removed. `NEEDS_REVIEW` finding citing EV-101 | FR-007, FR-013, F-PY-4 |
| `size=` on `fields.Char` | Regex removal; left broken syntax (first argument, continuation lines) | Token-based, comma-aware removal of one keyword and one comma | FR-007, F-PY-2, R-06 |
| `.sudo(...)` | `.sudo(x)` rewritten for every source; `.sudo(False)` rewritten too | Rewritten only for source 12 and older, and never for `True`/`False`/`flag=`. Other uses are `NEEDS_REVIEW` | FR-007, EV-103, F-PY-5 |
| JS files | `@odoo-module` header and `/* TODO */` comments injected; `ajax.jsonRpc` annotated | Detect-only. JS files are never written | FR-007, F-VER-6 |
| Python comments | `/* TODO */` JavaScript injected into `.py` files | Removed | FR-007, F-PY-6 |
| Manifest version | `version` replaced with `<target>.0.1.0.0` | Only the major prefix is replaced: `14.0.2.3.1` becomes `19.0.2.3.1`. Single and double quotes both work | FR-009, F-MAN-1 |
| Rule messages | `@api.*` "removed in v14+"; Warning "removed in v14" | `@api.one`/`@api.multi` removed in 13.0; `Warning` deprecated in 14.0–16.0, removed in 17.0; `@api.returns` removed in 19.0 | FR-013, EV-101/102/110 |
| Undecodable files | Read with replacement characters and rewritten | Reported as `Encoding` and never rewritten | Spec edge case |
| Tool errors | Exit 1 | Exit 4 | FR-010 |
| `--from-version >= --to-version` | Exit 1 | Usage error, exit 2 | FR-010 |

## Unchanged on purpose

- `--api-key` stays. Deprecation is decided at cut-over (D-10).
- The `attrs=` converter is not reintroduced; it arrives in P4 (REQ-XML-002).
- Rollback and resume are P2 (REQ-SAF-007/008/009).
- Validation is syntax only (layer L1). Higher layers come in later phases.

## Known gaps left in P0

- `_check_manifest_version` uses a pattern with doubled backslashes (`\\s`), so the first pattern never matches. The fallback patterns cover the common cases. Not fixed here: it is not in the P0 finding list.
- The `Manifest Version` base rule matches any version prefix, so it stays open after a successful fix and is shown with `[AUTO-FIX]`. Its noise is a P1 item (F-VER-4).
