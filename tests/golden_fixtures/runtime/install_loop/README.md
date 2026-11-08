# install_loop

A `post_init_hook` that never returns. Used to test the time limit and teardown.

- Expected L4 result: `FAIL`, status `FAILED`.
- Expected error class: `timeout` (set by the runtime adapter from the wall-time limit, not from a log line).
- After the run, no container, network or volume labelled with the run id may remain (SC-003).
