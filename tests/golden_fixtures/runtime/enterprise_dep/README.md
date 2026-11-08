# enterprise_dep

Depends on `sale_subscription`, an Enterprise module. Enterprise source is not accessible (D-05).

- Expected L4 result: `SKIPPED` with reason `enterprise_dependency` (no install attempted).
- Status: at most `STATIC_VALIDATED`.
- L3 reports the dependency as `missing_module` (WARNING) with a note that it may be an Enterprise module.
