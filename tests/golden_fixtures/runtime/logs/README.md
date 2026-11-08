# Runtime log samples

Used by `tests/unit/validation/test_log_classifier.py` (TST-008-005). One file per FR-006 class.

| File | Origin | Notes |
|---|---|---|
| `view_validation.log` | **Recorded** from the opt-in run of `broken_view` on odoo:19.0 (2026-11-07, image digest `odoo@sha256:5db447…af7b0`) | Lines from the `loading broken_view/views/fixture_views.xml` announcement to the end of the log. |
| `access_rights.log` | **Recorded** from the opt-in run of `acl_missing_model` on odoo:19.0 (same image) | On 19.0 the unresolvable xml id in `model_id:id` produced an SQL `null value in column "model_id"` error, not the EV-365 `External ID not found` message. Pattern `access_rights.null-model-id` covers this, with `version_range` 19.0 only. |
| `registry.log` | Synthesised from the EV-360 source string (`Some modules are not loaded`) | Not reproduced by a real run. |
| `import_error.log` | Synthesised from the EV-361 source string (`Couldn't load module`) | Not reproduced by a real run. |
| `data_load.log` | Synthesised from the EV-363 and EV-365 source strings | Not reproduced by a real run. |
| `asset_compile.log` | Synthesised from the EV-366 source string (`Could not parse file`) | Not reproduced by a real run. |
| `missing_python_dependency.log` | Synthesised from the EV-367 source strings (`External dependency ... not installed`, `Python library not installed`) | Not reproduced by a real run. |
| `unknown.log` | Synthesised | One ERROR record no pattern claims, and one INFO record that must not be reported. |

`timeout` and `oom` have no log file: they come from `killed_reason` (the `install_loop` fixture was killed at
60 s on 19.0 and produced exit code 137 with no classifiable record, which is what the adapter expects).

Odoo 19 real-run details that the samples depend on:
- Records start with `YYYY-MM-DD HH:MM:SS,mmm <pid> <LEVEL> <dbname> <logger>: `. The dbname is `?` before the
  database is attached.
- A view error appears in the traceback of the `Failed to initialize database` CRITICAL record. The traceback
  belongs to its record, so the record is classified from the traceback text.
- `Failed to load registry` (ERROR, unknown) always precedes the CRITICAL record. The adapter reports the first
  classified (non-unknown) error as the primary error.
