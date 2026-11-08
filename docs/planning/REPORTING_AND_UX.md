# Reporting and UX

Design for terminal, HTML, JSON, SARIF, and diff outputs (OBJ-006). Delivered in P8:
[specs/009-reporting-ux](../../specs/009-reporting-ux/), [handoff](phase-handoffs/PHASE_08_REPORTING.md).
Report model: [report-schema-v1.md](../../specs/009-reporting-ux/contracts/report-schema-v1.md),
which refines [CONTRACTS.md § ReportModel](architecture/CONTRACTS.md#reportmodel). Legacy defects
addressed: F-REP-1 (false fix counts), F-REP-2 (ANSI misalignment), F-REP-3 (exit codes), and
F-VER-4 (INFO noise).

## 1. Principles

1. **One model, many renderers.** Renderers never compute results (REQ-REP-001).
2. **Honesty first.** Status, reasons, and verification scope are always visible. Counts come
   from the re-scan.
3. **Actionable.** Every open finding shows a suggested action and an evidence link; every
   failure shows recovery steps.
4. **Accessible.** Works without colour (`--no-color`, `NO_COLOR`). Symbols are always paired
   with words. Severity is never encoded by colour alone.

## 2. Report schema (presentation-independent)

Summary of v1 (normative text in the contract):
- `Run`: IDs, timings, request, plan (steps and research status), summary counts, `modules[]`,
  `ai_usage`, `verification_scope`, `recovery`, `warnings[]`.
- `ModuleResult`: status, `status_reasons[]`, files, findings (with evidence `{id, url}`), edits
  (with rejection reasons), per-layer `validation[]`, `runtime`, `behavior`.
- Deterministic ordering. `schema_version` increments on breaking changes.

## 3. Terminal design

- **Stages.** `Discover → Plan → Workspace → Step N/M (s→t) → Validate L1–L5 → Promote → Report`.
- **Default verbosity.** Per-module one-line status. Expand findings for non-success modules;
  successful modules collapse to one line. `-v` expands all; `--max-findings-per-file N` caps
  lists (totals stay exact).
- **Renderers.** The stdlib ANSI renderer is the default. An optional `rich` adapter (D-07) is
  used only with `--ui rich` when `rich` is importable.
- **Width.** Alignment is computed on visible text (ANSI stripped) — the fix for F-REP-2. Snapshot
  tests run at 60, 80, and 120 columns.

### Mockup — progress

```text
OdooFlux 2.0  run 2026-11-06T14-02-11Z-7f3a   source 16.0 → target 18.0   mode: dry-run
Plan  16.0 → 17.0 → 18.0   steps: 2   research: 16-17 RULES_TESTED · 17-18 RULES_TESTED
[1/3] kbi_sale_approval   Step 1/2 16→17  parse ✓  detect 14  fix 11  validate L1 ✓ L2 ✓
                          Step 2/2 17→18  parse ✓  detect 6   fix 6   validate L1 ✓ L2 ✓
                          L3 deps ✓   L4 runtime – not requested   L5 – not requested
[2/3] kbi_hr_extension    Step 1/2 …
```

### Mockup — per-module summary

```text
MODULE RESULTS
 Status             Module               Open C/W/I   Fixed   Rejected   Layers
 STATIC_VALIDATED   kbi_sale_approval    0/0/2        17      0          L1 L2 L3 ✓  L4 –  L5 –
 NEEDS_REVIEW       kbi_hr_extension     0/1/0        9       1          L1 L2 L3 ✓  L4 –  L5 –
 FAILED             kbi_stock_custom     2/0/0        4       2          L1 ✓ L2 ✗ L3 ✓
 BLOCKED            kbi_old_portal       –            –       –          plan refused: step 12-13 NOT_ASSESSED

Why not verified: installation (L4) and behaviour (L5) were not run. Use --validate runtime,behavior.
```

### Mockup — file detail with evidence

```text
kbi_hr_extension/views/hr_views.xml
  WARNING  L42:13  16-17.xml.attrs-removed   [NEEDS_REVIEW]
           attrs domain uses a non-convertible expression; left unchanged.
           Action: rewrite as invisible="…" Python expression.
           Evidence: EV-109  https://github.com/odoo/odoo/blob/9ef8d62…/odoo/addons/base/models/ir_ui_view.py#L394
  FIXED    L57:9   17-18.xml.tree-to-list    <tree> → <list>   (edit e-0031)
```

### Mockup — rejected edits

```text
REJECTED EDITS (2)
  e-0044  kbi_stock_custom/models/stock.py:118-121  rule 12-13.py.api-one-removed
          reason: validation_failed:L1-python  (IndentationError line 119)  — file left unchanged
  e-0051  kbi_stock_custom/models/stock.py:203      rule ai:anthropic/<configured-model>
          reason: protected_identifier_changed (field 'qty_done' renamed)
```

### Mockup — verification scope and AI usage

```text
VERIFICATION SCOPE
  Ran: L1 syntax, L2 static re-scan, L3 dependency integrity
  Not run: L4 runtime (not requested), L5 behaviour (not requested)
  Unavailable: RNG view schema check (lxml not installed)
  Limits: business behaviour not covered by tests is unverified; no customer data was migrated.

AI USAGE  (enabled, consent given)
  provider/model                 requests  in tok   out tok  cached  cost
  anthropic/<configured-model>          7   12 410     2 980   8 200  not configured
  budget events: job budget 50 000 tok — 15 390 used
```

(Numbers in mockups are illustrative only.)

### Mockup — recovery

```text
RECOVERY
  Run log:   ~/.cache/odooflux/runs/2026-11-06T14-02-11Z-7f3a/log/run.jsonl
  Backup:    ~/.cache/odooflux/runs/2026-11-06T14-02-11Z-7f3a/backup/
  Roll back: odooflux rollback 2026-11-06T14-02-11Z-7f3a
  Resume:    odooflux resume 2026-11-06T14-02-11Z-7f3a
```

## 4. HTML design (D-06)

A single static file: stdlib `string.Template`, inline CSS, no JavaScript, no external fonts or
images. Collapsing uses native `<details>`. All untrusted text is HTML-escaped. Evidence links are
plain anchors to allow-listed official URLs.

### Page outline

```text
<header>   Run ID · tool version · source→target · mode · started/finished · overall counts
<nav>      Summary | Plan | Modules | Rejected edits | Verification scope | AI usage | Recovery
<section id="summary">   status tiles (counts per status), findings by severity and status
<section id="plan">      step chain with research status per step; blocked steps
<section id="modules">   one <details> per module: status + reasons, layer table,
                          files → findings (severity, location, rule, message, action, evidence),
                          edits (applied/rejected), runtime errors (class, excerpt), behaviour table
<section id="rejected">  all rejected edits with reasons
<section id="scope">     layers run/unavailable/skipped; limits statements
<section id="ai">        usage table, budget events, consent flag
<section id="recovery">  run log, backup, rollback/resume commands
<footer>   schema_version, generation time, link to JSON report file name
```

## 5. Machine-readable exports

| Format | Purpose | Contract |
|---|---|---|
| JSON v1 | Canonical, schema-validated (`report.schema.json`) | [report-schema-v1.md](../../specs/009-reporting-ux/contracts/report-schema-v1.md) |
| Legacy JSON | Compatibility for one minor release (D-10) | Fields of the current `save_json_report` |
| SARIF 2.1.0 | Code-scanning UIs | [sarif-and-diff.md](../../specs/009-reporting-ux/contracts/sarif-and-diff.md) |
| Unified diff | Review and `patch -p1` | same |

## 6. CI/CD integration

- Run with `--dry-run --report report.json --sarif report.sarif --diff changes.patch --fail-on warning`.
- Upload SARIF to the code-scanning UI. Publish the HTML and patch as artefacts.
- Exit codes:

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Threshold exceeded (open finding ≥ `--fail-on`, or module status in `--fail-on-status`; default `FAILED`) |
| 2 | Usage or configuration error |
| 3 | Rejected edits in write mode |
| 4 | `BLOCKED` module or internal tool error |

Precedence: 4 > 3 > 1 > 0. The default is `--fail-on critical`. INFO findings never fail a build
unless `--fail-on info`. This replaces the legacy mapping (2 = critical, 1 = warning or info,
F-REP-3/F-VER-4) after the D-10 window.

## 7. Evaluated options

| Option | Decision | Reason |
|---|---|---|
| Rich terminal UI (`rich`) | Optional adapter (D-07) | Nicer tables and progress, but Principle I forbids a core dependency |
| Full TUI (curses) | Rejected | Poor in CI; adds complexity |
| HTML via Jinja2 / SPA | Rejected (D-06) | Dependency; scripts and network; larger attack surface |
| Static HTML via stdlib | Chosen (D-06) | Offline, portable, safe |
| JSON Schema publication | Chosen | Lets consumers validate; stdlib subset validator used in tests |
| SARIF 2.1.0 | Chosen | Widely supported for code scanning |
| JUnit XML | Deferred | Can be derived later from the model; no current requirement |
