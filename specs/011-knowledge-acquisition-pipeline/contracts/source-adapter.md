# Contract: Source Adapter

Module: `src/odooflux/knowledge/acquisition/` (REQ-KAP-006..010, 001, 007, 008). Stdlib only.

## Interface

```
class SourceAdapter(Protocol):
    kind: str                                   # SourceSpec.kind
    def probe(self, spec: SourceSpec) -> ProbeResult          # no writes; checks revision presence/auth
    def snapshot(self, spec: SourceSpec, store: BlobStore) -> SourceSnapshot
```

`ProbeResult`: `{available: bool, reason_code, detail}`. Adapters register in a dict keyed by `kind` in `acquisition/sources.py` (data-driven; no per-release code).

## Adapters (v1)

| Kind | Input | Method | Network |
|---|---|---|---|
| GIT_COMMUNITY, OCA, OPENUPGRADE | local clone path (`local:` url) | `git -C <p> cat-file -e <sha>^{commit}`, `ls-tree -r -z`, `cat-file blob` (pattern of `refresh.py`) | none |
| DOCS | local clone of odoo/documentation | same as git, `.rst` files only | none |
| UPGRADE_SCRIPTS | subset of GIT_COMMUNITY (`**/migrations/**`) | scope filter | none |
| ENTERPRISE_LOCAL | user-supplied local path or snapshot pack | directory/pack read; requires `--i-am-entitled` flag recorded in provenance | none |
| DIRECTORY, SNAPSHOT_PACK | path | read, hash | none |
| fetch (`acquisition/fetch.py`) | allow-listed https URL | urllib, only in `source fetch --allow-network` | yes, explicit only |

## Rules

1. Pinned revision unavailable: `probe` returns `REVISION_UNAVAILABLE`; `snapshot` raises `SourceError`; status `FAILED`; no snapshot written; never resolve a branch/tag/other SHA (REQ-KAP-009).
2. Revision for git kinds must match `^[0-9a-f]{40}$`; branch names are informational.
3. Official kinds must be under the allow-list (`official_sources/allow_list.json`); else `NOT_ALLOWLISTED`.
4. Enterprise: no credentials are read, stored or logged; no network; absent entitlement flag gives `SKIPPED_UNAUTHORIZED`. Community-only builds continue and list the exclusion in `limits` (REQ-KAP-007).
5. OCA/OpenUpgrade: `official=false` forced by the adapter, not by the spec file.
6. Every blob is sha256-hashed on write and verified on read; mismatch raises `SNAPSHOT_CORRUPT`.
7. Paths are normalized to relative POSIX; entries escaping the root, symlinks outside the tree, and non-UTF-8 names go to `limits.excluded` with a reason.
8. Snapshot output is deterministic (sorted entries); the same inputs give the same `snapshot_digest`.
9. Subprocess: `git` with argument lists, `-c core.fsmonitor=false`, no shell, timeout per call, env cleared except PATH and HOME-less config (`GIT_CONFIG_NOSYSTEM=1`).

## Errors

`SourceError(code, source_id, message)`; codes: `REVISION_UNAVAILABLE`, `NOT_ALLOWLISTED`, `AUTH_REQUIRED`, `CHECKSUM_MISMATCH`, `SNAPSHOT_CORRUPT`, `IO_ERROR`, `NETWORK_DISABLED`.

## Tests (names)

`test_pinned_missing_fails`, `test_no_substitution`, `test_snapshot_deterministic`, `test_blob_tamper_detected`, `test_enterprise_skipped_without_entitlement`, `test_oca_forced_unofficial`, `test_no_network_without_flag`, `test_symlink_escape_excluded`.

## Official local clone identity (added after implementation, S1g)

An official source with a `local:` URL must declare `expected_origin` (an https URL under the allow-listed prefix for its kind: `odoo/odoo` for GIT_COMMUNITY, `odoo/documentation` for DOCS). The git-local adapter checks, with local git commands only, that `remote get-url origin` equals `expected_origin` after normalisation (trailing `.git` and `/` stripped, host lower-cased, `git@host:org/repo` read as `https://host/org/repo`), that it is allow-listed, that the clone top-level is the repository, and that the pinned 40-hex commit exists. Any missing remote, mismatch, non-allow-listed origin, missing `expected_origin` or absent commit fails the source with `OFFICIAL_IDENTITY_UNVERIFIED` (never downgraded, never substituted, nothing snapshotted). A verified clone records `origin_url` in its snapshot (optional field, not part of `snapshot_digest`). Release gate 1 uses the same helpers (`sources.py`): an official `local:` provenance entry counts only with an allow-listed verified `origin_url`, and its revision and digest must match the snapshot file in the release.

**Limit:** a configured Git remote URL is a declared identity, not cryptographic proof of repository authenticity. The contract verifies consistency between the declaration, the allow-list, the pinned commit and the content digest. A malicious local clone with a forged origin is a residual risk that only an external trust anchor (signed tags or maintainer-published hashes) could close.
