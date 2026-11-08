# OdooFlux — Odoo Module Upgrader Audit

| | |
|---|---|
| **Subject** | `odooflux.py` (1,801 lines, single file, stdlib only) at commit `c9914e6` |
| **Date** | 2026-11-06 |
| **Scope** | Architecture, XML/Python/JS transformations, AI fixing, version rules, manifests, security, views, assets, dependencies, validation, testing |
| **Change policy** | Read-only audit. No code was modified. |
| **Governing document** | `.specify/memory/constitution.md` v1.0.0 |

---

## 0. Executive summary

OdooFlux is a regex-driven scanner and fixer that targets Odoo 18/19. As a **scanner** it is
useful: it finds the most common legacy constructs quickly and produces readable console and
JSON reports. As a **fixer** (`--fix`) it is currently **unsafe**. In a reproduction run against a
small, realistic v14 module, the fixer produced a Python file that fails to compile and an XML
view file that is not well-formed. It then reported 22 issues as "fixed".

The upgraded modules fail for five root causes:

1. **No validation gate.** Transformed files are written to disk without parsing them first (§2.6).
2. **Text-level regex edits on structured languages.** Fixes ignore indentation, argument
   position, multi-line constructs and XML tag syntax (§2.1, §2.2).
3. **Wrong target syntax.** `attrs=` is converted into domain lists, but Odoo 17+ expects
   Python expressions (§2.1).
4. **Inaccurate bookkeeping.** Any change to a file marks *every* auto-fixable issue in it as
   fixed, so the report hides what is still broken (§2.7).
5. **Large coverage gaps.** Manifest assets, the legacy `qweb` key, XML asset templates,
   Python `states=`, `name_get`, dependencies, ACL CSVs and most v17–v19 API changes are not
   detected or fixed (§2.4, §2.5).

There are no tests in the repository, so none of these defects would have been caught.

**Recommendation:** disable or gate `--fix` behind validation first (repair plan Phase 0),
then build a fixture-based test suite, and only then expand rule coverage.

---

## Method and evidence levels

1. Full read of `odooflux.py`, top to bottom.
2. Unit probes: individual fixer functions were imported and run against hand-written inputs.
3. End-to-end reproduction: a synthetic v14 module, `kbi_demo` (see Appendix A), was placed in
   a temporary addons directory. The CLI was run in analyze mode, then in `--fix --backup` mode,
   then in analyze mode again. Results were checked with `py_compile` and
   `xml.etree.ElementTree`.

The AI path (`--ai-fix`) was **not** executed, because no API key was used. Findings about it
come from code reading only.

Every finding carries one of these evidence levels:

| Tag | Meaning |
|---|---|
| **CONFIRMED-RUN** | Reproduced by executing the tool or its functions |
| **CONFIRMED-CODE** | Follows unambiguously from the source; not executed |
| **HYPOTHESIS** | Plausible; depends on Odoo runtime behaviour or on inputs not tested. Needs verification |

Statements about Odoo version behaviour come from Odoo framework knowledge, not from running a
target Odoo server. Those marked *(verify on v19)* should be checked against Odoo 19 source
before rules are written for them.

---

## 1. Architecture assessment

### 1.1 Execution flow

```
main()                                           odooflux.py:1645
 ├─ argparse → resolve_modules()                 :1527   (--module / --modules / --addons-path)
 ├─ for each module:
 │    ├─ backup_module()            [if --fix --backup]          :1193
 │    ├─ walk_module()                                           :1022
 │    │    ├─ _check_manifest_version()                          :988
 │    │    ├─ os.walk + SKIP_DIRS + naive .gitignore             :957-983
 │    │    ├─ analyze_and_fix_file()  per file                   :915
 │    │    │    ├─ _rules_for_file() → check_content()  (DETECT) :870, :819
 │    │    │    └─ apply_{manifest,python,xml,js}_fixes() (FIX)  :763, :509, :646, :785
 │    │    │         └─ write_text() if changed  ← no validation :946
 │    │    │         └─ _mark_auto_fixes_applied()               :901
 │    │    └─ __openerp__.py → __manifest__.py copy/rename       :1045-1058
 │    └─ print_report()                                          :1075
 ├─ ai_fix_all_modules()            [if --ai-fix]                :1359
 │    └─ one bundled Claude request → JSON → per-file write (syntax-checked .py only)
 ├─ print_combined_summary / save_*_json_report
 └─ exit 2 (critical) / 1 (warn|info) / 0
```

### 1.2 Components

| Component | Location | Shape |
|---|---|---|
| Data model | `Issue`, `MigrationReport` (:37-73) | Dataclasses; the counters exclude `fix_applied` issues |
| Rule tables | :87-406 | Tuples `(min_src_ver, exact_tgt_ver, regex, severity, category, message, suggestion, auto_fixable)` |
| Detector | `check_content` (:819) | Line-by-line `re.search`; deduplicates on `(line, category)` |
| Fixers | :430-797 | Whole-file `re.sub` chains, one per file type |
| Walker | `walk_module` (:1022) | Manifests first, then other files |
| AI fixer | :1207-1524 | One request, JSON response containing full file contents |
| Reporting | :1075-1190, :1555-1642 | Console and JSON output |

### 1.3 Structural weaknesses

| # | Weakness | Consequence |
|---|---|---|
| A1 | **Detection and fixing are decoupled.** Rules know *what* is wrong. Fixers are separate `re.sub` chains with no link back to a rule or an issue. | Fixes cannot be attributed to issues (→ F-REP-1). A rule can claim `auto_fixable=True` while its fixer does something different, or nothing. |
| A2 | **No intermediate representation.** Everything is regex over raw text. | Multi-line constructs are invisible to detection (→ F-DET-1). Fixes break syntax (→ F-PY-1/2, F-XML-1). |
| A3 | **No validation stage** between transform and write. | Broken files are persisted (→ F-VAL-1). |
| A4 | **Version model is a single threshold.** `min_src_ver` and `exact_tgt_ver` cannot express "deprecated in X, removed in Y". Fixers ignore `from_version` entirely; the parameter is accepted and unused. | The 18→19 `<tree>` gap (→ F-VER-1). Fixes apply whatever the source version. |
| A5 | **Side effects are spread across the walk.** Writes, copies and renames happen inside the analysis loop. | Analyze mode writes files (→ F-SAFE-1). |
| A6 | **The AI step reads files after the regex step has rewritten them**, but uses issue line numbers computed before. | Stale context is sent to the model (→ F-AI-1). |
| A7 | **Global mutable state** in report counters, and module-level compiled rules. | Acceptable for a CLI; harder to test in isolation. |

### 1.4 Strengths worth keeping

- Zero install: stdlib only, single file. This is constitution Principle I.
- Clear severity model, and rule metadata includes suggestions.
- Handles several modules at once, with a combined summary and JSON output.
- Depth-counted `oe_chatter` div replacement (:724) is the right instinct.
- The AI step already validates Python syntax and saves failures as `.ai_draft`.
- The AI system prompt explicitly protects field names, model names and imports.

---

## 2. Root-cause findings

IDs are stable so that the repair plan and tests can reference them.

### 2.1 Regex-based XML transformations

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-XML-1** | The `states=` → `invisible=` fixer inserts an XML comment **inside the start tag** (`<button ... invisible="..."  <!-- TODO ... -->/>`). The file stops being well-formed and the module fails to install. | CONFIRMED-RUN (unit probe and e2e: `ParseError: not well-formed (invalid token): line 10`) | `_convert_states_to_invisible` :596, comment emitted at :632 |
| **F-XML-2** | The `attrs=` fixer outputs **domain lists** (`invisible="[('state','=','done')]"`, `readonly="['\|', (...), (...)]"`). Odoo 17+ evaluates these attributes as **Python expressions** (`state == 'done'`). A non-empty list literal is always truthy, so it is a hypothesis that such fields become unconditionally invisible, readonly or required. The output is wrong either way. | CONFIRMED-RUN (wrong output). Runtime effect: HYPOTHESIS | `_convert_attrs_to_inline` :542-593, output at :586 |
| **F-XML-3** | The `attrs=` parser recognises only `invisible`, `readonly` and `required`. `column_invisible` (list views) and any other keys are silently dropped from the rewritten element. | CONFIRMED-CODE | kv_pattern, ~:559 |
| **F-XML-4** | The fixers are not idempotent. A second `--fix` run appends another TODO comment, and `states=` → `invisible=` can be applied to tags that already have an `invisible=` (duplicate attribute → invalid XML). | CONFIRMED-RUN (comment stacking); duplicate attribute: HYPOTHESIS | :596-643 |
| **F-XML-5** | Chatter fields (`message_ids`, `activity_ids`, `message_follower_ids`, `widget="mail_thread"`) are deleted wherever they appear. `<chatter/>` is only inserted when they sat inside an `oe_chatter` div. In any other container the chatter disappears. | CONFIRMED-RUN (unit probe 10) | :695-718 |
| **F-XML-6** | `<chatter/>` is inserted wherever the old div was. No check that it ends up as a direct child of `<form>` after `<sheet>`. | CONFIRMED-CODE | `_replace_chatter_div` :724 |
| **F-XML-7** | `<tree>` → `<list>`, `view_mode` and `view_type` are rewritten in XML only. `'view_mode': 'tree,form'` in Python action dicts and `ir.actions` returned from methods are neither detected nor fixed. | CONFIRMED-CODE | :660-686 |
| **F-XML-8** | Not handled at all: XML asset templates (`<template inherit_id="web.assets_backend">`, assets moved to manifest in v15), `t-esc`/`t-raw` → `t-out`, `kanban-box` → `kanban-card` (v18), `numbercall` on `ir.cron` (removed v17), `active_id` in view expressions, `<act_window>`/`<report>` shorthand *fixes* (detection only). | CONFIRMED-RUN for the assets template (not reported in e2e); others CONFIRMED-CODE | XML_RULES :213-305 |

### 2.2 Regex-based Python transformations

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-PY-1** | Removing `@api.one` / `@api.returns` keeps the decorator's leading indentation in front of `def`, giving a double indent → `IndentationError`. | CONFIRMED-RUN (e2e `demo.py`) | :513-518 |
| **F-PY-2** | The `size=` removal leaves a dangling comma when `size` is the first argument: `fields.Char(, string='Name')` → `SyntaxError`. When `size=` is on a continuation line it leaves `fields.Char(string='Code',\n )`. That compiles but is untidy. | CONFIRMED-RUN | :531 |
| **F-PY-3** | `@api.returns` is flagged CRITICAL and deleted, but it **still exists** in the ORM (core uses it on `copy`, for example). Deleting it changes the return-value conversion seen by old-API and RPC callers. *(verify on v19)* | CONFIRMED-RUN (removal); impact: HYPOTHESIS | rule :92, fix :518 |
| **F-PY-4** | `@api.one` is removed without adding a `for rec in self:` loop or `ensure_one()`. On multi-record calls the method now silently runs with `self` as a recordset. It is still reported as fixed. | CONFIRMED-RUN | :513-517 |
| **F-PY-5** | `.sudo(\w+)` also matches the boolean flag form: `.sudo(False)` becomes `.with_user(False).sudo()`, which changes the semantics. | CONFIRMED-RUN | :524 |
| **F-PY-6** | A JavaScript comment (`/* TODO ... */`) is injected into Python source when `ajax.jsonRpc(` appears, even inside a string. | CONFIRMED-RUN | :532-536 |
| **F-PY-7** | `openerp.` → `odoo.` is applied to all text, including string literals and XML-ID strings. | CONFIRMED-CODE | :511 |
| **F-PY-8** | `print` conversion handles only single-line string literals. Other Py2 constructs (`except X, e`, `unicode`, `basestring`, `iteritems`) are not detected. | CONFIRMED-CODE | :530 |
| **F-PY-9** | The Python fixer chain runs regardless of `from_version`. The `from_version` argument is unused. | CONFIRMED-CODE | `apply_python_fixes` :509 |

### 2.3 AI-based Python transformations (not executed)

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-AI-1** | The AI receives file content **after** the regex fixes rewrote it, together with issue line numbers computed **before**. Line references are stale whenever regex fixes added or removed lines, and the file may already be syntactically broken (F-PY-1/2). | CONFIRMED-CODE (scan :940-943 → regex write :946 → AI read :1392) | :1392 |
| **F-AI-2** | All files go in one request of up to 180 KB of input (`CLAUDE_MAX_BUNDLE_BYTES`, :1212), but the model must return *complete* files within `max_tokens=16384` (:1211). Large bundles will be truncated. `stop_reason` is never checked, so truncation surfaces as a vague "JSON parse error". | CONFIRMED-CODE; truncation: HYPOTHESIS (likely above roughly 50 KB of output) | :1211-1212, :1290-1323 |
| **F-AI-3** | Only `.py` files are eligible (:1375). XML views, which need non-trivial `attrs` → expression conversion, never benefit from the AI path. | CONFIRMED-CODE | :1375 |
| **F-AI-4** | Every issue in an AI-updated file is marked `fix_applied=True` (:1509) without re-scanning, including issues the model listed as skipped. | CONFIRMED-CODE | :1508-1510 |
| **F-AI-5** | When the AI response is keyed by bare filename, `ai_files.get(fp.name)` (:1483) can apply one file's content to another file with the same name in a different directory. | HYPOTHESIS (depends on model output) | :1483 |
| **F-AI-6** | The model ID is hardcoded (`claude-sonnet-4-6`, :1210). `--api-key` on the command line leaks into shell history and `ps`. `ai_response_debug.txt` is written into the customer's module directory (:1454). | CONFIRMED-CODE | :1210, :1454, :1677-1680 |
| **F-AI-7** | Syntax validation is the only check. There is no check that protected identifiers (field names, `_name`, `_inherit`, imports), which the prompt forbids changing, actually survived. | CONFIRMED-CODE | :1495-1506 |

### 2.4 Odoo version compatibility rules

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-VER-1** | `<tree>` detection fires only when `from_version < 18`. An 18 module that still uses `<tree>` is not flagged when targeting 19, even though 19 removed it. The fixer converts it anyway, so detection and fixing disagree. | CONFIRMED-CODE | rule :264, gate :836 |
| **F-VER-2** | The rule schema cannot express *deprecated-in / removed-in* windows, or rules that apply only to some (from, to) pairs. Version semantics are spread across comments ("FIX: min_src_ver=17 means..."). | CONFIRMED-CODE | :80-85, :836-840 |
| **F-VER-3** | Rules that are factually wrong or misleading: "Lambda defaults on Selection removed in v17" (:177, false); "Editable Form" checks `type="form"` but its message talks about list views (:255); `@api.returns` "removed" (:92); `_inherits` flagged as a WARNING although it is supported (:112); `qweb\.` also matches unrelated identifiers (:143). | CONFIRMED-CODE | as listed |
| **F-VER-4** | Noise rules at INFO severity fire on almost every module: every `<menuitem>` (:233), view `arch` (:250), `<header>` (:302), `monetary` widget (:259), every TransientModel/AbstractModel (:169-175), `noupdate="0"` (:297). Since INFO forces exit code 1, the exit code never reaches 0. | CONFIRMED-RUN (e2e still shows INFO "View Arch"/"Header Buttons" after the fix, exit=2/1) | :1791-1797 |
| **F-VER-5** | Not detected (v16→19), which leaves real migration work invisible: `name_get` → `_compute_display_name` (v17; CONFIRMED-RUN, not reported in e2e), Python field `states=` (removed v17; CONFIRMED-RUN, not reported), `create(self, vals)` without `@api.model_create_multi`, `fields_view_get` → `get_view`, `user_has_groups` → `has_group`, `track_visibility` → `tracking`, `SavepointCase` (removed v16). *Verify on v19:* `_sql_constraints` → `models.Constraint`, `res.users.groups_id` → `group_ids`, `type='json'` → `'jsonrpc'` routes, `read_group` deprecation, `self._cr/_uid/_context` deprecation. | CONFIRMED-RUN / CONFIRMED-CODE as marked; v19 items HYPOTHESIS until verified | PYTHON_RULES :87-211 |
| **F-VER-6** | JS rules: `this.env.services.rpc` is suggested (:342, :790), but the `rpc` service was removed in v18 *(verify)*. Adding `/** @odoo-module */` on top of an unconverted `odoo.define()` file (:787) changes how the asset bundler processes it. HYPOTHESIS: this breaks loading of the file. `require('web.*')` and `Widget.extend` remain CRITICAL after the "fix". | CONFIRMED-RUN (output); load failure: HYPOTHESIS | :785-797 |
| **F-VER-7** | `PYTHON_RULES_V19` and `XML_RULES_V19` are empty "because general rules cover v19". General rules have no v19-specific content, so a v18→v19 run checks almost nothing. | CONFIRMED-CODE | :398-400 |

### 2.5 Manifests, security, views, assets, dependencies

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-MAN-1** | The manifest version is overwritten with `{to}.0.1.0.0`, discarding the module's own `x.y.z` (e.g. `14.0.2.3.1` → `19.0.1.0.0`). That breaks the migration-script version ordering (`migrations/<version>/`) that Odoo relies on. | CONFIRMED-RUN | :763-782 |
| **F-MAN-2** | The legacy manifest key `qweb` (replaced by `assets` bundles in v15) is not detected and not migrated. | CONFIRMED-RUN (not reported in e2e) | MANIFEST_RULES :307-324 |
| **F-MAN-3** | `depends` is never checked. Modules that were removed or renamed in the target version, and missing dependencies for referenced models, are not reported. | CONFIRMED-RUN (bogus dependency not reported) | — |
| **F-MAN-4** | Manifest `data`/`demo`/`assets` paths are never checked against the filesystem, and load order is never checked (security before views). | CONFIRMED-CODE | — |
| **F-MAN-5** | Only Python-literal manifests are handled by regex. There is no `ast.literal_eval` parse, so detection and fixing work on raw text, and the double-quote and single-quote paths are inconsistent (:995 contains a dead `\\s` regex). | CONFIRMED-CODE | :988-1019 |
| **F-SEC-1** | `security/ir.model.access.csv`, `ir.rule` records and `res.groups` are not scanned (`.csv` is not in `SCAN_EXTENSIONS`, :985). Renamed groups and models in the target version go unreported. | CONFIRMED-CODE | :985 |
| **F-SEC-2** | Removed security-relevant constructs (`auth='none'` routes, `csrf=False`, `t-raw`) are not flagged. | CONFIRMED-CODE | — |
| **F-AST-1** | SCSS/CSS is scanned with 2 rules. No checks for the v16+ Bootstrap 5 class renames or for asset bundle names. | CONFIRMED-CODE | :353-361 |

### 2.6 Validation

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-VAL-1** | **No post-transform validation.** The regex fixers write files without `ast.parse` (Python), XML well-formedness checks, or manifest `literal_eval`. This is the direct cause of the broken output in e2e. | CONFIRMED-RUN | :940-949 |
| **F-VAL-2** | No structural validation (XML IDs referenced, fields referenced in views exist on the model, `inherit_id` targets exist), and no optional install test against a real target Odoo. | CONFIRMED-CODE | — |
| **F-DET-1** | Detection is line-based. Multi-line `attrs=`, multi-line field definitions (`size=` on a continuation line), and multi-line class headers are partially or entirely missed. In e2e, `code = fields.Char(string='Code',\n size=16)` was not reported but was modified by the fixer. | CONFIRMED-RUN | :831-854 |
| **F-DET-2** | Deduplication by `(line, category)` reports the same line twice under overlapping categories, for example "Legacy Namespace" and "Legacy openerp Import". | CONFIRMED-CODE | :843 |

### 2.7 Safety, reporting and CLI

| ID | Finding | Evidence | Location |
|---|---|---|---|
| **F-SAFE-1** | **Analyze mode writes to the module**: `__openerp__.py` is copied to `__manifest__.py` without `--fix`, including in `--dry-run`. This violates constitution Principle II. | CONFIRMED-RUN (file appeared after an analyze-only run) | :1045-1049 |
| **F-SAFE-2** | Backups are created as a **sibling directory** (`<module>_backup_<ts>`), which lands inside the addons path. Odoo treats it as another installable module with the same models. The next `--addons-path` run scans it as a second module. | CONFIRMED-RUN (rescan listed `[2/2] kbi_demo_backup_…`) | :1195 |
| **F-SAFE-3** | If the backup fails, the tool prints a warning and continues writing. | CONFIRMED-CODE | :1199-1202 |
| **F-SAFE-4** | Writes are not atomic (`write_text` in place). An interrupted run leaves a module partly migrated, with no record of which files changed. | CONFIRMED-CODE | :946 |
| **F-SAFE-5** | After renaming via copy, `__openerp__.py` is kept when `__manifest__.py` already exists, so two manifests coexist. Both are rewritten by the manifest fixer. | CONFIRMED-RUN | :1045-1058 |
| **F-REP-1** | `_mark_auto_fixes_applied` marks **every** auto-fixable issue in a changed file as fixed. e2e reported `fixed=22` while two files were broken and `@api.one` semantics were lost. | CONFIRMED-RUN | :901-912 |
| **F-REP-2** | ANSI colour codes are counted in the `:>6` column widths, so the combined summary is misaligned when colour is on. The help text refers to `odoo_migrate_to_19.py`. | CONFIRMED-CODE | :1570-1588, :7-9 |
| **F-REP-3** | Exit codes overlap with argparse's own exit code 2. There is no `--fail-on` threshold. | CONFIRMED-CODE | :1791-1797 |
| **F-WALK-1** | The `.gitignore` translation is a naive unanchored substring regex. It does not support `!` negation, leading `/` anchors, or trailing `/` directory patterns. | CONFIRMED-CODE | :960-982 |

### 2.8 Why upgraded modules fail — synthesis

Ordered by likely frequency on real customer modules:

1. **The module does not load:** Python `SyntaxError`/`IndentationError` from F-PY-1/F-PY-2. The
   module cannot be imported at all.
2. **View files are rejected at install:** malformed XML from F-XML-1, duplicate attributes from
   F-XML-4.
3. **Views install but behave wrongly:** `attrs` converted to domain lists (F-XML-2), dropped
   `column_invisible` (F-XML-3), lost chatter (F-XML-5).
4. **Unmigrated APIs fail at runtime:** `name_get`, Python `states=`, `qweb` assets, legacy JS
   (F-VER-5, F-MAN-2, F-VER-6). None of these are reported, so the module looks "clean".
5. **Semantic changes with no error:** `@api.one` removal, `.sudo(False)`, `@api.returns`
   removal (F-PY-3/4/5).
6. **Environment pollution:** backup directories registered as duplicate addons (F-SAFE-2).
7. **False confidence:** the report claims fixes that did not happen (F-REP-1, F-AI-4), so
   problems are only found at install time.

---

## 3. Missing test coverage

The repository has **no tests**: no `tests/` directory, no fixtures, no CI. Constitution
Principle V requires a test with before/after samples for every rule and fixer. The minimum
suite, using `unittest` from the standard library (Principle I):

### 3.1 Unit tests per fixer (before/after/negative/idempotence)

| Area | Cases (each with a "must not change" counterpart) |
|---|---|
| `_convert_attrs_to_inline` | simple `=`, `!=`, `in`, `not in`; `\|` and `&` prefix operators; nested brackets; multi-line value; `column_invisible`; already-inline input (no-op); unconvertible input (left unchanged and still reported) |
| `_convert_states_to_invisible` | button, field, page; existing `invisible=` present; output is well-formed XML; second run is a no-op |
| `<tree>`/`view_mode` | XML arch, `view_mode` field, `view_type`, Python action dict, string literal "tree" elsewhere (unchanged) |
| Chatter | `oe_chatter` div with nested divs; standalone chatter fields; `mail_thread` widget; result has exactly one `<chatter/>` directly under `<form>` |
| Python decorators | `@api.multi`, `@api.one`, `@api.returns` at class indentation; comments between decorator and `def`; output passes `ast.parse` |
| `fields.Char(size=)` | first, middle and last argument; continuation line; `size` used as a variable name elsewhere |
| `sudo` | `.sudo(user)`, `.sudo(False)`, `.sudo(True)`, `.sudo()` |
| `Warning` → `UserError` | import variants, aliased import, `openerp.exceptions`, missing import injection |
| Imports | each entry in `_IMPORT_MODULE_MAP`; relative imports untouched |
| Manifest | single and double quotes; version suffix preserved; `__openerp__` rename only under `--fix` |
| JS | `odoo.define` file is not given an `@odoo-module` header unless converted |

### 3.2 Detector tests

- Every rule: one positive and one negative sample, and the correct version gating for each
  `(from, to)` pair (especially F-VER-1).
- Multi-line constructs are detected (F-DET-1).
- No duplicate issue for one construct (F-DET-2).

### 3.3 Integration / golden tests

- **Golden modules:** small fixture modules per source version (12, 14, 16, 17, 18), each with
  an expected migrated tree and an expected JSON report. Assert byte-equal output, then assert
  that `ast.parse` succeeds on every `.py` file and an XML parse succeeds on every `.xml` file.
- **Safety:** analyze and `--dry-run` leave the module tree byte-identical (hash before and
  after). Backups are not created inside the scanned addons path. A failed backup aborts.
- **Idempotence:** `--fix` run twice gives the same tree as running it once.
- **Report accuracy:** after `--fix`, re-scanning produces exactly the issues reported as open.
- **CLI:** exit codes, `--skip`, `--filter-severity`, combined JSON shape.
- **AI path (offline):** stub `_call_claude_api`. Cover a truncated response, a response with
  wrong keys, a syntax error saved as a draft, a protected identifier changed (rejected), and
  stale line numbers.

### 3.4 Optional acceptance tier (CI only)

- Install each migrated golden module in a containerised Odoo 18 and 19
  (`odoo-bin -i <module> --stop-after-init`). This is the only test that proves an upgraded
  module actually installs. Keep it outside the default test run so the tool stays
  dependency-free.

---

## 4. Prioritized repair plan

Each phase is shippable on its own. Do not start a phase before the previous phase's tests
pass.

### Phase 0 — Stop the damage (highest priority, small)

| Step | Fixes | Notes |
|---|---|---|
| 0.1 | Validation gate before any write: `ast.parse` for `.py`, XML well-formedness for `.xml`, `ast.literal_eval` for manifests. On failure, do not write; record a CRITICAL "Fix rejected" issue with the parser error. | F-VAL-1. Stops failure modes 1–2 in §2.8. |
| 0.2 | No side effects outside `--fix`: move the `__openerp__` copy under `do_fix` and make it a rename. | F-SAFE-1, F-SAFE-5 |
| 0.3 | Backups go outside the addons path (e.g. `<cwd>/.odooflux_backups/<module>_<ts>` or a zip). Abort the module if the backup fails. | F-SAFE-2, F-SAFE-3 |
| 0.4 | Remove the in-tag XML comment from the `states=` fixer. Skip conversion when `invisible=` already exists and report it instead. | F-XML-1, F-XML-4 |
| 0.5 | Remove the `@api.returns` deletion and the `.sudo(bool)` rewrite. Change `@api.one` to "detect, do not auto-fix" (set `auto_fixable=False`). | F-PY-3, F-PY-4, F-PY-5 |
| 0.6 | Fix decorator removal so it removes whole lines, and fix `size=` removal so it is comma-aware. Both are covered by the 0.1 gate. | F-PY-1, F-PY-2 |
| 0.7 | Remove the JS comment injection from the Python fixer. | F-PY-6 |
| 0.8 | Until a correct converter exists, make the `attrs=` fixer either produce correct Python expressions or **leave `attrs` untouched and report it**. | F-XML-2, F-XML-3 |

### Phase 1 — Trustworthy reporting and tests

| Step | Fixes |
|---|---|
| 1.1 | Create the `tests/` suite from §3.1–3.3, with the Appendix A fixture as the first golden module. |
| 1.2 | Accurate fix attribution: after fixing, **re-scan** the fixed content. Issues absent from the re-scan are fixed; the rest stay open. This is the simplest correct approach (F-REP-1, F-AI-4). |
| 1.3 | Make every fixer idempotent (tested). |
| 1.4 | Preserve the module version suffix: `14.0.2.3.1` → `19.0.2.3.1`, or make the reset explicit with a flag (F-MAN-1). |
| 1.5 | Remove or correct wrong rules (F-VER-3). Move noise rules to an opt-in `--verbose-rules` or drop them (F-VER-4). Add `--fail-on {critical,warning,info}` (F-REP-3). |
| 1.6 | Atomic writes (temp file + `os.replace`) and a run manifest listing changed files (F-SAFE-4). |

### Phase 2 — Correct, complete transformations

| Step | Fixes |
|---|---|
| 2.1 | A real `attrs`/domain → Python-expression converter: parse the domain with `ast.literal_eval`, translate prefix `\|`/`&`/`!` notation into `or`/`and`/`not`, support `column_invisible`, and mark unconvertible cases for manual review (F-XML-2/3). |
| 2.2 | Switch detection from line-based to whole-content matching with offset → line mapping, so multi-line constructs are seen (F-DET-1). |
| 2.3 | Version model: per-rule `deprecated_in`/`removed_in`, gated on the (from, to] interval. Close the 18→19 gaps (F-VER-1/2/7). |
| 2.4 | Add the missing detections in priority order: Python `states=`, `name_get`, `create(vals)`, manifest `qweb`, XML asset templates, `t-esc/t-raw`, `kanban-box`, cron `numbercall`, then the v19 items once verified (F-VER-5, F-MAN-2, F-XML-8). |
| 2.5 | Manifest checks: parse with `ast.literal_eval`; check that `data`/`assets` files exist and load order is right (F-MAN-4/5). |
| 2.6 | Security scanning: include `.csv`; check ACL model and group references; flag `auth='none'`, `csrf=False`, `t-raw` (F-SEC-1/2). |
| 2.7 | Dependency check against a per-version list of known core modules (F-MAN-3). |

### Phase 3 — AI path hardening

| Step | Fixes |
|---|---|
| 3.1 | Send the original content with fresh line numbers (scan the content you send), one request per file or per size-bounded batch, and check `stop_reason` (F-AI-1/2). |
| 3.2 | Verify after the AI step: syntax, protected-identifier diff (field names, `_name`, `_inherit`, imports), then re-scan. Reject on violation (F-AI-7). |
| 3.3 | Read the API key from the environment only, make the model configurable, write debug output outside the module, and use exact-path key matching (F-AI-5/6). |
| 3.4 | Optional: XML views for AI only *after* the deterministic converter, and only for cases it marked unconvertible (Principle III). |

### Phase 4 — Architecture evolution (§5)

Do this only after Phases 0–2. Moving to a package or adding dependencies requires a
constitution amendment first.

---

## 5. Future multi-version architecture proposal

### 5.1 Goals

- One engine that migrates any supported source to any later target (12…19) through explicit
  **version steps**, so that knowledge for 17→18 is written once and reused for 14→19.
- Every change is **attributable** (rule → issue → edit), **validated** before it is written,
  **idempotent**, and **reviewable** as a diff.
- Keep the zero-install promise (constitution Principle I) for the core engine.

### 5.2 Pipeline

```
discover ─► parse ─► detect ─► plan edits ─► validate ─► apply ─► verify ─► report
   │          │         │           │             │           │          │
 modules,   per-file   rules emit   fixers emit   syntax +    atomic     re-scan;
 manifests  views:     Findings     Edit(span,    structural  write +    optional
 (ast)      ast/XML    w/ spans     replacement,  checks on   run log    Odoo install
                                    rule_id)      the result             test (CI)
```

Each stage is a pure function over in-memory data. Only `apply` touches the disk. That makes
analyze and dry-run safe by construction, and gives `--diff` output for free (render the
planned edits).

### 5.3 Core abstractions

| Concept | Responsibility |
|---|---|
| `VersionStep(from, to)` | A named step such as 16→17. It owns the rules whose change happened in that release. |
| `Rule` | `id`, `step`, `file_kinds`, `severity`, `introduced_in`/`deprecated_in`/`removed_in`, `detect(doc) → [Finding]`, optional `fix(doc, finding) → [Edit]`, docs link |
| `Finding` | Rule ID, file, byte span → line/col, message |
| `Edit` | `(file, start, end, replacement, rule_id)`. Overlapping edits are detected and rejected. |
| `Document` | Raw text plus a lazily parsed view (Python `ast` with offsets; XML via an offset-tracking parser). Text is edited by span, so untouched formatting is preserved. |
| `Validator` | Python compiles; XML well-formed; manifest `literal_eval`; manifest file references exist; optional Odoo install test |
| `KnowledgeBase` | Per-version data: removed or renamed core modules, models, fields, groups, asset bundles, JS module paths. Data files, not code, so updating them is a data change. |

**Migration path:** for `--from 14 --to 19`, run steps 14→15, 15→16, …, 18→19 in sequence.
Each step works on the output of the previous one and validates it. A failing step stops the
module and reports which step failed. This replaces the `min_src_ver`/`exact_tgt_ver` tuple
(F-VER-2).

### 5.4 Parsing strategy (dependency trade-off)

| Option | Pros | Cons |
|---|---|---|
| **A. stdlib span editing (recommended first)**: `ast`/`tokenize` and an XML scanner locate exact spans; edits are spliced into the original text. Parsers are used to *find* and *validate*, never to re-serialise. | No dependencies (Principle I holds); formatting preserved; testable | More code for the XML span locator |
| B. `lxml` for XML | Robust XPath, line numbers | Re-serialising changes formatting/quoting; adds a dependency → constitution amendment |
| C. `libcst` for Python | Format-preserving, full CST transforms | Third-party dependency → amendment |

Start with A. Adopt B or C only if a concrete rule cannot be implemented correctly with A, and
record that decision as a constitution amendment (MINOR or MAJOR bump to Principle I).

### 5.5 Packaging

A single file stops scaling at roughly this size. Recommended shape, still runnable without
installing anything (`python -m odooflux`, or a zipapp built from the package):

```
odooflux/
├── __main__.py          CLI
├── engine/              pipeline, Document, Edit, Validator
├── rules/
│   ├── v13_v14.py … v18_v19.py   one module per VersionStep
│   └── common.py
├── kb/                  per-version knowledge data (JSON)
├── ai/                  optional AI fixer (emits Edits, same validation gate)
└── report/              console, JSON, SARIF, diff
tests/
├── fixtures/<version>/<module>/        input + expected/
└── test_*.py
```

Constitution Principle I currently mandates a single file. This layout therefore **requires an
amendment** (proposed: "single entry point, stdlib only, distributable as one zipapp").

### 5.6 AI as a plugin, not a pass

The AI fixer becomes one more fixer that returns `Edit`s for findings no deterministic rule
can fix. It goes through the same validator, the same protected-identifier check, and the same
re-scan. It is never trusted on its own, which is what constitution Principle III already
requires.

### 5.7 Outputs

Console, JSON (current schema, versioned), **SARIF** for code-scanning UIs, **unified diff**
for review, and `--fail-on` exit policy for CI.

---

## Appendix A — Reproduction fixture (`kbi_demo`, v14)

Files used in the end-to-end run (all of it is available to turn into the first golden test):

- `__openerp__.py`: `version '14.0.2.3.1'`, `depends` including a non-existent module,
  legacy `qweb` key.
- `models/demo.py`: `from odoo.exceptions import Warning`, `fields.Char(size=64, ...)`
  (first argument), `size=` on a continuation line, Python `states={...}`, `@api.one`,
  `@api.returns`, `@api.multi` + `name_get`, `.sudo(False)`, `raise Warning(...)`.
- `views/demo_views.xml`: `<openerp>` root, `states=` on a button, multi-line `attrs=` with
  `invisible`/`required`, `attrs` with a `|` domain, `oe_chatter` div, `<tree>`,
  `view_mode tree,form`, XML asset template on `web.assets_backend`.
- `static/src/js/demo.js`: `odoo.define`, `require('web.Widget')`, `ajax.jsonRpc`.
- `security/ir.model.access.csv`: one ACL row.

Observed results:

| Step | Result |
|---|---|
| Analyze only | exit 2; 25 issues; **`__manifest__.py` created** (F-SAFE-1) |
| Not reported | `name_get`, Python `states=`, multi-line `size=`, `qweb` key, asset template, bogus dependency |
| `--addons-path --fix --backup` | report: `fixed=22`, `open=5`; backup created **inside addons path** |
| `py_compile models/demo.py` | **SyntaxError** `fields.Char(, string='Name')`; doubled-indent `def` lines follow |
| XML parse `views/demo_views.xml` | **ParseError** line 10 (comment inside `<button>` tag) |
| `attrs` output | `invisible="[('state', '=', 'done')]"`, `readonly="['\|', ...]"` (domain lists) |
| Re-analyze addons path | 2 modules scanned: `kbi_demo` and `kbi_demo_backup_<ts>` |
