# Behaviour test outputs

Recorded from the opt-in runs of the `behavior_compare` fixture (odoo:19.0 and odoo:18.0, see
`tests/golden_fixtures/runtime/behavior_compare/README.md`). The runs used `run_tests` with tags `/behavior_compare`.

| File | Origin |
|---|---|
| `target_19.tests.log` | **Recorded**, 19.0 (digest `odoo@sha256:5db447…af7b0`) |
| `source_18.tests.log` | **Recorded**, 18.0 (digest `odoo@sha256:9668ab…40432`) |
| `source_18_without_pass_both.tests.log` | **Synthesised**: the recorded 18.0 log with the `Starting TestBehavior.test_pass_both` record deleted, so the test is not run on the source. Used for `target_only`. |
| `target_19_without_pass_both.tests.log` | **Synthesised**: the recorded 19.0 log with the same record deleted. Used for `source_only`. |

Format notes from the recorded logs (EV-368 applies; these details come from the runs):
- Each executed test logs `Starting <Class>.<method> ...` on the module's test logger. Passing tests log nothing else.
- Failures log `ERROR ... FAIL: <Class>.<method>` (or `ERROR:` for exceptions). Tests run once at install and again
  in post-install, so a failure can appear twice.
- `odoo.tests.stats` reports a count that does not equal the number of tests in the module (5 for 3 tests), so the
  count is not used to decide completeness.
