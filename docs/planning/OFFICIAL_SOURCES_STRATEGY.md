# Official Sources Strategy

How OdooFlux establishes, records, uses, and refreshes evidence for every Odoo-specific
compatibility claim. Binding under constitution Principle VI (Official Evidence Only) and
[ADR-008](ARCHITECTURE_DECISIONS.md#adr-008--evidence-status-is-separate-from-rule-maturity).
Implemented in Phase P3 ([specs/004-official-source-intelligence](../../specs/004-official-source-intelligence/)).

## Approved sources (allow-list)

Only these sources may be cited as evidence for Odoo behaviour (REQ-EVD-004).

| Source | Allowed URL prefix | Revision requirement |
|---|---|---|
| Odoo Community source | `https://github.com/odoo/odoo/` | Commit SHA (40 hex) or release tag |
| Odoo Enterprise source | `https://github.com/odoo/enterprise/` | Commit SHA; only with authorised access (D-05: default none) |
| OWL framework | `https://github.com/odoo/owl/` | Commit SHA or release tag (e.g. `v2.x.y`) |
| Odoo documentation source | `https://github.com/odoo/documentation/` | Commit SHA |
| Odoo documentation site | `https://www.odoo.com/documentation/<version>/` | Version path + retrieval date; the matching `odoo/documentation` SHA SHOULD also be recorded |
| Odoo upgrade utilities | `https://github.com/odoo/upgrade-util/` | Commit SHA |
| Odoo Docker images (runtime provenance only) | `https://github.com/odoo/docker/` | Commit SHA (research gap G-R-13) |

An unpinned branch (`master`, `17.0` without SHA) is **never** sufficient on its own. Branch names
may appear only alongside the SHA used.

## Prohibited as authority

Blogs, forums, Stack Overflow, Reddit, YouTube, third-party migration tools (including OCA
`openupgrade` and its scripts), AI-generated text (including this tool's AI subsystem),
memorised model knowledge, and internal skills (for example the `odoo-dev` skill). These MAY be
read for generic techniques, never cited as proof of Odoo behaviour.

## Evidence statuses

| Status | Definition | May drive a fixer? |
|---|---|---|
| `VERIFIED` | Official source or documentation at a pinned revision shows the behaviour **and** an OdooFlux runtime test on the target version (Phase P7) confirmed it | Yes |
| `DOCUMENTED_NOT_TESTED` | Official source or documentation at a pinned revision shows the behaviour; no OdooFlux rule test or runtime test has exercised it yet. All planning-phase records start here | Yes, once the rule's positive/negative/idempotence tests pass (rule maturity `FIX_ENABLED`) |
| `UNVERIFIED` | Claim believed plausible but not yet located in an official source | No (detect-only, flagged) |
| `CONFLICTING` | Two official sources (or two revisions) disagree, or source and docs disagree | No (detect-only; research task required) |
| `NOT_APPLICABLE` | Claim does not apply to the transition or edition in question (kept to record a negative result) | No (rule not loaded for that step) |

Promotion path: `UNVERIFIED → DOCUMENTED_NOT_TESTED` (official location found) `→ VERIFIED`
(runtime test passed on target). Demotion: a refresh that cannot re-locate the claim sets
`CONFLICTING` and disables fixers until resolved (REQ-EVD-003).

## Evidence record schema

Each record is one JSON object in `src/odooflux/knowledge/evidence/` (format fixed by
[specs/004-official-source-intelligence/data-model.md](../../specs/004-official-source-intelligence/data-model.md)).
Rule-facing fields required by the brief:

| Field | Meaning |
|---|---|
| `id` | `EV-NNN` |
| `rule_ids` | Rule IDs relying on this evidence (`<step>.<area>.<slug>`) |
| `category` | `orm`, `fields`, `decorators`, `views`, `data_files`, `qweb`, `javascript`, `owl`, `assets`, `manifest`, `security`, `controllers`, `cron`, `tests`, `python_runtime`, `dependencies` |
| `source_applicability` | Versions where the old behaviour exists (e.g. `["12.0","17.0"]` range) |
| `target_applicability` | Versions where the new behaviour holds |
| `description` | One-sentence claim |
| `url` | Allow-listed URL |
| `revision` | SHA or tag |
| `location` | Path + line (or doc section + line) at that revision |
| `detection_method` | How a rule detects the old construct (AST pattern, XML attribute, token, manifest key) |
| `proposed_transformation` | Deterministic edit, or `review-only` |
| `risk` | `LOW`, `MEDIUM`, `HIGH` (behavioural impact if wrong) |
| `required_validation` | Validator IDs / layers that must pass |
| `status` | Evidence status above |
| `checked_on` | ISO date of last verification |
| `checked_by` | Person or process (`refresh-job`) |
| `notes` | Optional |

## Research workflow per transition (step `N → N+1`)

1. **Pin revisions.** Record the SHAs of `odoo/odoo` `N.0` and `N+1.0`, `odoo/documentation`
   `N+1.0`, and `odoo/owl` used by `N+1.0` (from `addons/web/static/lib/owl/`).
2. **Read the official changelog** (`content/developer/reference/backend/orm/changelog.rst`,
   available from the 16.0 docs; it covers Online releases 15.2 onward, EV-001/EV-015). Map Online
   releases to the next major (ADR-007).
3. **Diff framework surfaces** between the two SHAs, for each category: `odoo/models.py` or
   `odoo/orm/`, `odoo/fields.py`, `odoo/api.py`, `odoo/http.py`, `odoo/tools/convert.py`,
   `odoo/addons/base/models/ir_ui_view.py`, `odoo/addons/base/rng/*.rng`,
   `odoo/addons/base/models/ir_qweb.py`, `ir_asset.py`, `ir_cron.py`, `res_users.py`,
   `odoo/tools/js_transpiler.py`, `addons/web/static/src/{core,views}/`, `odoo/tests/common.py`,
   `setup.py`/`release.py`.
4. **Record each claim** as an evidence record with exact path:line at both revisions
   (presence/absence), status `DOCUMENTED_NOT_TESTED`.
5. **Derive candidate rules** (detection + proposed transformation or `review-only`), risk, and
   required validation. Semantics-changing claims are `review-only` (Principle VIII).
6. **Record gaps** (`G-R-…`) for categories not yet researched; the matrix cell stays
   `NOT_ASSESSED` or `RESEARCH_SEEDED`.
7. **Peer review**: a second person or agent re-runs the location checks from the record alone.
8. **Mark the step** `RESEARCHED` in the version registry when every category is either covered
   by records or listed as an explicit gap.

## Refresh workflow (new SHAs, new releases, Odoo 20)

Run on each new Odoo major release and at least every release of OdooFlux:

1. Fetch the new branch SHAs (for a new major, e.g. `20.0`, add a registry entry with
   `research_status: NOT_ASSESSED`, `support_status: UNSUPPORTED`).
2. Re-run every record's location check against the new SHA of its `target_applicability`
   versions (automated by the P3 refresh tool; REQ-EVD-005). Output: unchanged / moved (line drift,
   update location) / missing (set `CONFLICTING`, disable fixers, open research task).
3. For a new major, perform the per-transition workflow for step `19 → 20`.
4. Regenerate the Version Compatibility Matrix from data (REQ-EVD-006) and diff it.
5. A new version becomes `SUPPORTED` only per [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md#version-support-milestones).

## How planning research was done

Shallow clones of `odoo/odoo` and `odoo/documentation` for branches 12.0–19.0, pinned to the SHAs
listed in [research/OFFICIAL_EVIDENCE_REGISTER.md](research/OFFICIAL_EVIDENCE_REGISTER.md), were
inspected with targeted searches. Results are records EV-001…EV-015 (documentation) and
EV-101…EV-125 (source); twelve further source records (EV-201…EV-212) were added during feature
004 planning and are listed in
[specs/004-official-source-intelligence/research.md](../../specs/004-official-source-intelligence/research.md).
No runtime test was executed, so no record is `VERIFIED`. Known gaps are G-R-01…G-R-12 (register) and G-R-13…G-R-19 (feature 004 research).
