# Research and Decisions: Knowledge Acquisition Pipeline

Format: Decision, alternatives considered, rationale, consequences. All unverified repo facts are marked VERIFY and each owning task re-checks them.

## R1. JSON, not YAML

| Option | Verdict |
|---|---|
| JSON (stdlib `json`) | CHOSEN. ADR-009 already fixes it; schemas and validator exist; canonical form is simple. |
| YAML | Rejected: no stdlib parser (ADR-002), ambiguous scalars, non-canonical. |
| TOML | Rejected for data: no stdlib writer, poor for nested records. |

Canonical JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` for digests; files on disk keep the repo convention (`indent=2`, trailing newline, `sort_keys=True`). Digest of a file is sha256 of its bytes; digest of a manifest is sha256 of its canonical JSON with `release_digest` removed. Floats are forbidden in digested manifests (use integers or strings) to avoid formatting drift. New helper `release/canonical.py` is the single place (assessment section 9 noted none exists). Existing `ai/caching/cache.py` and `refresh.py` writers stay untouched.

## R2. Content-addressed records

| Option | Verdict |
|---|---|
| Name by content hash (`objects/sha256/ab/<hex>`) for source blobs | CHOSEN for snapshots: dedupes, verifies on read, trivial integrity. |
| Release id derived from manifest digest (`kr-<12 hex>`) | CHOSEN: same inputs give the same id; id is not a free label. A human `label` is metadata. |
| Evidence/rule/ledger records keep stable semantic ids (EV-nnn, rule ids, CH-hash) and carry optional `content_sha256` for the bytes they cite | CHOSEN: existing file-name-equals-id check (E001 family) stays valid. |
| Hash-named rule or evidence files | Rejected: breaks `file name equals id`, reviewers read ids. |

Change id: `CH-` + first 16 hex of sha256 of `"{from_digest}|{to_digest}|{domain}|{kind}|{subject_key}"`. Stable across reruns; independent of ordering and time.

## R3. SQLite rejected

| Need | File-based answer |
|---|---|
| Lookup of changes by id | ledger shards by `step` and domain; load into dict in memory (ledgers are thousands, not millions) |
| Join evidence to rules | existing loader already loads 200 evidence files into memory |
| Atomicity | atomic write of one `active.json` and directory rename |
| Concurrency | single-writer maintainer tool; advisory lock file in kb-home |

Evidence threshold to revisit (recorded for OD-K12): ledger over 500 000 entries per release or measured load time over 5 s on the reference machine from the benchmark protocol, shown by a benchmark committed with the proposal. Until then SQLite is out (REQ-KAP-003, import-graph test).

## R4. Package format: ZIP (`.ofkp`)

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| ZIP via stdlib `zipfile` | central directory lists all entries and sizes before any extraction; no symlink or device semantic needed (reject via `external_attr`); deterministic if timestamps and order fixed | zip-slip class, bombs | CHOSEN, with pre-flight checks |
| tar.gz via `tarfile` | familiar | symlink, hardlink, device, absolute names, sparse; streaming only so total size unknown ahead; `extractall` footguns | Rejected |
| Plain directory + manifest | easy | not one file, no atomic transport | Used inside kb-home only |
| Custom container | none | invented format | Rejected |

Package layout (all names relative POSIX, UTF-8 NFC, no leading `./`):

```
package.json                  # package manifest (contract knowledge-package-format.md)
release.json                  # release manifest (data-model)
knowledge/...                 # complete knowledge tree
coverage/coverage-manifest.json
ledger/<step>.ledger.json
provenance/sources.json
history/...                   # rule and release history
fixtures/...                  # optional test fixtures, synthetic only
integrity/SHA256SUMS          # sha256  size  path, sorted, LF
```

Determinism: entries sorted by name, `ZipInfo.date_time = (1980,1,1,0,0,0)`, `create_system = 3`, `external_attr = 0o100644 << 16`, `compress_type = ZIP_DEFLATED`, `compresslevel = 6`, no extra fields, no comments. Note: DEFLATE output is stable for a fixed zlib version but not across zlib versions; the reproducibility test therefore compares the sha256 manifest and the release digest, and the byte-equality test runs in one interpreter. If cross-version bytes matter, use `ZIP_STORED` (OD-K2 decides; default DEFLATED).

Limits (defaults in `package/limits.py`, overridable only downward by flags): entries 20 000; per-entry 64 MiB; total uncompressed 1 GiB; compression ratio 200:1 per entry; path length 240; depth 12. Extraction streams each entry in 64 KiB chunks and aborts at the cap, never trusting header sizes alone.

## R5. Snapshot archive format

Snapshots are not tar/zip downloads. Internal form: `snapshots/<snapshot-id>/snapshot.json` (manifest: sorted `path, sha256, size, mode_kind`) and shared `objects/`. Input adapters read: local git clone (`git ls-tree -r`, `git cat-file` as `refresh.py`/`extract_view_index.py` already do), directory mirror, or a snapshot pack (a ZIP using the same reader and limits as `.ofkp`). Chosen over `git archive` tarballs to avoid tar attack surface and to reuse the existing git-plumbing pattern.

## R6. Extraction via structural parsers

| Domain | Parser (existing) | What is compared |
|---|---|---|
| Python/ORM | `parsers/python` (ast) | classes, `_name`/`_inherit`, fields and their keyword args, method signatures, decorators, `_sql_constraints`, route decorators (controllers), imports of removed symbols |
| XML (views, data, reports, security, QWeb) | `parsers/xml` (expat locator) | view ids and arch tag/attribute sets, `<record model>`, `ir.model.access` rows, record rules, groups, report actions, QWeb directives |
| JS/OWL | `parsers/javascript` lexer, adapter optional | exported symbols, `registry.category().add` keys, imports, template names. No adapter: file `UNSUPPORTED:no_js_adapter` |
| Manifest, dependencies | ast `literal_eval` of `__manifest__.py` | depends, version, data/assets lists, installable, license |
| Assets | manifest `assets` dict | bundle membership changes |
| Data files | CSV (stdlib `csv`), XML | ids added/removed |
| Migration scripts | file names `migrations/<ver>/{pre,post,end}-*.py` + ast of function bodies for model/field names touched | referenced renames; used for cross-check XC-UPGRADE (REQ-KAP-033), not as sole evidence |

Regex is allowed only to pre-filter (e.g. file kind by suffix). Classification input is always parsed structure. Rename detection: candidate pairing within the same domain and module using (a) identical signature/arity or attribute set, (b) token-set Jaccard of the body above a threshold from data (default 0.8), (c) one-to-one uniqueness. Output is `RENAMED_CANDIDATE` with `score`, `basis`, and `confirmed:false`. Ambiguous (one-to-many) pairings yield `UNKNOWN` plus candidates list.

## R7. Where installed releases live

kb-home default: `$XDG_DATA_HOME/odooflux/kb` (fallback `~/.local/share/odooflux/kb`; Windows `%LOCALAPPDATA%\odooflux\kb`), overridden by `--kb-home` or `ODOOFLUX_KB_HOME`. Separate from `ODOOFLUX_STATE_DIR` (ADR-013 run state) because knowledge outlives runs; recorded in OD-K1. Layout:

```
<kb-home>/
  active.json                 # {"release_id","digest","activated_at","previous":[...]}
  releases/<release-id>/      # complete tree as in package
  snapshots/<snapshot-id>/... and objects/sha256/..
  staging/<uuid>/             # import/build scratch, removed on success or failure
  audit.jsonl                 # hash-chained (core/recovery/audit_log.py)
  .lock
```

## R8. Other decisions

| Topic | Decision |
|---|---|
| Release completeness vs maturity | Separate (ADR-008 style): completeness describes pipeline coverage, maturity describes a rule. |
| Candidate to rule | `CandidateRule` is its own record; acceptance writes a `rule_metadata` row with `origin: GENERATED`, maturity DRAFT or DETECT_ONLY. Existing `rule_candidates.json` (43 seeded) is a different, older artifact; left untouched and linked by id in the ledger as `EXISTING_RULE_LINKED` where ids match. |
| Rule history | Sidecar `history/rules/<rule-id>.json` (append-only, hash-chained) rather than inline fields, so rule files and evidence stay byte-compatible and the rule schema gains only optional `origin` and `rev` (OD-K11 asks whether to inline). |
| Duplicate checks on built-in | Run as warnings only when called with `--strict-builtin`; default `knowledge validate` output unchanged (REQ-KAP-005). |
| AI proposals | `ai_proposer.py` only builds a minimised prompt from evidence excerpts (`evidence_excerpt` category), calls the existing gateway, parses a closed-schema JSON reply, and stores `AI_PROPOSED` items in `candidates/ai/`. They are never read by the gates as evidence. VERIFY gateway entry point in `ai/integration.py` and grants in `ai/authorization.py`. |
| Redaction | Use `utils/redaction.py` (richer: canary and shape scans). `utils/redact.py` left alone (OD-K9). |
| Audit | Reuse `core/recovery/audit_log.py` `AuditLog` with a kb-home path; VERIFY constructor accepts an arbitrary path (T-P2 task checks first). |
| Docs source | Docs adapter ingests a pinned `odoo/documentation` revision (git) and parses `.rst` headings and `versionchanged`/`deprecated` directives structurally (line-oriented parser, no HTML scraping). Rendered web docs are out of scope for v1. |
| Enterprise | Adapter accepts only a local path or snapshot supplied by the user; never network; derived records are marked `access: ENTERPRISE_AUTHORIZED` and excluded from exported packages unless `--include-enterprise-derived` and owner decision OD-K6. |
| Tags | SHA only for official git sources (tags are movable). |
| Time | `retrieved_at` and `created_at` are recorded in non-digested fields, or in digested manifests only via explicit `build_time` supplied through `SOURCE_DATE_EPOCH` for reproducible builds. |
| Concurrency | Single writer; lock file with PID check; readers never lock (immutable releases). |

## Open owner decisions

Nothing below is approved. Recommended defaults are used by the plan and are revisable.

| ID | Question | Recommended default |
|---|---|---|
| OD-K1 | kb-home location and env var | `ODOOFLUX_KB_HOME`, default XDG data dir; separate from state dir |
| OD-K2 | Package container and compression | ZIP (`.ofkp`), DEFLATE level 6; `ZIP_STORED` if cross-zlib byte equality is required |
| OD-K3 | Import of package with unverified FIX_ENABLED | refuse by default; `--downgrade-unverified` opt-in |
| OD-K4 | Report schema evolution | optional `knowledge_release`; `schema_version` 1.1.0 only when present (reading "increments on breaking changes" as allowing a minor bump) |
| OD-K5 | Package authenticity | none in v1; `--expect-digest` pin; signing deferred |
| OD-K6 | Enterprise and supplementary scope | v1: Enterprise by local path only, derived data excluded from packages; OCA/OpenUpgrade via local git/snapshot, labelled non-official |
| OD-K7 | Audit log | reuse hash-chained `AuditLog` in kb-home |
| OD-K8 | Named benchmark sets for recall | golden corpus (42 review cases) plus synthetic fixture set; no recall claim otherwise |
| OD-K9 | Redaction module | `utils/redaction.py` |
| OD-K10 | Activate PARTIAL releases | allowed with report warning; `--require-complete-kb` opt-in to refuse |
| OD-K11 | Rule history inline vs sidecar; duplicate checks on built-in tree | sidecar; built-in checks opt-in |
| OD-K12 | Revisit SQLite | only above the threshold in R3 |
