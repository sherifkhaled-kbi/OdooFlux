# Reference machine (feature 010, REQ-PRF-001)

Budgets in `budgets.json` and the stored `baseline.json` hold for this machine profile. On another machine the numbers are
not comparable: run `run_benchmarks.py --no-enforce` there and treat the output as information. The P2 baseline machine
in [BASELINE.md](BASELINE.md) is the same machine.

| | |
|---|---|
| CPU | 13th Gen Intel Core i5-13420H (12 logical cores) |
| Memory | 15.2 GiB |
| OS | Linux 7.0.0-42-generic |
| Python | 3.12.3 (system interpreter) |
| Storage | local SSD |

CI must use the same runner class before it enforces these budgets. That choice is an owner decision (see the review register).
