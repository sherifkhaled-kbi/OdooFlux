# Verification evidence: Safety Stabilization (P0)

Commands run from the repository root on Linux with Python 3.12. The unpatched script is the
pre-change `odooflux.py` (commit `c9914e6`). Fixture: `tests/golden_fixtures/p0_kbi_demo_v14`.

## Regression suite (SC-005, SC-006)

```
$ python -m unittest discover -s tests -p "test_p0_*.py" -v
Ran 37 tests in 1.719s
OK
```

Before the change, the suite (35 tests at that point) failed: 19 failures, 16 errors. Each test
names the finding or requirement it covers in its docstring.

| Finding / requirement | Test |
|---|---|
| F-SAFE-1 | `test_analyze_is_read_only`, `test_dry_run_is_read_only` |
| F-SAFE-2 | `test_backup_outside_addons_path` |
| F-SAFE-3 | `test_backup_failure_blocks_module` |
| F-SAFE-4 | `test_atomic_write_interrupted` |
| F-SAFE-5 | `test_both_manifests_reported_not_copied` |
| F-VAL-1 | `test_invalid_python_not_written`, `test_invalid_xml_not_written`, `test_invalid_manifest_not_written` |
| F-PY-1 | `test_decorator_removal_keeps_indentation` |
| F-PY-2 | `test_size_first_arg`, `test_size_continuation_line`, `test_size_last_arg` |
| F-PY-4 (EV-101) | `test_api_one_detect_only` |
| F-PY-3 (EV-102) | `test_api_returns_target18_kept_review`, `test_api_returns_target19_removed_review` |
| F-PY-5 (EV-103) | `test_sudo_bool_unchanged`, `test_sudo_user_rewritten_only_from_12` |
| F-PY-6 | `test_no_js_comment_in_python` |
| F-XML-1, F-XML-4 | `test_states_fix_well_formed`, `test_states_fix_skipped_when_invisible_present` |
| F-XML-2 | `test_attrs_detect_only` |
| F-REP-1 | `test_fixed_count_equals_rescan_delta` |
| F-MAN-1 | `test_manifest_version_suffix_preserved` |
| F-AI-6 | `test_no_tool_artifacts_in_module` |
| FR-013 (EV-110) | `test_warning_message_versions` |
| FR-010 | `test_fail_on_thresholds`, `test_exit_codes_rejected_3_blocked_4` |
| FR-002 (AI path) | `test_ai_invalid_output_not_written` |
| SC-001 | `test_fixture_fix_outputs_valid` |
| SC-006 | `test_write_failure_restores_module_from_backup`, `test_write_failure_without_backup_reports_partial_state` |

## SC-001: written files are valid

Fix mode on a copy of the fixture, then `py_compile` on `models/demo.py` and an XML parse of
`views/demo_views.xml`.

```
UNPATCHED:  SyntaxError: invalid syntax            (demo.py)
            ParseError: not well-formed ... line 10 (demo_views.xml)
PATCHED:    PY-OK
            XML-OK
```

## SC-002: analysis and dry-run change no bytes

```
$ find $W/ro -type f -exec sha256sum {} + | sort | diff $W/before -
READ-ONLY-OK          (after analyze, and after --fix --dry-run)
```

Unpatched analyze mode created `__manifest__.py` in the module (1 file created).

## SC-003: no backup inside the addons path

```
PATCHED:    addons dir after: kbi_demo
            backup in state dir: kbi_demo, kbi_demo.manifest.json
UNPATCHED:  addons dir after: kbi_demo kbi_demo_backup_<ts>
```

## SC-004: fixed count equals the re-scan difference

```
PATCHED:    Fixed : 12   (re-scan difference, checked by test_fixed_count_equals_rescan_delta)
UNPATCHED:  Fixed : 19
```

The unpatched count marked every auto-fixable finding in a changed file as fixed. The patched
count only counts findings that a re-scan of the written content no longer reports (FR-008).

## Exit codes and edge cases (manual checks)

```
--backup --no-backup            exit 2  (usage error)
--ai-fix without a key          exit 2  (usage error)
non-UTF-8 file                  reported as "Encoding", bytes unchanged
state dir inside addons root    exit 4
rename dry-run                  "[planned] rename __openerp__.py -> __manifest__.py"
```

## Not measured

The plan's performance goal (no more than a 10 % slowdown) was not measured. The fixture is too
small to measure meaningfully. Validation and re-scan add one parse per changed file.
