# Regression index (P0-resolved audit findings)

Each row names a finding from `docs/reviews/ODOO_MODULE_UPGRADER_AUDIT.md`, the `TST-001-*` IDs from
`specs/001-safety-stabilization/tasks.md`, and at least one test whose docstring (or class docstring) contains the
finding ID. `tests/regression/test_regression_index.py` validates this table (TST-002-009).

Test reference format: `path::Class::method`, relative to the repository root.

| Finding ID | Test IDs | Test |
|---|---|---|
| F-SAFE-1 | TST-001-004 | tests/regression/test_p0_safety_readonly.py::AnalysisIsReadOnlyTests::test_analyze_is_read_only |
| F-SAFE-2 | TST-001-017 | tests/regression/test_p0_backup_atomic.py::BackupTests::test_backup_outside_addons_path |
| F-SAFE-3 | TST-001-018 | tests/regression/test_p0_backup_atomic.py::BackupTests::test_backup_verified |
| F-SAFE-4 | TST-001-002 | tests/regression/test_p0_backup_atomic.py::AtomicWriteTests::test_atomic_write_interrupted |
| F-SAFE-5 | TST-001-006 | tests/regression/test_p0_safety_readonly.py::BothManifestsTests::test_both_manifests_reported_not_copied |
| F-PY-1 | TST-001-012 | tests/regression/test_p0_python_fixers.py::DecoratorRemovalTests::test_decorator_removal_keeps_indentation |
| F-PY-2 | TST-001-011 | tests/regression/test_p0_python_fixers.py::SizeArgumentTests::test_size_first_arg |
| F-PY-4 | TST-001-022 | tests/regression/test_p0_python_fixers.py::ApiDecoratorVersionTests::test_api_one_detect_only |
| F-PY-5 | TST-001-023 | tests/regression/test_p0_python_fixers.py::SudoTests::test_sudo_bool_unchanged |
| F-PY-6 | TST-001-015 | tests/regression/test_p0_python_fixers.py::NoJsInPythonTests::test_no_js_comment_in_python |
| F-XML-1 | TST-001-013 | tests/regression/test_p0_xml_fixers.py::StatesFixTests::test_states_fix_well_formed |
| F-XML-2 | TST-001-024 | tests/regression/test_p0_xml_fixers.py::AttrsDetectOnlyTests::test_attrs_detect_only |
| F-XML-4 | TST-001-014 | tests/regression/test_p0_xml_fixers.py::StatesFixTests::test_states_fix_skipped_when_invisible_present |
| F-REP-1 | TST-001-025 | tests/regression/test_p0_reporting.py::FixedCountTests::test_fixed_count_equals_rescan_delta |
| F-MAN-1 | TST-001-026 | tests/regression/test_p0_reporting.py::ManifestVersionTests::test_manifest_version_suffix_preserved |
| F-AI-6 | TST-001-030 | tests/regression/test_p0_reporting.py::ArtifactPlacementTests::test_no_tool_artifacts_in_module |
| F-VAL-1 | TST-001-007, TST-001-008, TST-001-009 | tests/regression/test_p0_validation_gate.py::ValidationGateTests::test_invalid_python_not_written |
| F-REP-3 | TST-001-028 | tests/regression/test_p0_reporting.py::ExitCodeTests::test_fail_on_thresholds |
