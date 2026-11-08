# behavior_compare

Three tests in `tests/test_behavior.py`, all tagged `odooflux_fixture`.

| Test | Source 18.0 | Target 19.0 | Classification |
|---|---|---|---|
| `test_pass_both` | pass | pass | `pass_both` |
| `test_regression` | pass | fail | `regression` |
| `test_fail_both` | fail | fail | `fail_both` |

- Expected L5 result with a source baseline: `FAIL` listing exactly the regression (SC-004).
- Without a source baseline: target tests run, L5 is `PASS` with `coverage = partial`, status at most `INSTALL_VERIFIED`.
- Expected error class: `test_failure` (not a classified install error).
