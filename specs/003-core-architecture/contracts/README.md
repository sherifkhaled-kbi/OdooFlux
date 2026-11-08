# Contracts for Feature 003 (Core Architecture)

The base contracts (data shapes and behaviour) are defined once in
[docs/planning/architecture/CONTRACTS.md](../../../docs/planning/architecture/CONTRACTS.md). The
files here refine them for P2 and do not contradict them.

| File | Refines |
|---|---|
| [cli.md](cli.md) | Entry point, subcommands, options, exit codes |
| [registries-and-plugins.md](registries-and-plugins.md) | Plugin registration |
| [recovery.md](recovery.md) | Workspace, run log, rollback, resume (ADR-013) |
| [result-model-v1.md](result-model-v1.md) | ReportModel v1 and its JSON schema |
