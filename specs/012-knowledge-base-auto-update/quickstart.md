# Quickstart: Knowledge Base Auto-Update

Command flow for feature 012. Every command below exists in `cli/kap_update.py` and `cli/kap_release.py`. The sample outputs in this file were captured from offline runs in a temporary kb-home under `/tmp` on the development tree. Sections marked **not executed here** describe online behaviour from the code only: no online command was run while writing this file, and nothing in this file is verified against live upstream, a real Enterprise repository or a production source.

Commands are run from a scratch directory with the source tree on `PYTHONPATH`, as the documentation runs did:

```bash
cd /tmp && PYTHONPATH='/home/sherif-khaled/Desktop/KBI Projects/OdooFlux/src' python3 -m odooflux knowledge <verb> ...
```

Once installed, drop the `PYTHONPATH` prefix and use `odooflux knowledge <verb> ...`.

## 0. Choose a kb-home

The kb-home is the directory that holds releases, the active pointer, the audit log, the update history and the managed cache. It is resolved in this order: `--kb-home PATH`, then `ODOOFLUX_KB_HOME`, then the XDG data directory.

```bash
export ODOOFLUX_KB_HOME=/tmp/kb012          # optional; --kb-home overrides it
```

A kb-home that does not exist yet is fine for `check --offline`, `update --offline --dry-run` and `status`. `status` and `history` never create directories. `check` writes nothing.

## 1. Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `ODOOFLUX_KB_HOME` | every `knowledge` verb with `--kb-home` | Default kb-home. |
| `ODOOFLUX_OFFLINE=1` | `check`, `update` | Forces zero network calls (same as `--offline`). |
| `ODOOFLUX_ENTERPRISE_TOKEN` | `check`, `update` (online) | Enterprise token. Takes precedence over the file below. Never printed. |
| `ODOOFLUX_ENTERPRISE_TOKEN_FILE` | `check`, `update` (online) | Path to a regular file holding the token. It must not be a symbolic link, must have no group or other permission bits, must be owned by you, must be at most 4096 bytes, and its stripped content must be non-empty with no whitespace or control characters. |
| `ODOOFLUX_CA_BUNDLE` | `check`, `update` (online) | Absolute path to an existing regular file, passed to git as `GIT_SSL_CAINFO` for each call. TLS verification is never disabled. |

A bad token configuration prints one stderr warning with a closed code only (for example `TOKEN_FILE_PERMISSIONS`) and the run continues without a token. The token value never appears in stdout, stderr, the history or a report.

Without any Enterprise variable, Enterprise sources are reported as `SKIPPED_NO_CREDENTIALS` and Community knowledge still updates.

## 2. Check for upstream changes

### 2.1 Offline check (verified output)

With no installed release and no network:

```bash
python3 -m odooflux knowledge check --offline --kb-home /tmp/kb012
```

Captured output (exit 4):

```text
installed release: none (built-in knowledge only)
mode: offline, no remote contacted
status: CHECK_UNAVAILABLE
community: SKIPPED_OFFLINE=8; not compared
  SKIPPED_OFFLINE: 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0 (network access is disabled)
enterprise: SKIPPED_OFFLINE=8; not compared
  SKIPPED_OFFLINE: 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0 (network access is disabled)
affected transitions: none
enterprise freshness: NOT_INSTALLED
nothing could be read from the community remote
```

`CHECK_UNAVAILABLE` means no comparison ran, so the command cannot report success. The exit code is 4.

`ODOOFLUX_OFFLINE=1 python3 -m odooflux knowledge check --kb-home /tmp/kb012` gives the same output and exit code 4 (verified).

### 2.2 Online check (not executed here)

```bash
odooflux knowledge check                      # online: one ls-remote per repository, nothing downloaded
odooflux knowledge check --json               # canonical JSON (schema odooflux.knowledge-check/1)
```

An online check is the explicit network authorization for that run. It reads branch heads with `git ls-remote --heads --refs`. Community sources are read without credentials. Enterprise sources are read only with a token. Without a token the Enterprise sources are `SKIPPED_NO_CREDENTIALS`; a rejected token is `AUTH_FAILED`; an unreachable remote is `UNAVAILABLE`. These statuses are never merged.

Reading the output:

- `KNOWLEDGE_UPDATE_AVAILABLE` / `SOURCE_REVISION_AVAILABLE`: a source moved; an update would build.
- `NEW_VERSION_DISCOVERED`: a new numeric major branch exists. The line `Migration support: not established` is printed. It is never a supported target.
- `NO_UPDATE`: every Community source was read and matches; no new version; no installed Enterprise source was unreadable.
- `CHECK_UNAVAILABLE`: no Community source could be read. Exit 4.
- `LOCAL_STATE_INVALID`: the installed release state cannot be trusted. Exit 1, and no remote is contacted.

## 3. Dry run an update (verified output)

A dry run reads remote metadata like `check` (none with `--offline`). It downloads nothing, builds nothing, installs nothing, activates nothing, appends nothing to the history and takes no lock.

```bash
python3 -m odooflux knowledge update --offline --dry-run --kb-home /tmp/kb012
```

Captured output, abridged (exit 1). Lines marked `...` are the per-source reason lines for the 9 Community and 9 Enterprise branches, omitted here for length; they follow the same pattern as the two shown:

```text
OdooFlux Knowledge Update

outcome: BLOCKED

reason: CHECK_UNAVAILABLE: remote check unavailable; no update is decided offline
reason: odoo-community-12.0: remote not read (SKIPPED_OFFLINE) (CHECK_UNAVAILABLE); not installed, skipped
... (one line per Community branch 13.0 to 19.0)
reason: odoo-enterprise-12.0: no Enterprise credentials (ENTERPRISE_REQUIRED_UNAVAILABLE); not installed, skipped
... (one line per Enterprise branch 13.0 to 19.0)

mode: dry run, offline, no remote contacted
check status: CHECK_UNAVAILABLE
sources checked: comparison unavailable
new versions: comparison unavailable
updated versions: comparison unavailable

knowledge changes:
  not computed (no build ran)

release:
  integrity digest: not computed
  activation: not attempted
  completeness: not computed
  active release id: none (built-in knowledge only)

enterprise: SKIPPED_OFFLINE, freshness NOT_INSTALLED

limitations:
  - migration support not established
  - production certification not granted

support dimensions:
  source availability: reported per source (verified provenance of the acquired snapshot)
  knowledge completeness: reported from the release (COMPLETE or PARTIAL)
  migration support: not established by an update
  production certification: NOT_GRANTED
```

Verified on the same kb-home: after the dry run the directory was empty (no `updates/` directory was created).

`--json` prints the same result as canonical JSON with schema `odooflux.knowledge-update/1` (verified: `outcome` `BLOCKED`, schema string as stated).

## 4. Apply an update (verified offline; online flow not executed)

### 4.1 Offline apply (verified)

```bash
python3 -m odooflux knowledge update --offline --kb-home /tmp/kb012
```

Offline, the check cannot run, so nothing is built. The outcome is `BLOCKED` (exit 1), and a `BLOCKED` record is appended to the history. This is the only write an offline apply makes:

```text
outcome: BLOCKED
reason: CHECK_UNAVAILABLE: remote check unavailable; no update is decided offline
...
mode: apply, offline, no remote contacted
...
activation: not attempted
...
```

The directory after this run contains `updates/.update.lock` and `updates/history.jsonl`. Nothing else changes: no release directory, no active pointer.

### 4.2 Online apply (not executed here)

```bash
odooflux knowledge update                         # check, acquire changed sources, build, activate if allowed
odooflux knowledge update --json                  # the UpdateResult as canonical JSON
odooflux knowledge update --require-enterprise    # BLOCKED unless the Enterprise sources can be refreshed
odooflux knowledge update --from 16 --to 17       # only the 16 -> 17 transition (both flags together)
```

What an online apply does, from the code (`knowledge/update/orchestrator.py`):

1. Takes the update lock `<kb-home>/updates/.update.lock`. A second concurrent run waits up to 5 seconds, then reports `BLOCKED` with `CONCURRENT_UPDATE` and records nothing.
2. Verifies the history chain and the installed state. A broken chain or an invalid installed release is `BLOCKED` before any network call.
3. Discovers remote heads, plans, and fetches only the sources that changed (by commit SHA, verified). Unchanged Community sources are not fetched. Installed Enterprise sources that cannot be read are carried forward byte-identically.
4. If the plan says NOOP and the build inputs equal the last ACTIVE or NOOP record, the outcome is `NOOP` and no release is built.
5. Otherwise builds with the 17-step pipeline in `<kb-home>/staging/update/`, evaluates activation, and only when allowed swaps the active pointer once.

Outcomes and exit codes are in [section 7](#exit-codes).

Notes:

- `--from` and `--to` must be given together. Given one alone, the command exits 2 (verified: `ERROR: --from and --to must be given together`).
- `--require-enterprise` without a token is `BLOCKED` and recorded (unit-tested).
- A run with no extract toolkit attached is a usage error (exit 2). The `odooflux` CLI always attaches it.

## 5. Status and history (verified)

### 5.1 Status

```bash
python3 -m odooflux knowledge status --kb-home /tmp/kb012
python3 -m odooflux knowledge status --json --kb-home /tmp/kb012
```

Captured output on a kb-home with no release (exit 0; reads only, never networks, never creates a directory):

```text
OdooFlux Knowledge Status
knowledge: built-in
active release: none (built-in knowledge only)
digest: 8bb139d0d4ad0516a917255796321bb67a2058a163e5eafdd52f61fd6e8483ea
completeness: not recorded
steps covered: none recorded
installed sources: none recorded
detection rules: 91 (DETECT_ONLY=78, DRAFT=3, FIX_ENABLED=10)
fix-enabled rules: 10
certification-governed rules: 0
last successful update: none recorded
limitations:
  - migration support not established
  - production certification not granted
  - Enterprise freshness unknown without a check
```

The JSON form has schema `odooflux.knowledge-status/1`; its `kind` is `built-in` when nothing is installed. The `FIX_ENABLED=10` rules are the shipped built-in rows; they are trusted by byte identity (see the guide, section 9).

Exit codes: 0 read; 1 local state invalid (an unusable active release, an invalid installed state or a broken history chain). On exit 1 nothing is printed to stdout and the problem goes to stderr.

### 5.2 History

```bash
python3 -m odooflux knowledge history --kb-home /tmp/kb012
python3 -m odooflux knowledge history --limit 5 --kb-home /tmp/kb012
python3 -m odooflux knowledge history --json --kb-home /tmp/kb012
```

Captured output after the offline apply in section 4.1 (exit 0):

```text
OdooFlux Knowledge History
chain: verified
#1 2026-11-09T15:17:09Z BLOCKED
  release: none -> none
  sources: none
  changes: not recorded
  activation: not recorded
  failure reason: CHECK_UNAVAILABLE: remote check unavailable; no update is decided offline
```

Newest entries first. `--limit N` keeps the newest N (N must be a positive integer; `--limit 0` is a usage error, exit 2, verified).

Tamper check (verified on a copy): changing `BLOCKED` to `FAILED` inside `updates/history.jsonl` makes both `history` and `status` exit 1 with `ERROR: update history is not valid: history.hash_mismatch line 1: entry content does not match entry_hash (edited)` on stderr and nothing on stdout.

## 6. Recovery, rollback and deactivation

The update verbs do not have a rollback of their own beyond the atomic pointer. The release verbs of feature 011 remain the operator tools:

```bash
odooflux knowledge release list --kb-home $ODOOFLUX_KB_HOME        # installed releases
odooflux knowledge release show <release_id> --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge release activate <release_id> --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge release rollback --kb-home $ODOOFLUX_KB_HOME    # activate the previous release
odooflux knowledge release deactivate --kb-home $ODOOFLUX_KB_HOME  # return to built-in knowledge
odooflux knowledge release audit-verify --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge release remove <release_id> --kb-home $ODOOFLUX_KB_HOME   # only an inactive release
```

What the update does on failure:

- A failure before the pointer swap leaves the previous pointer as it was. The outcome is `BLOCKED` or `FAILED`, recorded in the history.
- A failure during the swap is `ROLLED_BACK` (the pointer still names the previous release) or `FAILED` (the pointer cannot be read back). Exit 3 or 4.
- A `BLOCKED` decision never touches the pointer.

Stale locks: the update lock is an `flock` held by a running process; it is released when the process exits. The managed cache under `<kb-home>/updates/cache` and the staging directory `<kb-home>/staging/update` are working data. The update does not delete them as part of a failure; `release remove` only deletes inactive installed releases.

Do not edit `updates/history.jsonl` by hand. A broken chain stops `update`, `status` and `history`. Recover by restoring the file from a backup, not by editing it.

## 7. Exit codes

### 7.1 `knowledge check`

| Exit | Meaning |
|---|---|
| 0 | Check completed. Updates may be available. |
| 1 | Local knowledge state invalid (`LOCAL_STATE_INVALID`). No remote contacted. |
| 2 | Usage error. |
| 4 | `CHECK_UNAVAILABLE`: no Community source could be read, or the catalog could not be loaded. Also offline. |

### 7.2 `knowledge update`

| Exit | Outcome | Meaning |
|---|---|---|
| 0 | `ACTIVE` | A new release was activated. |
| 0 | `NOOP` | Nothing relevant changed. No release built. |
| 0 | `DRY_RUN` | Plan only. Nothing written. |
| 1 | `BLOCKED` | A gate or activation rule refused the update. Nothing was activated. Includes offline runs (`CHECK_UNAVAILABLE`). |
| 2 | (usage) | `--from` and `--to` not given together; no extract toolkit attached; bad arguments. |
| 3 | `ROLLED_BACK` | The swap failed and the previous release is still active. |
| 4 | `FAILED` | A required source failed, the build failed, or the outcome was `ACTIVE`, `NOOP` or `DRY_RUN` with `CHECK_UNAVAILABLE` (no comparison ran, so the run is not a success). |

### 7.3 `knowledge status` and `knowledge history`

| Exit | Meaning |
|---|---|
| 0 | Read. |
| 1 | Local state invalid: broken history chain, unusable active release or installed state. Stdout is empty; the reason goes to stderr. |
| 2 | Usage error (`--limit` not a positive integer). |

Verified: `--limit 0` exits 2; a tampered history exits 1 for both verbs.

## 8. Common flags

| Flag | Verbs | Meaning |
|---|---|---|
| `--kb-home PATH` | all four | kb-home directory. |
| `--json` | all four | Canonical JSON output (keys sorted). |
| `--offline` | `check`, `update` | No network call. Same as `ODOOFLUX_OFFLINE=1`. |
| `--dry-run` | `update` | Plan only. With `--offline`: no network at all. Without it: read-only remote metadata, like `check`. |
| `--from N --to M` | `update` | Restrict to the transition N to M. Both or neither. |
| `--require-enterprise` | `update` | Block unless Enterprise sources can be refreshed. |
| `--limit N` | `history` | Newest N entries. |

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `status: CHECK_UNAVAILABLE`, exit 4 | Offline, or no Community remote could be read. | Run online without `--offline`, and without `ODOOFLUX_OFFLINE`. Check network access to `github.com`. |
| `Enterprise ... SKIPPED_NO_CREDENTIALS` | No token configured. | Expected without access. Set `ODOOFLUX_ENTERPRISE_TOKEN` or `ODOOFLUX_ENTERPRISE_TOKEN_FILE` only if you have Enterprise access. |
| `AUTH_FAILED` for an Enterprise source | Token rejected or lacks access. | Check the token. Community is not affected unless `--require-enterprise`. |
| `WARNING: Enterprise token configuration is unusable (<CODE>)` | Token file permissions, size, symlink, or content. | Make the file a regular file, owner-only (for example `chmod 600`), no symlink, and no whitespace inside the token. |
| `ERROR: update history is not valid ...` (exit 1) | The history file was edited, truncated mid-line or corrupted. | Restore it from a backup. Do not edit it. |
| `ERROR: --from and --to must be given together` (exit 2) | One of the two flags is missing. | Give both. |
| `BLOCKED` with `CONCURRENT_UPDATE` | Another update is running. | Wait for it. Nothing was recorded. |
| `BLOCKED` with `ENTERPRISE_COMPAT` | A carried Enterprise module has a dependency that does not resolve in the candidate's inventory (existence check only), or there is no previous release to compare against. | Read the finding in the report. The previous release stays active. |
| `BLOCKED` with `CAPABILITY_LOST` / `CAPABILITY_DOWNGRADED` | A rule was removed or weakened without an approved equal replacement. | Read the report. The previous release stays active. |
| `NEW_VERSION_DISCOVERED` | A new numeric major branch exists upstream. | Nothing is migrated automatically. Migration support is not established for it. |

## 10. Online commands with live sources

Not executed for this feature's documentation. Run only when you have explicitly chosen to contact the official remotes, and understand that this is the network authorization for that run (decision D1). Enterprise sources need your own entitlement.

```bash
export ODOOFLUX_ENTERPRISE_TOKEN_FILE=$HOME/.config/odooflux/enterprise-token   # optional; owner-only file
odooflux knowledge check --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge update --dry-run --kb-home $ODOOFLUX_KB_HOME    # reads remote metadata only
odooflux knowledge update --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge status --kb-home $ODOOFLUX_KB_HOME
odooflux knowledge history --limit 10 --kb-home $ODOOFLUX_KB_HOME
```

The real-source pilot 16.0 to 17.0 is prepared, not run (NOT_RUN / NOT_AUTHORIZED; see [tasks.md](tasks.md#open-and-blocked-items)).
