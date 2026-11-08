# Data Model: Test Foundation (P1)

## Fixture layout

```text
tests/golden_fixtures/
├── .gitattributes                       # * -text
├── INDEX.json                           # list of fixtures (see below)
└── v<NN>_<name>/
    ├── README.md                        # purpose, constructs, EV IDs, findings triggered
    ├── input/<module_name>/...          # module source (never modified by tests)
    ├── expected/18/<module_name>/...    # legacy --fix output for target 18 (if NN < 18)
    ├── expected/19/<module_name>/...    # legacy --fix output for target 19
    ├── expected_report.18.json          # normalised analyze report
    ├── expected_report.19.json
    └── expected_exit.json               # {"analyze": {"18": n, "19": n}, "fix": {...}}
```

## INDEX.json entry

| Field | Type | Rule |
|---|---|---|
| `id` | string | `v14_kbi_demo` |
| `source_version` | string | `"14.0"` |
| `module` | string | Module directory name under `input/` |
| `targets` | list[int] | Subset of `[18, 19]`, each greater than the source major |
| `evidence` | list[string] | `EV-…` IDs whose constructs the fixture uses |
| `findings` | list[string] | Audit finding IDs this fixture reproduces, if any |

## Normalised report

The legacy JSON report with:
- `module_path` → `"<MODULE>"`;
- `issues[].file` relative to the module;
- `timestamp` → `"<TS>"`;
- `summary.elapsed_seconds` → `0`;
- issues sorted by (file, line, category, message).

## Regression index (`tests/regression/INDEX.md`)

Table: `Finding ID | Test IDs (TST-…) | Test path::name`. It is validated by a test that greps
docstrings.
