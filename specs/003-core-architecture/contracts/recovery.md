# Contract: Workspace, Run Log, Rollback, Resume (P2)

State directory layout (ADR-013):

```text
<state-dir>/runs/<run-id>/
├── state.json          RunState (atomic rewrite after each module)
├── work/<module>/      workspace copy (deleted after successful promotion unless --keep-work)
├── backup/<module>/    verified backup + <module>.manifest.json
└── log/run_log.jsonl   RunLogEntry v1 (append-only, fsync per entry)
```

## Guarantees

| Operation | Guarantee | Test |
|---|---|---|
| analyze / dry-run | Creates only `runs/<run-id>/{state.json,log}`; never touches sources | TST-003-030 |
| promote(module) | Either all changed files are promoted, or the module is restored from backup and marked `FAILED` | TST-003-031 |
| rollback(run) | Every `file_written`/`file_created` entry is reverted to `sha256_before` (or deleted). A file whose current hash ≠ `sha256_after` is skipped with `rollback_conflict` | TST-003-032, TST-003-033 |
| resume(run) | Final report equals an uninterrupted run (normalised); refused when `source_digest` changed | TST-003-034, TST-003-035 |

The state dir must not resolve inside any scanned path (exit 4), as in P0.
