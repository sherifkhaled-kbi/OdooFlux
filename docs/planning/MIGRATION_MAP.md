# Migration Map — current code → target structure

Maps every component of the legacy `odooflux.py` (1,801 lines, sha256 `384115fe…`) to its home in
the target layout ([PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)). It also records each
component's disposition, owner phase, and risks.

Dispositions:
- **Port**: move with minimal change.
- **Rewrite**: same responsibility, new design.
- **Replace**: superseded by a different mechanism.
- **Retire**: dropped, with rationale.

Line ranges were verified against the current file.

## 1. Component mapping

| Lines | Legacy component | Target location | Disposition | Phase | Notes / risks |
|---|---|---|---|---|---|
| 32–34 | Severity constants | `core/contracts/` (Finding.severity enum) | Port | P2 | Values kept (`CRITICAL`/`WARNING`/`INFO`) for report compatibility |
| 37–47 | `Issue` dataclass | `core/contracts/` `Finding` | Rewrite | P2 | Gains `id`, `rule_id`, span, evidence, `status`; `auto_fixable`/`fix_applied` replaced by maturity + re-scan status (F-REP-1) |
| 50–73 | `MigrationReport` + counters | `reporting/model/` `ModuleResult` | Rewrite | P2 | Counters derived from findings with status; adds status, validation, edits |
| 80–211 | `PYTHON_RULES` (29 rules) | `rules/python/` + `knowledge/compatibility/<step>.json` | Rewrite per rule | P5 | Each rule re-evidenced, then kept, corrected (NF-01, NF-02, F-PY-3) or retired (noise, F-VER-3/4) |
| 213–305 | `XML_RULES` (21) | `rules/xml/`, `rules/qweb/`, `rules/security/` | Rewrite per rule | P5 | `attrs`/`states` → converter (P4); chatter rules pending G-R-09 |
| 307–324 | `MANIFEST_RULES` (4) | `rules/manifest/` | Rewrite | P5 | Version rule becomes a step-independent hygiene rule (`*`) |
| 326–351 | `JS_TS_RULES` (6) | `rules/javascript/`, `rules/owl/` | Rewrite | P5 | Detect-only without the JS adapter (ADR-006); NF-04/NF-17 corrections |
| 353–361 | `CSS_RULES` (2) | `rules/assets/` | Rewrite or retire | P5 | Kept only with evidence |
| 364–406 | V18/V19 rule tables | `knowledge/compatibility/17-18.json`, `18-19.json` | Replace | P3, P5 | Target-exact tables replaced by step rules (F-VER-2) |
| 413–455 | `_IMPORT_MODULE_MAP`, `rewrite_import_paths` | `rules/python/` (12-13 step) + `transformers/` | Rewrite | P4, P5 | Token-aware, strings untouched (F-PY-7) |
| 457–506 | `fix_warning_exception` | `rules/python/` (16-17 step, EV-110) | Rewrite | P5 | Gated on the version where `Warning` disappears |
| 509–539 | `apply_python_fixes` chain | Individual rules in `rules/python/` | Replace | P0 (safety patch), P5 | P0 removes unsafe parts in legacy; P5 re-implements via Edits |
| 542–593 | `_convert_attrs_to_inline` | `transformers/` expression converter + `rules/xml/` | Rewrite | P0 (disable), P4 | Must emit Python expressions (F-XML-2, EV-109) |
| 596–643 | `_convert_states_to_invisible` | `transformers/` + `rules/xml/` | Rewrite | P0 (fix), P4 | No in-tag comment (F-XML-1) |
| 646–721 | `apply_xml_fixes` chain | Rules in `rules/xml/` | Replace | P5 | `tree`→`list` per EV-112; Python action dicts added (F-XML-7) |
| 724–760 | `_replace_chatter_div` | `rules/xml/` chatter rule | Rewrite | P5 | Depth-counter idea kept; span locator replaces string search |
| 763–782 | `apply_manifest_fixes` | `rules/manifest/` | Rewrite | P0 (suffix), P5 | Preserve suffix (F-MAN-1) |
| 785–793 | `apply_js_fixes` | `rules/javascript/` | Retire then rewrite | P0, P5 | Header injection retired (F-VER-6) |
| 800–816 | `_compile_rules`, compiled tables | `rules/shared/` loader | Replace | P2 | Loader validates metadata + evidence |
| 819–855 | `check_content` | `core/engine/` detection over Documents | Rewrite | P2, P4 | Whole-document, span-based (F-DET-1/2) |
| 858–867 | `_read_file` | `parsers/` Document loader | Rewrite | P2 | Keeps encoding/newline style for byte preservation |
| 870–898 | `_rules_for_file` | `rules/shared/` file-kind mapping | Replace | P2 | File kinds per [CONTRACTS.md](architecture/CONTRACTS.md#rule) |
| 901–912 | `_mark_auto_fixes_applied` | `core/engine/` re-scan diff | Replace | P0 (legacy), P2 | Over-reporting removed (F-REP-1) |
| 915–949 | `analyze_and_fix_file` | `core/orchestrator/` + `core/engine/` + `validation/syntax/` | Rewrite | P2 | Write moves to promote step (ADR-013) |
| 957–983 | `SKIP_DIRS`, gitignore helpers | `discovery/` | Rewrite | P2 | Correct ignore semantics (F-WALK-1) |
| 985 | `SCAN_EXTENSIONS` | `discovery/` file-kind table | Rewrite | P2 | Adds `.csv` (F-SEC-1) |
| 988–1019 | `_check_manifest_version` | `discovery/` source-version detection | Rewrite | P2 | `ast.literal_eval` (F-MAN-5, REQ-VER-006) |
| 1022–1058 | `walk_module` (+ `__openerp__` copy) | `discovery/` + `core/orchestrator/` | Rewrite | P0 (no write), P2 | Rename only during promotion (F-SAFE-1/5) |
| 1065–1152 | Colours, `print_report` | `reporting/terminal/` | Rewrite | P8 | Width-aware colour (F-REP-2) |
| 1155–1186 | `save_json_report` | `reporting/exporters/` JSON | Rewrite | P2 (schema), P8 | Versioned schema (REQ-REP-001) |
| 1193–1202 | `backup_module` | `core/jobs/` + `core/recovery/` | Replace | P0 (legacy), P2 | State dir outside scanned paths, verified (F-SAFE-2/3) |
| 1209–1255 | Claude constants, system prompt | `ai/providers/` (Anthropic adapter), `ai/prompts/` | Rewrite | P6 | Model configurable; prompt versioned |
| 1257–1288 | Prompt builders | `ai/prompts/` | Rewrite | P6 | Region-level context (REQ-AI-004) |
| 1290–1323 | `_call_claude_api` | `ai/providers/` transport | Rewrite | P6 | `stop_reason`, budgets, usage (REQ-AI-005/006) |
| 1326–1356 | Response parsing, syntax check, newline | `ai/` + `validation/syntax/` | Replace | P6 | AI output becomes Edits validated by the normal path |
| 1359–1520 | `ai_fix_all_modules` | `core/orchestrator/` AI escalation | Replace | P6 | No whole-file writes, no bundle (ADR-012) |
| 1527–1553 | `resolve_modules` | `discovery/` | Port | P2 | Adds dependency ordering (REQ-DEP-002) |
| 1555–1589 | `print_combined_summary` | `reporting/terminal/` | Rewrite | P8 | |
| 1592–1638 | `save_combined_json_report` | `reporting/exporters/` | Replace | P2, P8 | One schema for single and multi-module runs |
| 1645–1801 | `main()` | `cli/` | Rewrite | P2 | Root `odooflux.py` becomes a launcher at cut-over (ADR-001) |

## 2. CLI option mapping

| Current option | Target | Notes |
|---|---|---|
| `--module PATH` | `--module PATH` | Unchanged |
| `--modules PATH…` | `--modules PATH…` | Unchanged |
| `--addons-path DIR` | `--addons-path DIR` (repeatable) | Backups/state never inside it |
| `--from-version N` | `--from-version X.0` | Accepts `14` or `14.0`; optional when detection succeeds (REQ-VER-006) |
| `--to-version {18,19}` | `--to-version X.0` | Choices from the version registry (no hardcoded max, REQ-ARC-003) |
| `--fix` | `--fix` | Writes only after validation and verified backup |
| `--backup` | Always on in fix mode; `--no-backup` requires explicit confirmation flag | D-10 |
| `--dry-run` | `--dry-run` | Guaranteed no writes; shows planned diff |
| `--report FILE` | `--report FILE` + `--format json\|html\|sarif\|diff` | P8 |
| `--no-color` | `--no-color` (also honours `NO_COLOR`) | |
| `--skip NAME…` | `--skip NAME…` | Unchanged |
| `--show-fixed` | `--show-fixed` | Unchanged |
| `--filter-severity LEVEL` | Kept unchanged at cut-over ([003 contracts/cli.md](../../specs/003-core-architecture/contracts/cli.md)); renaming to `--min-severity` is a proposal under D-10, not planned work | D-10 |
| `--ai-fix` | `--ai` + `--ai-provider` + `--ai-consent` | AI off by default; consent required (D-08) |
| `--api-key KEY` | **Removed**; environment variable or secrets file only | D-10, REQ-AI-008 |
| `--ai-verbose` | `--verbose` scoped logging | D-10 |
| (none) | `--fail-on`, `--state-dir`, `--allow-unverified`, `--validate-intermediate`, `--runtime`; subcommands `odooflux plan`, `odooflux rollback <run-id>`, `odooflux resume <run-id>`, `odooflux versions` (normative: [003 contracts/cli.md](../../specs/003-core-architecture/contracts/cli.md)) | New |
| Exit 2/1/0 | Documented table (success / findings over threshold / rejected changes / tool error) | REQ-REP-005 |

## 3. Cut-over plan (ADR-001)

1. **P0–P1**: all changes go into the legacy `odooflux.py`; the characterisation suite pins its
   behaviour.
2. **P2**: build `src/odooflux/` alongside it. The legacy script stays the entry point.
3. **P2 exit**: when the characterisation suite passes against the new CLI (or each difference is
   documented), the root `odooflux.py` becomes a launcher. It inserts `src/` on `sys.path` and
   calls `odooflux.cli.main`. This happens in one reviewed commit with a rollback note.
4. Legacy option aliases remain for one release; removals follow D-10.

## 4. Planned interfaces and structural dependencies

Interfaces are defined in [architecture/CONTRACTS.md](architecture/CONTRACTS.md). Allowed
dependency direction (enforced by an import-graph test, REQ-ARC-001):

```
cli → core/orchestrator → core/engine → core/contracts
core/orchestrator → discovery, versions, dependencies, validation, ai, reporting/model
rules → parsers, transformers, core/contracts, knowledge (data)
validation/* → parsers, rules (re-scan), core/contracts
reporting/* → reporting/model only
optional adapters (parsers/javascript, validation/runtime, ai/providers, reporting/terminal rich)
  ← imported lazily; never imported by core/*
```

## 5. Migration risks

| Risk | Mitigation |
|---|---|
| Behaviour drift during the rewrite | Characterisation suite (REQ-TST-004) plus documented differences |
| Rule semantics lost when rules are re-implemented | Per-rule mapping table in P5 (kept/corrected/retired, with evidence) |
| Users scripting legacy options | Aliases for one release, deprecation warnings (D-10) |
| Report consumers parsing legacy JSON | Report schema v1 documents the legacy-to-new field mapping; `--legacy-json` for one release is a proposal under D-10 (no task until approved) |
| Import shadowing at cut-over | Launcher approach; no package at repository root (ADR-001) |

## 6. Scaffolding created during planning

51 `.gitkeep` files, no other files under `src/` or `tests/`:

```text
docs/planning/phase-handoffs/.gitkeep
src/odooflux/ai/caching/.gitkeep
src/odooflux/ai/prompts/.gitkeep
src/odooflux/ai/providers/.gitkeep
src/odooflux/ai/usage/.gitkeep
src/odooflux/analyzers/.gitkeep
src/odooflux/cli/.gitkeep
src/odooflux/core/contracts/.gitkeep
src/odooflux/core/engine/.gitkeep
src/odooflux/core/jobs/.gitkeep
src/odooflux/core/orchestrator/.gitkeep
src/odooflux/core/recovery/.gitkeep
src/odooflux/dependencies/.gitkeep
src/odooflux/discovery/.gitkeep
src/odooflux/knowledge/compatibility/.gitkeep
src/odooflux/knowledge/evidence/.gitkeep
src/odooflux/knowledge/official_sources/.gitkeep
src/odooflux/knowledge/schemas/.gitkeep
src/odooflux/parsers/javascript/.gitkeep
src/odooflux/parsers/python/.gitkeep
src/odooflux/parsers/xml/.gitkeep
src/odooflux/reporting/exporters/.gitkeep
src/odooflux/reporting/html/.gitkeep
src/odooflux/reporting/model/.gitkeep
src/odooflux/reporting/terminal/.gitkeep
src/odooflux/rules/assets/.gitkeep
src/odooflux/rules/javascript/.gitkeep
src/odooflux/rules/manifest/.gitkeep
src/odooflux/rules/owl/.gitkeep
src/odooflux/rules/python/.gitkeep
src/odooflux/rules/qweb/.gitkeep
src/odooflux/rules/security/.gitkeep
src/odooflux/rules/shared/.gitkeep
src/odooflux/rules/xml/.gitkeep
src/odooflux/transformers/.gitkeep
src/odooflux/utils/.gitkeep
src/odooflux/validation/behavioral/.gitkeep
src/odooflux/validation/dependency/.gitkeep
src/odooflux/validation/runtime/.gitkeep
src/odooflux/validation/static/.gitkeep
src/odooflux/validation/syntax/.gitkeep
src/odooflux/versions/adapters/.gitkeep
src/odooflux/versions/graph/.gitkeep
src/odooflux/versions/registry/.gitkeep
tests/benchmarks/.gitkeep
tests/contract/.gitkeep
tests/golden_fixtures/.gitkeep
tests/integration/.gitkeep
tests/regression/.gitkeep
tests/runtime/.gitkeep
tests/unit/.gitkeep
```

## 7. Application files unchanged

The sha256 hashes of `odooflux.py`, `LICENSE`, `README.md`, and `.gitignore` were recorded before
scaffolding and re-checked after (`sha256sum -c`): all four match.
`odooflux.py` = `384115fe77431baad1ab0bc0c3acb3853a10da497da43dce2a1bd821f014c87e`.
