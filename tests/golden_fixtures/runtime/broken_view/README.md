# broken_view

Same as `install_ok`, but the form view references `no_such_field`, which the model does not define.

- Expected L4 result: `FAIL`, status `FAILED`.
- Expected error class: `view_validation` (`Error while validating view`, EV-362), attributed to
  `views/fixture_views.xml`.
