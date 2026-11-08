# Contract: Knowledge Package Format and Safe Handling

Module: `src/odooflux/knowledge/package/` (REQ-KAP-022..028, 047). Container and limits: research R4.

## Layout

See research.md R4. Required entries: `package.json`, `release.json`, `integrity/SHA256SUMS`, `knowledge/` complete tree, `coverage/coverage-manifest.json`, `provenance/sources.json`. Optional: `ledger/`, `history/`, `fixtures/`.

## package.json

```
{ "format": "odooflux.package/1", "release_id": "kr-...", "release_digest": "<sha256>",
  "created_with": "odooflux X.Y.Z",
  "compat": {"min_framework": "X.Y.Z", "max_framework": null, "schemas": {"evidence": "1", "rule_metadata": "1", ...}},
  "entries": [{"path": "...", "sha256": "...", "size": 123}], "entry_count": n, "total_size": n,
  "contains_enterprise_derived": false, "redaction_scan": {"status": "PASSED", "scanner_version": "1"} }
```

## Reader rules (every one is rejection, nothing installed)

| Id | Check |
|---|---|
| P01 | name: UTF-8, no NUL, no `\`, not absolute, no drive letter, no `..` or `.` segment, no empty segment, length and depth within limits, NFC form |
| P02 | duplicate names, including case-insensitive and Unicode-normalised duplicates |
| P03 | entry is a regular file (reject directories-as-data, symlink and hardlink via `external_attr` mode bits, devices) |
| P04 | entries set equals manifest `entries` set exactly (no extra, none missing); `entry_count`, `total_size` match |
| P05 | declared size within caps; actual streamed bytes within caps and equal to declared; ratio cap |
| P06 | sha256 of each entry equals manifest; `SHA256SUMS` equals manifest; `release_digest` recomputes from `release.json` |
| P07 | `format` known; `compat` satisfied by running framework (REQ-KAP-047); schema versions known |
| P08 | encrypted entries, non-STORED/DEFLATED compression, zip64 over caps, multi-disk: rejected |
| P09 | redaction scan of text entries: secret-shaped or absolute-path strings in non-allowlisted fields reject (REQ-KAP-028) |
| P10 | every FIX_ENABLED rule re-gated locally (REQ-KAP-027): default reject; `--downgrade-unverified` caps and records |
| P11 | tree validation: `knowledge validate` on staged tree, errors reject |

## Reader algorithm

1. Open ZIP, read central directory only; run P01-P05, P08 on headers.
2. Create a new empty staging dir under `<kb-home>/staging/<uuid>/` (mode 0700). For each entry: resolve target, assert `is_within(target, staging)`, create parents, stream with caps, hash while writing, `open(..., 'xb')` (exclusive create).
3. Run P06, P07, P09, P10, P11 on staging. Any failure: delete staging, raise `PackageError(code, entry)`; nothing else touched.
4. Success: staging becomes the release dir via `os.replace` (same filesystem, so rename is atomic); release state `INSTALLED`.

## Writer (export)

Inputs: release dir. Entries sorted bytewise by path, fixed ZipInfo fields (research R4), manifest from `release.json` + file hashes, `SHA256SUMS` sorted. Refuses to include absolute paths, files outside the release dir, `staging/`, snapshots (source blobs are never exported; provenance is digests only), or Enterprise-derived records unless allowed (OD-K6). Honors `SOURCE_DATE_EPOCH` only for `build.build_time` in `release.json`, not for ZIP timestamps. Self-check: re-read the written file with the reader before declaring success.

## Content rules

Allowed: rules, evidence, schemas, version metadata, ledger, history, provenance (urls, revisions, digests), coverage manifests, synthetic fixtures. Forbidden: secrets, tokens, customer data, absolute paths, hostnames, usernames, Enterprise source text, raw source blobs.

## Errors

`PackageError.code` in `P01..P11`, `LIMIT_EXCEEDED`, `ZIP_CORRUPT`. Exit code 3 for package rejection (CLI contract).

## Tests (table-driven malicious archive generator in tests helper)

`test_reject_traversal`, `test_reject_absolute`, `test_reject_backslash`, `test_reject_duplicate_entry`, `test_reject_casefold_duplicate`, `test_reject_symlink`, `test_reject_zip_bomb_ratio`, `test_reject_oversize_header_lie`, `test_reject_extra_entry`, `test_reject_missing_entry`, `test_reject_bad_sha`, `test_reject_incompatible_framework`, `test_reject_secret_canary`, `test_reject_unverified_fix_enabled`, `test_downgrade_option_caps`, `test_failure_leaves_kbhome_untouched`, `test_export_deterministic`, `test_roundtrip_digest_equal`.
