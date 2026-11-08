# Contract: Rule catalogue for feature 006

The authoritative list of rules is the knowledge-base data. This catalogue fixes the **initial
target set** for P5 from the seed catalogue in
[VERSION_COMPATIBILITY_MATRIX.md](../../../docs/planning/VERSION_COMPATIBILITY_MATRIX.md#seed-rule-catalogue-candidates-not-implemented)
plus non-seed rules required by the spec.

Maturity shown is the ceiling. Implementers may ship lower maturity if tests or research are
incomplete, and must record why.

## Group A — evidence-complete, mechanical fixes

| Rule | Evidence | Ceiling | Generic fixer |
|---|---|---|---|
| 12-13.python.api-multi-removed | EV-101 | FIX_ENABLED | `remove_decorator` |
| 15-16.python.search-args-keyword | EV-013 | FIX_ENABLED | `rename_keyword` (calls to `search`, `search_count`, `_search`) |
| 15-16.python.x2many-limit-attribute | EV-013 | FIX_ENABLED | `remove_keyword` |
| 15-16.python.removed-field-attributes | EV-014 | FIX_ENABLED | `remove_keyword` (`column_format`, `deprecated`) |
| 16-17.python.warning-exception | EV-110 | FIX_ENABLED | bespoke import/raise rewrite |
| 17-18.xml.tree-to-list | EV-112 | FIX_ENABLED | `rename_tag`, `rewrite_view_mode` (XML + Python dict) |
| 17-18.python.group-operator-renamed | EV-010, EV-118 | FIX_ENABLED | `rename_keyword` |
| 18-19.python.route-type-json | EV-007, EV-115 | FIX_ENABLED | keyword value rewrite |
| 18-19.python.env-shortcuts-deprecated | EV-003, EV-209 (+ `_context` task) | FIX_ENABLED | attribute rewrite |

## Group B — fixes gated on research

| Rule | Evidence | Gate | Ceiling |
|---|---|---|---|
| 16-17.xml.attrs-removed | EV-109 | G-R-20 | FIX_ENABLED |
| 16-17.xml.states-attribute-removed | EV-109 | G-R-20 | FIX_ENABLED |
| 14-15.qweb.t-esc-deprecated | EV-201, EV-203 | — (P7 check later) | FIX_ENABLED |
| 16-17.tests.savepointcase-removed | EV-111 | G-R-15 | FIX_ENABLED |
| 17-18.python.user-has-groups-removed | EV-105, EV-210 | G-R-16 | FIX_ENABLED |
| 16-17.xml.act-window-tag | EV-117 | design + G-R-06 | FIX_ENABLED |
| 16-17.xml.report-tag | EV-117 | design + G-R-06 | FIX_ENABLED |
| 14-15.manifest.qweb-key | EV-123, EV-124 | G-R-05 | FIX_ENABLED |

## Group C — detect-only, review required

| Rule | Evidence |
|---|---|
| 12-13.python.api-one-removed | EV-101 |
| 12-13.python.sudo-user-argument | EV-103 (G-R-14) |
| 14-15.qweb.t-raw-deprecated | EV-202 |
| 15-16.python.fields-view-get | EV-107 |
| 15-16.python.browse-str-ids | EV-013 (not review; DETECT_ONLY) |
| 15-16.python.deprecated-model-methods | EV-013 (not review; DETECT_ONLY) |
| 16-17.python.field-states-parameter | EV-108 |
| 16-17.python.name-get-deprecated | EV-011 |
| 16-17.python.read-group-signature | EV-012 |
| 16-17.python.message-post-with-template | EV-207 |
| 17-18.python.name-get-removed | EV-104 |
| 17-18.python.name-search-to-search-display-name | EV-008, EV-106 |
| 17-18.xml.cron-numbercall-removed | EV-113 |
| 17-18.xml.kanban-box-deprecated | EV-119 (not review; DETECT_ONLY) |
| 17-18.js.rpc-service-removed | EV-120 |
| 18-19.python.api-returns-removed | EV-102 |
| 18-19.python.sql-constraints-unsupported | EV-006, EV-116 |
| 18-19.python.osv-deprecated | EV-002 (not review; DETECT_ONLY) |
| 18-19.python.read-group-deprecated | EV-004 |
| 18-19.any.res-users-groups-id | EV-114 |
| 18-19.xml.kanban-box-removed | EV-119 |

## Group D — shared hygiene rules (`step: "*"`, evidence `NOT_APPLICABLE`)

| Rule | Purpose |
|---|---|
| *.manifest.parse-error | Manifest not parseable by `ast.literal_eval` |
| *.manifest.version-prefix | Version prefix vs target; preserve suffix (REQ-MAN-002) |
| *.manifest.not-installable | `installable: False` (legacy M2) |
| *.manifest.missing-data-file | REQ-MAN-003 |
| *.manifest.load-order | Security before views (REQ-MAN-003) |
| *.deps.unknown-dependency | REQ-DEP-001 |
| *.refs.dangling-reference | REQ-DEP-003 |
| *.python.sql-string-formatting | Legacy PYTHON_RULES#23 (security hygiene) |
| *.any.parse-error | File unparseable |

## Group E — research-dependent (no rule until evidence exists)

Chatter (G-R-09), OWL hooks/components and legacy widgets (G-R-03), the legacy `odoo.define`
form (G-R-08), XML data shorthand tags `<url>` and `<openerp>` root (G-R-06), security data
changes beyond EV-114 (G-R-10), controller changes before 19.0 (G-R-11), CSS (G-R-18),
legacy claims (G-R-17), steps 12-13/13-14 general diff (G-R-01).

## Amendment 2026-11-07: run-supplied parameters and Group D (DRAFT)

### Contract change: `bind_rule(meta, modules, run_params=None)`

- New optional argument `run_params: dict | None` (initial key: `target`, the planned step's target version string, e.g. `"16.0"`; the planner supplies it, not rule metadata).
- For each bound function (detector, fixer), keys of `run_params` are passed as keywords only if the function's signature declares that parameter name. Undeclared keys are ignored.
- A key present in both static `params` and `run_params` is a BindingError (no silent override).
- A function that requires a run key (declared with no default, as `flag_version_prefix(..., *, target)`) and a `run_params` that lacks it: the rule binds as "unbound-needs-run-context" and is skipped with an INFO gap, never an exception.
- Defaults: `run_params=None` means current behaviour. Existing signatures, `BoundRule` fields used by callers, and rule metadata schema are unchanged (a rule needing a run key is recognised from the function signature, no schema change). If a `requires_run_params` metadata key is later wanted, that is a separate amendment.
- Non-regression test: for every existing rule, binding with `run_params=None` and with `{"target": X}` yields identical detector_params/fixer_params and identical findings on the golden and per-rule fixtures.

### Group D (proposed rule IDs; maturity ceiling is a ceiling, all pending acceptance)

| Rule | Evidence | Ceiling |
|---|---|---|
| 15-16.python.model-renamed-payment-provider | EV-450 | DETECT_ONLY, review_required |
| 15-16.xml.model-renamed-payment-provider | EV-450 | DETECT_ONLY, review_required |
| 15-16.csv.model-renamed-payment-provider | EV-450 plus ACL id evidence to be researched | DETECT_ONLY, review_required |
| `*.manifest.version-prefix` (per-run bind, existing DRAFT) | none (policy) | DETECT_ONLY now; FIX_ENABLED only by separate owner decision |
| `*.deps.removed-with-successor` | per-module evidence to be researched | DETECT_ONLY |
| `*.xml.inherit-id-missing-in-target` | view index evidence to be researched | DETECT_ONLY |
| `*.xml.xpath-anchor-missing-in-target` | view index evidence to be researched | DETECT_ONLY |
