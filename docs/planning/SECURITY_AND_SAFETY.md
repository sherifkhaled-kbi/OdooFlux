# Security and Safety

Safety of customer source code (OBJ-008) and security of the tool's processing. Governing rules:
constitution Principles II, III, and VII;
[ADR-013](ARCHITECTURE_DECISIONS.md#adr-013--job-workspace-backups-and-state-directory) (workspace and state dir);
[ADR-011](ARCHITECTURE_DECISIONS.md#adr-011--runtime-validation-in-disposable-containers) (sandbox).
Current defects motivating this design: F-SAFE-1…5, F-VAL-1, F-AI-6 in
[../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../reviews/ODOO_MODULE_UPGRADER_AUDIT.md).

## 1. Safety model

### Immutable inputs and read-only analysis
- Analysis and `--dry-run` never create, modify, rename, or delete anything under scanned module
  or addons paths. This is enforced structurally: only the **promote** stage writes to inputs, and
  it is unreachable in those modes (REQ-SAF-001). Today `odooflux.py` violates this by copying
  `__openerp__.py` in analyze mode (F-SAFE-1, fixed in P0).
- A hash test (every file's SHA-256 and the directory listing before and after) runs on every
  golden fixture.

### Safe dry-run
Dry-run executes the full pipeline in the workspace, including validation, and produces the
report and an optional diff. It stops before promotion.

### Isolated working directories (ADR-013)
- State dir: `--state-dir`, default `$XDG_CACHE_HOME/odooflux` or `~/.cache/odooflux`. Refused if
  inside any scanned path.
- Per run: `runs/<run-id>/work/` (module copies), `backup/`, `log/` (run log, audit log),
  `runtime/`, `ai-cache/` (shared across runs).
- Transformations operate only on `work/` (REQ-SAF-007).

### Backup validation
- The backup is written under `runs/<run-id>/backup/<module>/` (never next to the module; F-SAFE-2).
- After copying, verify the file count and the SHA-256 of every file against the originals.
- On failure or mismatch, the module is `BLOCKED` and nothing is promoted (REQ-SAF-003/004;
  F-SAFE-3).

### Atomic writes
Write to a temporary file in the **same directory** as the target, then `fsync`, then
`os.replace`, then `fsync` the directory where supported. Permissions and the original encoding
and newline style are preserved (REQ-SAF-005; F-SAFE-4).

### Run log, rollback, checkpoints, resume
- The run log (JSON Lines) records, per promoted file: path, pre-hash, post-hash, edit IDs, and
  backup path (REQ-SAF-006).
- `odooflux rollback <run-id>` restores files whose current hash equals the logged post-hash. It
  reports, and does not overwrite, files changed after the run (REQ-SAF-008).
- A checkpoint is written after each module is promoted. `odooflux resume <run-id>` continues
  from the last checkpoint and produces the same final report as an uninterrupted run
  (REQ-SAF-009).

### Failure recovery
Every failure path ends in one of three states:
1. nothing promoted for the module;
2. the module fully promoted;
3. a partial promotion with the run log listing exactly what changed and the rollback command
   printed in the report's recovery section.

## 2. Untrusted source handling

Customer modules are **untrusted input**.

| Rule | Mechanism |
|---|---|
| Never import or execute customer code in the tool process | Parsing only (`ast`, expat, JS adapter). A static test bans `exec`, `eval`, and dynamic import of workspace paths (REQ-SEC-001; TST-008-013) |
| Manifest parsing | `ast.literal_eval` only, never `eval` (REQ-MAN-001) |
| Path safety | Resolve and reject symlinks escaping the module root. Reject absolute paths and `..` in manifest file lists. Workspace copies do not follow external symlinks. |
| Resource exhaustion | Per-file size cap and parse timeouts for pathological inputs. An oversized file is reported as a finding, not processed. |
| Decoding | Undecodable bytes are reported. Files are never re-encoded without an edit. |
| Output escaping | All excerpts escaped in terminal (control characters) and HTML (entities) (REQ-SEC-004) |

## 3. Sandbox isolation and resource limits (runtime layer)

Customer code executes **only** inside the runtime adapter's containers (P7):
- Read-only bind mount of the workspace copy and a per-run scratch volume. No other host paths.
- `--network none` by default. Optional allow-listed package index for `external_dependencies`.
- CPU, memory, pids, and wall-time limits, configurable, with defaults set from measured
  fixture baselines.
- Not privileged. No added capabilities. A non-root user where the image allows.
- Images allow-listed and digest-pinned. Provenance research: G-R-13, G-R-21.
- Labels `odooflux.run=<run-id>`. Teardown on every exit path. Leftovers reported with a cleanup
  command.

## 4. Secrets

| Topic | Rule |
|---|---|
| API keys | From environment variables or a secrets file outside scanned paths. `--api-key` is deprecated (D-10) and removed in P9 (REQ-AI-008) |
| Redaction | Configured secret names and credential-shaped patterns are replaced by `***` in logs, reports, audit log, AI cache, and debug files |
| Transmission | Credentials are sent only to the configured provider endpoint for that provider |
| Verification | Canary-secret scan over all artefacts (TST-007-014, TST-010-008) |

## 5. AI-specific defences

- **Consent and minimisation.** AI is off by default and requires explicit consent to send code
  (D-08). Only regions are sent, never whole files. Prompts are redacted.
- **Prompt injection.** Customer content sits in delimited data blocks. AI output cannot alter
  plan, rules, validators, or edit scope, and is validated like any edit (REQ-SEC-004).
- **Output validation.** Protected identifiers, L1/L2, and re-scan.
- Details: [AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md § 6](AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md#6-security).

## 6. Audit logging

Hash-chained, append-only `audit.jsonl` per run (REQ-SEC-005). Actions and fields are defined in
[specs/010-hardening-release/contracts/audit-log.md](../../specs/010-hardening-release/contracts/audit-log.md).
The log never contains file contents, prompts, or secrets.

## 7. Threat model

| # | Asset | Threat | Likelihood | Impact | Control | Verified by |
|---|---|---|---|---|---|---|
| T1 | Customer source | Corrupted by an invalid fix | High today (F-PY-1, F-XML-1) | High | L1 gate, workspace, atomic promote | TST P0 regression, failure injection |
| T2 | Customer source | Modified in analyze/dry-run | High today (F-SAFE-1) | Medium | Promote stage unreachable; hash test | REQ-SAF-001 tests |
| T3 | Addons path | Backup registered as a duplicate addon | High today (F-SAFE-2) | High | Backups in state dir | REQ-SAF-003 tests |
| T4 | Host | Customer code executed on host | Low | Critical | No exec in core; containers only | TST-008-013, TST-008-004 |
| T5 | Host | Resource exhaustion by a module | Medium | Medium | Container limits, parse caps | TST-008-007 |
| T6 | Credentials | Leakage via CLI history, logs, or reports | Medium today (F-AI-6) | High | Env/secrets file; redaction; scan | TST-007-014, TST-010-008 |
| T7 | Customer source | Exfiltration to an AI provider without consent | Low | High | Off by default; consent flag; minimisation | TST-007-003/004 |
| T8 | Tool behaviour | Prompt injection in code | Medium | Medium | Data blocks; validation; fixed plan | TST-007-009 |
| T9 | Reports | XSS or terminal escape injection via excerpts | Medium | Medium | Escaping in renderers | TST-009-005, TST-009-011 |
| T10 | Supply chain | Untrusted container image | Medium | High | Allow-list and digest pinning; provenance research | G-R-13 closure (P7 T001) |
| T11 | Integrity | Undetected tampering with the run/audit log | Low | Medium | Hash chain | TST-010-007 |
| T12 | Path traversal | Manifest or symlink pointing outside the module | Low | High | Path normalisation and rejection | P2 discovery tests |

## 8. Failure-injection test plan

See the injection table in
[VALIDATION_AND_TEST_STRATEGY.md § Failure-injection plan](VALIDATION_AND_TEST_STRATEGY.md#failure-injection-plan).
Ownership:
- P0: write path and backup;
- P2: promotion, checkpoint, and rollback;
- P6: AI responses;
- P7: runtime;
- P9: the full consolidated suite (TST-010-010), as a release gate.
