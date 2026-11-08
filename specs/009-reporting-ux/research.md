# Research: Reporting and UX (P8)

No Odoo-specific compatibility claims are made. Evidence URLs shown in reports come from the knowledge base (P3).

| Decision | Rationale | Alternatives |
|---|---|---|
| Static HTML via `string.Template`, inline CSS, `<details>` for collapsing (D-06) | Offline, stdlib-only, safe to email or archive | Jinja2 (dependency); SPA with JS (needs network or bundling, larger attack surface) |
| ANSI renderer default; optional `rich` adapter (D-07) | Principle I; `rich` gives better tables when installed | `rich` mandatory (core dependency); curses TUI (overkill, non-CI friendly) |
| SARIF 2.1.0 | Widely accepted by code-scanning platforms | Custom JSON only (no CI UI integration) |
| JSON Schema draft 2020-12 published with a stdlib subset validator in tests | Consumers can validate with any tool; no runtime dependency | No schema (legacy) |
| New exit-code table with legacy mapping for one release (D-10) | Legacy codes collided with argparse code 2 and made INFO fail builds (F-REP-3, F-VER-4) | Keep legacy codes (perpetuates defects) |
| Snapshot tests for terminal output at widths 60/80/120, colour and plain | Detects regressions in alignment (F-REP-2) | Manual review |

Legacy findings addressed: F-REP-1 (fix-count honesty, via the report model from P2), F-REP-2 (ANSI width misalignment), F-REP-3 (exit codes), F-VER-4 (INFO noise forcing exit 1).
