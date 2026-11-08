# Research: Version Compatibility Rules (Feature 006 / Phase P5)

## R-1 Scope of the first rule release (D-04)
- **Decision (default, pending D-04):** Steps 14-15 … 18-19 must reach `RESEARCHED` with tested
  rules for P5 exit. Steps 12-13 and 13-14 get research tasks and seed rules. They may stay
  `RESEARCH_SEEDED`, in which case the planner reports paths through them as `BLOCKED`
  (REQ-VER-003).
- **Order** (roadmap): 17-18, 18-19, 16-17, 15-16, 14-15, 13-14, 12-13.

## R-2 Research precedes rules
- Each gap blocking a rule (G-R-…) has a research task that must complete before that rule's
  implementation task. Research output is evidence records (feature 004 format) or a recorded
  negative result (`NOT_APPLICABLE`/`CONFLICTING`).
- Categories without any evidence after research stay detect-free: no rule is written from
  memory (Principle VI).

## R-3 Rule code organisation
- **Decision:** Reusable parameterised detectors/fixers per language:
  - Python: rename keyword, remove keyword, remove decorator, rename attribute access, flag call,
    flag override, flag class attribute.
  - XML: rename tag, remove attribute, convert modifiers, flag element, rewrite `view_mode`.
  - QWeb: rename directive, flag directive.
  - JS: flag import/call (adapter or lexer).
  - Manifest: flag key, move key.

  Rules are mostly metadata bindings of these. Bespoke code only where needed (e.g.
  `_sql_constraints` analysis).
- **Rationale:** Fewer code paths to test; each parameterised fixer has its own idempotence
  tests, and each rule adds positive/negative fixtures.

## R-4 Golden migrations
- **Decision:** For each source version fixture from feature 002
  (`tests/golden_fixtures/<src>/<module>/`), add `expected/<target>/` trees for each supported
  target, plus `expected/<target>/report.json` (normalised: no timestamps or durations). The
  golden test runs the full pipeline in write mode into a temp state dir and compares.

## R-5 Core module lists per version (REQ-DEP-001)
- **Decision:** Extract from the pinned official tree the set of directories under `addons/` and
  `odoo/addons/` that contain `__manifest__.py`. This is official source at a pinned SHA, so it
  is evidence. Store it as `knowledge/compatibility/core_modules/<ver>.json` with the SHA and an
  evidence record per version (EV-3xx, created by the task). Enterprise modules are unknown
  (D-05), so dependencies not found in core or in the scanned custom modules are reported as
  `unknown-dependency` with WARNING, not CRITICAL.

## R-6 Cross-module references (REQ-DEP-003)
- **Decision:** Build an index from the scanned modules and the target core-module manifests'
  declared data (XML IDs from `data` files are **not** extracted from core in P5; this is
  limited to custom modules). References to `module.xml_id`, where the module is a scanned
  custom module, are resolved. References to core XML IDs are reported as "unverified (core)"
  until P7 runtime validation. Model/field references in views are checked against fields
  declared by scanned modules plus `_inherit` chains within scanned modules. Unknown → INFO
  with `NEEDS_REVIEW`.

## R-7 Business-logic inventory (REQ-BIZ-001)
Risk classes and detection (Python `ast`):

| Class | Detection |
|---|---|
| `orm-override` | Methods named `create`, `write`, `unlink`, `copy`, `read`, `search`, `_search`, `name_get`, `_compute_display_name`, `default_get`, `fields_get`, `_read_group`, `read_group`, `get_view`, `fields_view_get` on classes with `_inherit`/`_name` |
| `computed-field` | `fields.*(compute=...)` + `@api.depends` methods |
| `onchange` | `@api.onchange` |
| `constraint` | `@api.constrains`, `_sql_constraints`, `Constraint` attributes |
| `multi-company` | `company_id` fields, `check_company`, `_check_company_auto`, `with_company` |
| `transaction` | `cr.commit`, `cr.rollback`, `savepoint`, raw `cr.execute` |
| `cron` | `ir.cron` records in XML, `_cron_*` methods |
| `controller` | `http.route` decorators |
| `security-sensitive` | `sudo()`, `with_user`, `auth='none'`/`'public'`, `csrf=False` |
| `integration` | `requests`, `urllib`, `xmlrpc`, `smtplib` imports |

The inventory is reported per module; it never changes code.

## R-8 ACL and security data (REQ-ACL-001)
- `ir.model.access.csv` columns are parsed with `csv`; `ir.rule` and `res.groups` records with
  the XML locator. Rules use evidence for renamed fields such as `groups_id` → `group_ids`
  (EV-114) inside `domain_force`, `eval`, and CSV `group_id:id` (the column itself is not a field
  rename; detection is limited to field-name usage in domains/evals). Other changes are gated on
  G-R-10.

## R-9 Assets and QWeb (REQ-JS-003, REQ-XML-005)
- Evidence: EV-123/124 (manifest `assets` read in 15.0, `qweb` key read in 14.0), EV-201…203
  (`t-out`, `t-esc`/`t-raw` deprecated). Bundle-name mapping for XML asset templates →
  manifest `assets` requires G-R-05 research before any fixer.

## R-10 `_context` replacement verification
- EV-209 covers `_cr` and `_uid`. Before enabling `18-19.python.env-shortcuts-deprecated` for
  `_context`, locate the `_context` deprecation and its replacement at the 19.0 SHA (task T0xx).

## Gaps consumed by this feature

G-R-01, G-R-03, G-R-04, G-R-05, G-R-06, G-R-07, G-R-08, G-R-09, G-R-10, G-R-11, G-R-14, G-R-15,
G-R-16, G-R-17, G-R-18, G-R-20. Out of scope: G-R-02 (Enterprise; D-05), G-R-12 (data
migration; non-goal), G-R-13 (P7), G-R-19 (Odoo 20).
