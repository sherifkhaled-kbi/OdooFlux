# R4 round-2 review (read-only)

Scope: rollback "already" action, dedup/retire rows, AI authorization `missing()`, AST and rule-order memoisation.
No product code or tests were edited. Nothing committed. Repro: `/tmp/r4chk-Utx0/repro.py` (throwaway).

## 1. Rollback "already" (rollback.py, cli/commands.py) - VERDICT: OK for the new action, two DEFECTs found

"already" fires only when the file already holds its pre-run state (rollback.py:13-19, 39-41), so no file that
needs restoring is skipped. Conflict detection still runs for every other state. The defects below are in
or next to the same code.

- DEFECT (pre-existing, reproduced): a run that logs two write events for one path cannot be rolled back.
  rollback.py:50-52 compares the backup with the second entry's `sha256_before` (the run's intermediate bytes),
  raises `RuntimeError`, and leaves the file at the run output. Reproduced twice in a row: both attempts raise,
  final bytes `Z`. Reachable: run.py:259 runs the AI escalation pass after the deterministic promote, on the same
  run and module paths (ai_pass.py `_writer`). I did not confirm end-to-end that escalation re-edits an already
  promoted file.
- RISK (pre-existing ordering, new message): rename rollback unlinks the new path (rollback.py:53-54) before
  writing the source (line 55). A crash between the two leaves neither file. The next rollback reports
  `conflict ... changed after the run` (exit 1) although the backup holds the bytes. Fix: write the source first,
  then unlink the new path.
- GAP: a file deleted by the user after the run (not created by the run, not renamed) is reported as a conflict
  and not restored (rollback.py:42-44). This is conservative, but the wording "changed after the run" is misleading.
- MINOR: commands.py:61-63 prints "already rolled back" for any run whose files all match pre-run bytes, including
  a manual `git checkout`. The state is still set to ROLLED_BACK. Not unsafe.
- TEST GAPS (tests/regression/test_fix_rollback_idempotency.py:48-74): no partial or mixed state (one restored,
  one already, one conflict), no created-file case, no rename, no deleted file, no double-write. The conflict
  assertion only checks `"conflict" not in stdout`.

## 2. Dedup and retire rows - VERDICT: dedup OK; gated rows are a behaviour decision needing sign-off

- `deduplicate` / `retired_duplicate` (knowledge_rules.py:142-158): every drop has a surviving reporter.
  The only retired category is "Page Attrs" (legacy_overlap.py:32). It is dropped only when, on the same
  file and line, an "Attrs Attribute" issue or the knowledge id `16-17.xml.attrs-removed` is in the input.
  "Attrs Attribute" is an always-on row (legacy_rules.py:263) and is never dropped, so it survives. A knowledge
  issue is dropped only by `covered()`, which needs a non-retired legacy sibling on that line, and that sibling
  survives. Caveat: the surviving message is the generic attrs text, so the page-specific message is lost.
- STALE DOCSTRING: legacy_overlap.py:8 still says "nothing is retired here", which contradicts lines 30-32.
- DECISION / DEFECT-RISK (legacy_rules.py gate `min_ver=12` at lines 113, 164, 168, 172, 176, 200, 229, 233,
  237, 247; gate logic check_content:899). The gate works: these rows fire only when from_version < 12. These are
  the ten pre-12 "retire" rows in legacy_disposition.json. On 12+ runs no other rule reports them: no knowledge
  rule covers openerp, `_columns`, `_defaults`, `ir.values` or html_sanitize. The disposition evidence says the
  constructs are absent or broken in 12.0 itself (EV-205: no top-level openerp package; "12.0 has no _columns
  attribute handling"; "Model absent in 12.0"). A 12.0 module that still contains them therefore gets zero
  findings for a 12->13 run. test_legacy_precedence.py asserts this on purpose, so it needs an owner decision.
- FIXER MISMATCH (new with the gate): `apply_python_fixes` (legacy_rules.py:663-690) is not gated. It still
  rewrites `openerp.` (line 665), html_sanitize (680-683) and `print` (685) on every run, including 12+. With
  `--fix`, a 12->13 run edits these files and reports nothing for them. This is the AR-R4-1(b) item, but the
  round-2 gate makes the mismatch visible.

## 3. AI authorization `missing()` and gateway `_block` - VERDICT: OK (D-08 unchanged)

- `missing()` (authorization.py:63-66) is a pure read. It only returns requested categories that are not granted,
  and grants are never widened. `check()` decides the outcome.
- The detail string (gateway.py:58-61) is `authorization:missing=<category names>`. Those names come from the
  fixed set built at prompts/builder.py:170 (`source_python`, `source_xml`, `evidence_excerpt`). No content or
  path reaches `data_categories`. A provider mismatch returns plain "authorization". Nothing under src/odooflux/ai
  reads `AIResponse.detail` (grep), and types.py:83 documents it as content-free.
- No new send path: the check order in `_block` is unchanged, and the denial still happens before any adapter call.
- HARDENING (minor): `missing()` would echo any string a future caller puts in `data_categories`. Intersecting
  with DATA_CATEGORIES in `missing()` removes that risk.

## 4. Memoisation - VERDICT: OK, with one convention-only risk

- astnodes.py: no `id()`-keyed caches anywhere (grep found none). The caches (`_NODES`, `_BUCKETS`, `_FILTERED`)
  are attributes on the tree, so they die with it. The `nodes_of` fallback for base classes (line 66) is correct.
- Convention-only risk: `parse()` (astnodes.py:16-28) returns the same tree object for identical source text
  across callers. Immutability is documented, not enforced. grep found no AST mutation in the consumers. Any
  future mutation would silently corrupt `_NODES`/`_BUCKETS` for every later parse of that text. Add a test or a
  guard.
- `_PARSED` is an unsynchronised OrderedDict. This is safe today because parallel.py uses processes (fork), not
  threads. It would not be safe under threads.
- order_rules memo (step_runner.py:27, 30-43): the key is the content signature (keys plus edges), not object
  identity, and `topo_order` is deterministic (sorted, heap-based), so the order cannot go stale. Rule objects are
  taken from the current `by_key`. Cycles raise before caching. Cross-run state is only the order tuple. Bounded
  at 64 entries.

## Dangerous items (priority order)
1. Double-write in one run makes rollback raise and leave the file changed (rollback.py:50-52). Pre-existing, reachable via the AI pass.
2. Rename rollback crash window (rollback.py:53-55): data reachable only from backup, reported as conflict.
3. 10 pre-12 rows gated off on 12+ with no other reporter, plus the unchanged fixers (legacy_rules.py:113-247, 663-690). Owner decision.
