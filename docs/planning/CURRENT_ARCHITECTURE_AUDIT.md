# Current Architecture Audit

Audit of the repository **as it is today**. It builds on the earlier review
[../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../reviews/ODOO_MODULE_UPGRADER_AUDIT.md) and re-checks
each finding against the current code. It also adds findings from the official-source research in
[research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md). Nothing was fixed.

## 1. Baseline

| Item | Value |
|---|---|
| Commit | `c9914e6` ("Init for existing project"), branch `main`; working tree adds only planning files |
| Application source | `odooflux.py`, 1,801 lines, sha256 `384115fe77431baad1ab0bc0c3acb3853a10da497da43dce2a1bd821f014c87e` (identical to the version reviewed in the earlier audit) |
| Other files | `README.md` (title only), `LICENSE` (Apache-2.0), `.gitignore` (Python template) |
| Dependencies | Python standard library only; no packaging metadata, no lockfile |
| Tests | **None** (no `tests/` before planning scaffolding, no CI configuration) |
| Spec Kit | 1.3.1, integration `claude`, `feature_numbering: sequential`, features under `specs/NNN-name/`, no git branches created by scripts (ADR-015) |
| Constitution | 2.0.0 (amended during planning, approval pending D-01); 1.0.0 had mandated a single stdlib-only file |

Re-verification method (2026-11-06):
1. Confirmed the file hash matches the reviewed version.
2. Re-ran the Appendix A fixture of the earlier audit on a fresh copy in a new temporary
   directory: `--dry-run`, then `--addons-path … --fix --backup`, then `py_compile` and an XML
   parse.
3. Read every finding location again.

## 2. Component inventory

| Area | Location (`odooflux.py`) | What it does today |
|---|---|---|
| Data model | 32–73 | `Issue`, `MigrationReport` dataclasses; counters exclude `fix_applied` issues |
| Rule tables | 87–406 | Regex tuples `(min_src_ver, exact_tgt_ver, pattern, severity, category, message, suggestion, auto_fixable)` for Python, XML, manifest, JS/TS, CSS, plus 18/19-specific tables |
| Python fixers | 413–539 | Import path rewrite, `Warning`→`UserError`, decorator removal, `sudo`, `print`, `size=` removal |
| XML fixers | 542–760 | `attrs`→inline, `states`→`invisible`, `tree`→`list`, chatter replacement, `<openerp>`→`<odoo>` |
| Manifest/JS fixers | 763–793 | Version string overwrite; `@odoo-module` header and TODO comments for JS |
| Analyzer | 800–949 | Rule compilation, line-by-line detection, fix application, write, "fixed" marking |
| Walker | 957–1058 | `os.walk`, skip dirs, naive `.gitignore`, manifest version check, `__openerp__.py` copy/rename |
| Reporting | 1065–1186, 1555–1638 | Console (ANSI), JSON (single and combined) |
| Backup | 1193–1202 | `copytree` to a sibling directory |
| AI | 1209–1520 | One bundled Anthropic Messages API request via `urllib`; JSON response with full file contents; `.py` syntax check |
| CLI / main | 1527–1553, 1645–1801 | `--module/--modules/--addons-path`, `--from-version`, `--to-version {18,19}`, `--fix`, `--backup`, `--dry-run`, `--report`, `--no-color`, `--skip`, `--show-fixed`, `--filter-severity`, `--ai-fix`, `--api-key`, `--ai-verbose`; exit 2/1/0 |

### Cross-cutting observations

- **Version detection.** The manifest version prefix is compared with `--from-version`, and a
  mismatch is a WARNING (988–1019). The tool never infers the source version itself. Targets
  are limited to 18 and 19 by `argparse` choices.
- **Version model.** A single `min_src_ver` threshold plus an exact target. Fixers ignore
  `from_version` entirely (F-PY-9, F-VER-2).
- **Edit model.** None. Fixers are whole-file `re.sub` chains with no link to findings (A1 in the
  earlier audit).
- **Validation.** None before writes. The AI path syntax-checks `.py` only (F-VAL-1).
- **Recovery.** A backup copy only. There is no run log, rollback, checkpoint, or atomic write
  (F-SAFE-2…4).
- **Documentation.** `README.md` has only a title; usage exists only in the module docstring and
  `--help` epilog. The script is named `odoo_migrate_to_19.py` there (F-REP-2).

## 3. Classification vocabulary

| Classification | Meaning |
|---|---|
| `CONFIRMED_CURRENT` | Reported earlier **and** re-confirmed in this audit against the current code, by execution or by unambiguous code reading of unchanged lines |
| `PREVIOUSLY_REPORTED` | Reported earlier as a hypothesis about tool inputs or model output; still plausible because the code is unchanged, but not re-executed |
| `ALREADY_RESOLVED` | Reported earlier and no longer present in the current code |
| `REQUIRES_RUNTIME_VERIFICATION` | Its impact depends on Odoo runtime behaviour or a live AI provider, which planning did not execute |
| `NEW_FINDING` | Not in the earlier audit; found by the official-source research or by re-reading the code |

`ALREADY_RESOLVED` is **empty**: the application file is byte-identical to the reviewed version.

## 4. Classification of earlier findings (all 52)

Evidence levels follow the earlier audit: **RUN** reproduced by execution, **CODE** follows
from source, **HYP** hypothesis. `EV-…` are evidence records.

| ID | Summary | Classification | Evidence |
|---|---|---|---|
| F-XML-1 | `states=` fix inserts an XML comment inside the start tag → malformed XML | CONFIRMED_CURRENT | RUN (re-run: `ParseError` line 10) |
| F-XML-2 | `attrs` converted to domain lists instead of Python expressions; runtime effect unknown | REQUIRES_RUNTIME_VERIFICATION | RUN (output); runtime effect HYP; EV-109 confirms `attrs` rejected from 17.0 |
| F-XML-3 | `column_invisible` and other `attrs` keys dropped | CONFIRMED_CURRENT | CODE (548–560) |
| F-XML-4 | XML fixers not idempotent; duplicate `invisible=` possible | CONFIRMED_CURRENT | RUN (comment stacking); duplicate attribute HYP |
| F-XML-5 | Chatter fields deleted without inserting `<chatter/>` outside `oe_chatter` | CONFIRMED_CURRENT | RUN (unit probe) |
| F-XML-6 | `<chatter/>` placement not checked | CONFIRMED_CURRENT | CODE (724–760) |
| F-XML-7 | `view_mode` `tree` in Python action dicts not handled | CONFIRMED_CURRENT | CODE (660–686) |
| F-XML-8 | Asset templates, `t-esc/t-raw`, `kanban-box`, cron `numbercall`, shorthand tags not handled | CONFIRMED_CURRENT | RUN (asset template unreported); EV-113, EV-117, EV-119, EV-123 |
| F-PY-1 | Decorator removal leaves doubled indentation → `IndentationError` | CONFIRMED_CURRENT | RUN |
| F-PY-2 | `size=` removal leaves `fields.Char(, …)` → `SyntaxError` | CONFIRMED_CURRENT | RUN (re-run: `SyntaxError`) |
| F-PY-3 | `@api.returns` deleted unconditionally. **Re-stated:** the decorator exists through 18.0 and is removed in 19.0 (EV-102), so deletion is required for 19.0 targets and wrong for 18.0 targets. In both cases the return-value semantics need review. | CONFIRMED_CURRENT | RUN; EV-102 |
| F-PY-4 | `@api.one` removed without loop/`ensure_one()` → silent semantic change | CONFIRMED_CURRENT | RUN; EV-101 |
| F-PY-5 | `.sudo(False)` rewritten to `.with_user(False).sudo()` | CONFIRMED_CURRENT | RUN; EV-103 (flag form valid 13.0–19.0) |
| F-PY-6 | JS comment injected into Python | CONFIRMED_CURRENT | RUN |
| F-PY-7 | `openerp.`→`odoo.` applied inside strings | CONFIRMED_CURRENT | CODE (511) |
| F-PY-8 | Only single-line `print`; other Py2 constructs undetected | CONFIRMED_CURRENT | CODE (530) |
| F-PY-9 | Python fixers ignore `from_version` | CONFIRMED_CURRENT | CODE (509) |
| F-AI-1 | AI receives post-regex content with pre-regex line numbers | CONFIRMED_CURRENT | CODE (940–946 → 1392) |
| F-AI-2 | 180 KB bundle vs 16,384 output tokens; `stop_reason` unchecked | REQUIRES_RUNTIME_VERIFICATION | CODE; truncation needs a live provider |
| F-AI-3 | Only `.py` files eligible for AI | CONFIRMED_CURRENT | CODE (1375) |
| F-AI-4 | All issues in an AI-updated file marked fixed | CONFIRMED_CURRENT | CODE (1508–1510) |
| F-AI-5 | Bare-filename key fallback can cross-apply content | PREVIOUSLY_REPORTED | HYP (1483) |
| F-AI-6 | Hardcoded model ID; key on CLI; debug file written into module | CONFIRMED_CURRENT | CODE (1210, 1454, `--api-key`) |
| F-AI-7 | No protected-identifier check on AI output | CONFIRMED_CURRENT | CODE (1495–1506) |
| F-VER-1 | `<tree>` not flagged for 18→19 although fixed | CONFIRMED_CURRENT | CODE (264, 836); EV-112 |
| F-VER-2 | Rule schema cannot express deprecated/removed windows | CONFIRMED_CURRENT | CODE (80–85) |
| F-VER-3 | Factually wrong or misleading rules | CONFIRMED_CURRENT | CODE (92, 112, 143, 177, 255); EV-101/102 |
| F-VER-4 | INFO noise rules force exit code ≠ 0 | CONFIRMED_CURRENT | RUN (exit 2/1 after fix) |
| F-VER-5 | Missing detections (`name_get`, field `states`, `create(vals)`, v19 items) | CONFIRMED_CURRENT | RUN (`name_get`, Python `states=` unreported); EV-104, EV-108, EV-114…116 |
| F-VER-6 | JS: `rpc` suggestion, `@odoo-module` header on `odoo.define` file | REQUIRES_RUNTIME_VERIFICATION | RUN (output); EV-120, EV-121, EV-122; load failure HYP |
| F-VER-7 | Empty v19 rule tables | CONFIRMED_CURRENT | CODE (398–400) |
| F-MAN-1 | Manifest version suffix discarded | CONFIRMED_CURRENT | RUN |
| F-MAN-2 | Legacy `qweb` manifest key undetected | CONFIRMED_CURRENT | RUN; EV-123, EV-124 |
| F-MAN-3 | `depends` never checked | CONFIRMED_CURRENT | RUN |
| F-MAN-4 | Manifest file paths and load order never checked | CONFIRMED_CURRENT | CODE |
| F-MAN-5 | Manifest handled by raw regex; dead `\\s` regex | CONFIRMED_CURRENT | CODE (988–1019, 995) |
| F-SEC-1 | ACL CSV, record rules, groups not scanned | CONFIRMED_CURRENT | CODE (985); EV-114 shows a relevant rename |
| F-SEC-2 | `auth='none'`, `csrf=False`, `t-raw` not flagged | CONFIRMED_CURRENT | CODE |
| F-AST-1 | Two CSS rules only | CONFIRMED_CURRENT | CODE (353–361) |
| F-VAL-1 | No post-transform validation before write | CONFIRMED_CURRENT | RUN (re-run: invalid `.py` and `.xml` written) |
| F-VAL-2 | No structural or runtime validation | CONFIRMED_CURRENT | CODE |
| F-DET-1 | Line-based detection misses multi-line constructs | CONFIRMED_CURRENT | RUN |
| F-DET-2 | Duplicate reporting across overlapping categories | CONFIRMED_CURRENT | CODE (843) |
| F-SAFE-1 | Analyze mode writes `__manifest__.py` | CONFIRMED_CURRENT | RUN (re-run: also happens with `--dry-run`) |
| F-SAFE-2 | Backup created inside the addons path and re-scanned as a module | CONFIRMED_CURRENT | RUN (re-run: `kbi_demo_backup_<ts>` beside module) |
| F-SAFE-3 | Backup failure does not abort writes | CONFIRMED_CURRENT | CODE (1199–1202) |
| F-SAFE-4 | Non-atomic in-place writes | CONFIRMED_CURRENT | CODE (946) |
| F-SAFE-5 | Two manifests coexist after copy | CONFIRMED_CURRENT | RUN |
| F-REP-1 | Every auto-fixable issue in a changed file marked fixed | CONFIRMED_CURRENT | RUN (re-run: `fixed=21` with broken files) |
| F-REP-2 | ANSI codes break column widths; wrong script name in help | CONFIRMED_CURRENT | CODE (1570–1588, 7–9) |
| F-REP-3 | Exit codes overlap argparse; no `--fail-on` | CONFIRMED_CURRENT | CODE (1791–1797) |
| F-WALK-1 | Naive `.gitignore` translation | CONFIRMED_CURRENT | CODE (960–982) |

Counts: CONFIRMED_CURRENT 48, REQUIRES_RUNTIME_VERIFICATION 3 (F-XML-2, F-AI-2, F-VER-6),
PREVIOUSLY_REPORTED 1 (F-AI-5), ALREADY_RESOLVED 0. Total 52. Plus 19 NEW_FINDING items (§5).

## 5. New findings

| ID | Summary | Evidence |
|---|---|---|
| NF-01 | `@api.one`/`@api.multi` described as "removed in v14+"; they were removed in **13.0** | EV-101; rule text at `odooflux.py:92-94` |
| NF-02 | `odoo.exceptions.Warning` described as "removed in v14"; alias in 12/13, subclass in 14–16, removed in **17.0** | EV-110; `odooflux.py:197-210` |
| NF-03 | `<tree>` described as "deprecated in v18"; view type is `list` from 18.0. Acceptance of `<tree>` in 18.0 is unverified (G-R-07) | EV-112; `odooflux.py:263-266` |
| NF-04 | `odoo.define()` described as "removed in v17+"; the loader API `odoo.define(name, deps, factory)` exists in 17.0; legacy form unverified (G-R-08) | EV-122; `odooflux.py:327-329` |
| NF-05 | **`_sql_constraints` is silently ignored in 19.0** (warning only, constraints not created); no rule exists, so a "clean" v19 migration loses DB constraints | EV-116 |
| NF-06 | `name_get` removed in 18.0 (deprecated 17.0); no rule | EV-011, EV-104 |
| NF-07 | `user_has_groups` removed in 18.0; no rule | EV-105 |
| NF-08 | `_name_search` replaced by `_search_display_name` in 18.0; no rule | EV-008, EV-106 |
| NF-09 | Field parameter `states` unsupported from 17.0; no Python rule | EV-108 |
| NF-10 | `SavepointCase` removed in 17.0; module tests break; no rule | EV-111 |
| NF-11 | `ir.cron.numbercall` removed in 18.0; cron data files fail; no rule | EV-113 |
| NF-12 | `res.users.groups_id` renamed `group_ids` in 19.0 (Python, XML, CSV references); no rule | EV-114 |
| NF-13 | `@route(type='json')` is a deprecated alias of `jsonrpc` in 19.0; no rule | EV-007, EV-115 |
| NF-14 | `<act_window>`/`<report>` data-file tags removed in 17.0; current rules are WARNING and detect-only | EV-117; `odooflux.py:229-231` |
| NF-15 | `group_operator` renamed `aggregator` in 18.0; no rule | EV-010, EV-118 |
| NF-16 | `kanban-box` deprecated in 18.0 and gone from the 19.0 parser; no rule | EV-119 |
| NF-17 | `rpc` service removed in 18.0; the tool *recommends* it in its suggestion | EV-120; `odooflux.py:342, 790` |
| NF-18 | `--dry-run` (not only plain analysis) creates `__manifest__.py` (worse than F-SAFE-1 stated) | RUN (re-run) |
| NF-19 | The rule tables carry no evidence reference at all; nothing ties a rule to an official source | CODE (87–406) |

## 6. Prioritised assessment

Severity: **Critical** = corrupts or silently changes customer code, or writes when told not to;
**High** = wrong results likely to reach production; **Medium** = misleading or incomplete;
**Low** = cosmetic or edge case.

| ID | Severity | Classification | Evidence | Affected | Recommended remediation | Phase | REQ |
|---|---|---|---|---|---|---|---|
| F-VAL-1 | Critical | CONFIRMED_CURRENT | RUN | `odooflux.py:940-949` | Validation gate before write; reject on parse failure | P0 | REQ-SAF-002, REQ-VAL-001 |
| F-PY-1 | Critical | CONFIRMED_CURRENT | RUN | `odooflux.py:512-518` | Whole-line decorator removal; detect-only for `@api.one` | P0 | REQ-SAF-010 |
| F-PY-2 | Critical | CONFIRMED_CURRENT | RUN | `odooflux.py:531` | Comma-aware removal, covered by the gate | P0 | REQ-SAF-010 |
| F-XML-1 | Critical | CONFIRMED_CURRENT | RUN | `odooflux.py:596-643` | No in-tag comment; skip when `invisible=` exists | P0 | REQ-SAF-010 |
| F-SAFE-1 / NF-18 | Critical | CONFIRMED_CURRENT / NEW_FINDING | RUN | `odooflux.py:1045-1058` | Manifest copy/rename only in write mode | P0 | REQ-SAF-001, REQ-MAN-001 |
| F-SAFE-2 | Critical | CONFIRMED_CURRENT | RUN | `odooflux.py:1193-1202` | Backups in the state dir outside scanned paths | P0 | REQ-SAF-003 |
| F-SAFE-3 | Critical | CONFIRMED_CURRENT | CODE | `odooflux.py:1199-1202` | Abort module writes on backup failure | P0 | REQ-SAF-004 |
| F-PY-5 | Critical | CONFIRMED_CURRENT | RUN, EV-103 | `odooflux.py:524` | Rewrite only `sudo(<user expr>)` from 12.0 sources; never boolean literals | P0 | REQ-SAF-010 |
| NF-05 | Critical | NEW_FINDING | EV-116 | rule tables (absent) | Review-required rule for `_sql_constraints` on 19.0 targets; conversion to `Constraint` objects after research | P5 | REQ-PY-003 |
| F-XML-2 | Critical | REQUIRES_RUNTIME_VERIFICATION | RUN, EV-109 | `odooflux.py:542-593` | In P0, leave `attrs` untouched and report it; P4 expression converter | P0, P4 | REQ-XML-002 |
| F-REP-1 | High | CONFIRMED_CURRENT | RUN | `odooflux.py:901-912` | Fixed status from a re-scan diff | P0 | REQ-TRF-005 |
| F-AI-4 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:1508-1510` | Re-scan after AI writes | P0 (legacy), P6 | REQ-TRF-005, REQ-AI-003 |
| F-PY-3 | High | CONFIRMED_CURRENT | RUN, EV-102 | `odooflux.py:92, 518` | Version-gated: flag for review; removal only for 19.0 targets | P0 (stop removal), P5 | REQ-PY-003 |
| F-PY-4 | High | CONFIRMED_CURRENT | RUN, EV-101 | `odooflux.py:513-517` | Detect-only, review-required | P0 | REQ-SAF-010, REQ-PY-003 |
| F-XML-5 | High | CONFIRMED_CURRENT | RUN | `odooflux.py:695-718` | Do not delete chatter fields without replacement | P0 | REQ-SAF-010 |
| F-SAFE-4 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:946` | Atomic write helper | P0 | REQ-SAF-005 |
| F-MAN-1 | High | CONFIRMED_CURRENT | RUN | `odooflux.py:763-782` | Preserve the version suffix | P0 | REQ-MAN-002 |
| F-AI-1 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:1392` | Scan the exact content sent | P6 | REQ-AI-004 |
| F-AI-2 | High | REQUIRES_RUNTIME_VERIFICATION | CODE | `odooflux.py:1211-1212, 1290-1323` | Per-region requests, `stop_reason` check, budgets | P6 | REQ-AI-005 |
| F-AI-7 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:1495-1506` | Protected-identifier diff | P6 | REQ-AI-003 |
| F-VER-5 | High | CONFIRMED_CURRENT | RUN, EV-104/108/114–116 | `odooflux.py:87-211` | Evidence-backed rule catalogue | P5 | REQ-PY-002 |
| NF-06…NF-17 | High | NEW_FINDING | EV-104…EV-120 | rule tables | Add evidence-backed rules per step (see §5) | P5 | REQ-PY-002, REQ-XML-003, REQ-JS-002, REQ-ACL-001 |
| F-VER-1 | High | CONFIRMED_CURRENT | CODE, EV-112 | `odooflux.py:264, 836` | Deprecated/removed windows in the rule model | P2, P5 | REQ-VER-004 |
| F-MAN-3 | High | CONFIRMED_CURRENT | RUN | — | `depends` check against the per-version core list | P5 | REQ-DEP-001 |
| F-DET-1 | High | CONFIRMED_CURRENT | RUN | `odooflux.py:831-854` | Whole-document parsing with spans | P4 | REQ-PY-001, REQ-XML-001 |
| F-VER-6 | High | REQUIRES_RUNTIME_VERIFICATION | RUN, EV-120–122 | `odooflux.py:785-793` | Stop header injection; JS rules after research | P0, P5 | REQ-JS-002 |
| F-SEC-1 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:985` | Scan CSV/security data | P5 | REQ-ACL-001 |
| F-AI-6 | High | CONFIRMED_CURRENT | CODE | `odooflux.py:1210, 1454` | Env-only key, configurable model, debug outside module | P0 (debug path), P6 | REQ-AI-008, REQ-SEC-003 |
| F-VER-3 / NF-01…04 / NF-19 | Medium | CONFIRMED_CURRENT / NEW_FINDING | CODE, EV-101/110/112/122 | `odooflux.py:92, 112, 143, 177, 197-210, 255, 263, 327` | Correct or retire; attach evidence to every rule | P1 (pin), P5 | REQ-EVD-001 |
| F-XML-3 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:548-560` | Converter supports `column_invisible` | P4 | REQ-XML-002 |
| F-XML-4 | Medium | CONFIRMED_CURRENT | RUN | `odooflux.py:596-643` | Idempotence tests | P0, P4 | REQ-TRF-003 |
| F-XML-6 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:724-760` | Placement check after research (G-R-09) | P5 | REQ-XML-003 |
| F-XML-7 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:660-686` | Python action-dict rule | P5 | REQ-XML-003 |
| F-XML-8 | Medium | CONFIRMED_CURRENT | RUN, EV-113/117/119/123 | XML rules | Rules after research | P5 | REQ-XML-005, REQ-JS-003 |
| F-PY-6 | Medium | CONFIRMED_CURRENT | RUN | `odooflux.py:532-536` | Remove | P0 | REQ-SAF-010 |
| F-PY-7 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:511` | Token-aware import rewrite | P4 | REQ-PY-001 |
| F-PY-9 / F-VER-2 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:80-85, 509` | Step-scoped rules | P2 | REQ-VER-004 |
| F-VER-4 / F-REP-3 | Medium | CONFIRMED_CURRENT | RUN | `odooflux.py:233-302, 1791-1797` | Drop noise rules; `--fail-on` | P0 (basic), P8 | REQ-REP-005 |
| F-VER-7 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:398-400` | 18→19 rules from EV-102/114/115/116 | P5 | REQ-PY-002 |
| F-MAN-2 | Medium | CONFIRMED_CURRENT | RUN, EV-124 | manifest rules | Asset rules | P5 | REQ-JS-003 |
| F-MAN-4 / F-MAN-5 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:988-1019` | `ast.literal_eval`; path checks | P2, P5 | REQ-MAN-001, REQ-MAN-003 |
| F-SAFE-5 | Medium | CONFIRMED_CURRENT | RUN | `odooflux.py:1045-1058` | Rename, never copy | P0 | REQ-MAN-001 |
| F-VAL-2 | Medium | CONFIRMED_CURRENT | CODE | — | Layers 3–5 | P5, P7 | REQ-VAL-003…005 |
| F-AI-3 | Medium | CONFIRMED_CURRENT | CODE | `odooflux.py:1375` | XML after the deterministic converter | P6 | REQ-AI-002 |
| F-SEC-2 | Medium | CONFIRMED_CURRENT | CODE | — | Security-pattern rules (G-R-11) | P5 | REQ-ACL-001 |
| F-AI-5 | Medium | PREVIOUSLY_REPORTED | HYP | `odooflux.py:1483` | Exact-path keys only | P6 | REQ-AI-003 |
| F-PY-8 | Low | CONFIRMED_CURRENT | CODE | `odooflux.py:530` | Py2 constructs out of scope (≥12.0 is Py3) — retire | P5 | REQ-PY-004 |
| F-DET-2 | Low | CONFIRMED_CURRENT | CODE | `odooflux.py:843` | Finding IDs from rule + span | P2 | REQ-TRF-001 |
| F-AST-1 | Low | CONFIRMED_CURRENT | CODE | `odooflux.py:353-361` | CSS rules after research | P5 | REQ-JS-003 |
| F-REP-2 | Low | CONFIRMED_CURRENT | CODE | `odooflux.py:7-9, 1570-1588` | Width-aware colour; fix help name | P8 | REQ-REP-002 |
| F-WALK-1 | Low | CONFIRMED_CURRENT | CODE | `odooflux.py:960-982` | Proper ignore semantics | P2 | REQ-ARC-005 |

## 7. Gap summary

### Architectural gaps

1. No intermediate representation or edit model: detection and fixing are disconnected
   (ADR-003, REQ-TRF-001).
2. No validation stage between transform and write (REQ-SAF-002).
3. No version graph: the threshold model cannot express multi-step paths or windows (REQ-VER-002).
4. No evidence linkage: rules have no provenance (REQ-EVD-001).
5. No workspace, run log, rollback, or resume (REQ-SAF-006…009).
6. Single-file monolith with module-level state; nothing is extensible without editing it
   (REQ-ARC-002).
7. AI is coupled to one provider and to whole-file rewrites (ADR-012).

### Implementation gaps

1. Unsafe fixers (F-PY-1/2/5/6, F-XML-1/5).
2. Wrong target syntax for `attrs` (F-XML-2).
3. Incorrect version claims (NF-01…04).
4. Missing rules for verified changes (NF-05…17).
5. No dependency, security-data, or asset analysis (F-MAN-3, F-SEC-1, F-MAN-2).
6. No tests (REQ-TST-001).

## 8. Focus areas from the brief

| Focus area | Findings |
|---|---|
| Unsafe regex transformations | F-PY-1, F-PY-2, F-PY-5, F-PY-6, F-PY-7, F-XML-1, F-XML-4, F-XML-5, F-DET-1 |
| Invalid XML output | F-XML-1, F-XML-4 |
| Invalid Python output | F-PY-1, F-PY-2, F-PY-6 |
| Incorrect Odoo version rules | F-VER-1, F-VER-3, F-VER-6, NF-01, NF-02, NF-03, NF-04, NF-17, F-PY-3 |
| Broken XML modifiers | F-XML-2, F-XML-3, F-XML-4 |
| Decorator handling | F-PY-1, F-PY-3, F-PY-4, NF-01 |
| JavaScript / OWL compatibility | F-VER-6, NF-04, NF-16, NF-17, F-AST-1 |
| Incorrect fix counts | F-REP-1, F-AI-4 |
| Missing validation | F-VAL-1, F-VAL-2 |
| Missing dependency checks | F-MAN-3, F-MAN-4 |
| Inaccurate AI issue context | F-AI-1, F-AI-2 |
| Unsafe backup locations | F-SAFE-2, F-SAFE-3 |
| Non-atomic writes | F-SAFE-4 |
| Missing test coverage | No tests in the repository (REQ-TST-001); see [VALIDATION_AND_TEST_STRATEGY.md](VALIDATION_AND_TEST_STRATEGY.md) |
| Incorrect success reporting | F-REP-1, F-AI-4, F-VER-4, NF-05 ("clean" v19 run that drops constraints) |
