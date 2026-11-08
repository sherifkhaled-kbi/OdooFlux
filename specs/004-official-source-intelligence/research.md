# Research: Official Source Intelligence (Feature 004 / Phase P3)

## Decisions

### R-1 Storage format: JSON files with a stdlib schema checker
- **Decision:** Evidence, version registry, revision catalogue, rule metadata, research records,
  and gaps are JSON files under `src/odooflux/knowledge/`, validated by a small schema checker
  written with the standard library (ADR-009).
- **Rationale:** Principle I (stdlib core). JSON diffs review well and need no parser dependency.
- **Alternatives:** YAML (needs PyYAML; rejected). SQLite (opaque diffs, merge conflicts;
  rejected). The `jsonschema` package (third-party; rejected for core, but the schema documents
  in `knowledge/schemas/` follow JSON Schema draft 2020-12 vocabulary so an external validator
  can be used in CI).

### R-2 One file per record type and step
- **Decision:** `evidence/EV-NNN.json` (one record per file), `compatibility/versions.json`,
  `compatibility/<step>.rules.json`, `compatibility/<step>.research.json`,
  `official_sources/allow_list.json`, `official_sources/revisions.json`, `gaps.json`.
- **Rationale:** One record per file minimises merge conflicts between parallel research agents.

### R-3 Evidence revision must be immutable
- **Decision:** `revision` must match `^[0-9a-f]{40}$` or a tag listed in `revisions.json`.
  Branch names alone are rejected (REQ-EVD-004, Principle VI).

### R-4 Location verification is offline and reproducible
- **Decision:** The refresh tool verifies a record by reading the file at the pinned SHA from a
  local clone (`git show <sha>:<path>`) and checking that the record's `match` text occurs at or
  near `line` (±50 lines → "moved"; absent → "missing"). Network access is needed only to
  fetch clones, done by a documented command, not by the core tool.
- **Alternatives:** GitHub API per record (rate limits, network-dependent tests; rejected).

### R-5 Matrix is generated
- **Decision:** `docs/planning/VERSION_COMPATIBILITY_MATRIX.md` becomes the output of
  `odooflux knowledge matrix`, built deterministically from registry, research, and rule data
  (REQ-EVD-006). A test regenerates it and fails on a diff.

### R-6 Online releases map to the next major
- **Decision:** Per ADR-007; the version record lists `online_releases`; evidence citing the
  changelog for `18.1` sets `target_applicability` starting at `19.0`.

## Additional seed evidence (verified during this feature's planning)

Same method and status as the planning register: `DOCUMENTED_NOT_TESTED`. SHAs are listed in
[../../docs/planning/research/OFFICIAL_EVIDENCE_REGISTER.md](../../docs/planning/research/OFFICIAL_EVIDENCE_REGISTER.md#pinned-revisions).

| ID | Claim | Evidence (branch: path:line) |
|---|---|---|
| EV-201 | QWeb `t-out` directive is compiled from 15.0; no `_compile_directive_out` in 14.0 | 15.0: `odoo/addons/base/models/qweb.py:1087`; 14.0: same file, ABSENT |
| EV-202 | `t-raw` produces a "Found deprecated directive @t-raw" warning from 15.0 | 15.0: `odoo/addons/base/models/qweb.py:1154`; 16.0: `odoo/addons/base/models/ir_qweb.py:2065` |
| EV-203 | The 16.0 QWeb reference docstring marks `t-esc` and `t-raw` "Deprecated, please use `t-out`" | 16.0: `odoo/addons/base/models/ir_qweb.py:297–303` |
| EV-204 | Odoo's own view-arch RELAX NG validation uses `lxml.etree.RelaxNG` | 18.0: `odoo/addons/base/models/ir_ui_view.py:9`, `:301–302` |
| EV-205 | 12.0 has no top-level `openerp` package | 12.0: repository root, `openerp/` ABSENT |
| EV-206 | 12.0 has no `ir.values` model file in `base` | 12.0: `odoo/addons/base/models/`, `ir_values*` ABSENT |
| EV-207 | `mail.thread.message_post_with_template` exists in 16.0 and is absent in 17.0 | 16.0: `addons/mail/models/mail_thread.py:2197`; 17.0/18.0/19.0: ABSENT in `addons/mail/models/` |
| EV-208 | `website.published.mixin` is still defined in 17.0 and 18.0 | 17.0: `addons/website/models/mixins.py:183`; 18.0: `:180` |
| EV-209 | 19.0 deprecates `_cr` / `_uid` properties with replacements `self.env.cr` / `self.env.uid` | 19.0: `odoo/orm/models.py:5930–5936` (`@api.deprecated("Deprecated since 19.0, use self.env.cr directly")`) |
| EV-210 | `res.users.has_group(group_ext_id)` in 17.0; `has_groups(group_spec)` in 18.0 and 19.0 | 17.0: `odoo/addons/base/models/res_users.py:1089`; 18.0: `:1159`; 19.0: `:1034` |
| EV-211 | 12.0 `odoo/models.py` has no `_columns` model-attribute handling (matches are `_check_removed_columns`, `_create_parent_columns`); `odoo/osv/` still contains `expression.py`, `orm.py`, `osv.py`, `query.py` | 12.0: `odoo/models.py:2340`, `:2473`; `odoo/osv/` listing |
| EV-212 | `addons/spreadsheet_dashboard` exists in 17.0 and 18.0 | 17.0/18.0: directory present |

Note on EV-210: whether `has_group` was removed in 18.0 or kept alongside `has_groups` was not
checked. It is recorded as G-R-16.

## New research gaps

| ID | Gap | Blocks |
|---|---|---|
| G-R-13 | Provenance, tags, and maintenance of official Odoo container images (`github.com/odoo/docker`) | P7 runtime adapter (ADR-011) |
| G-R-14 | Semantic equivalence of 12.0 `sudo(user)` and 13.0 `with_user(user)` / `with_user(user).sudo()` | Rule `12-13.python.sudo-user-argument` fixer |
| G-R-15 | Replacement for `SavepointCase` in 17.0 (`TransactionCase` behaviour) | Rule `16-17.tests.savepointcase-removed` fixer |
| G-R-16 | Replacement API for `user_has_groups` in 18.0 and whether `has_group` remains | Rule `17-18.python.user-has-groups-removed` fixer |
| G-R-17 | Unverified legacy claims: `fields.Html` sanitize defaults (17), `attachment=False` (18), `_auto_init` (19), `phone.validation.mixin` path | Legacy rules marked needs-research |
| G-R-18 | Backend CSS class changes per version | CSS rules |
| G-R-19 | Odoo 20.0 not inspected (no branch evaluated during planning) | Step 19-20 |

## Coverage honesty

Research status of every step after planning: `RESEARCH_SEEDED` (12→19) or `NOT_ASSESSED`
(19→20). Feature 004 delivers the **machinery** and migrates the seed. Completing research per
step is scheduled in feature 006 (tasks for each G-R gap before the rules that depend on it).
