# Data Model: Official Source Intelligence

All files live under `src/odooflux/knowledge/`. Encoding is UTF-8 JSON with sorted keys and
2-space indentation (deterministic diffs). Schema documents are written to
`knowledge/schemas/*.schema.json` using the JSON Schema 2020-12 vocabulary. They are validated by
the stdlib checker in `src/odooflux/knowledge/` (feature 004 tasks).

## Layout

```text
src/odooflux/knowledge/
├── schemas/
│   ├── evidence.schema.json
│   ├── version.schema.json
│   ├── revisions.schema.json
│   ├── allow_list.schema.json
│   ├── step_research.schema.json
│   ├── gap.schema.json
│   └── rule_metadata.schema.json
├── official_sources/
│   ├── allow_list.json
│   └── revisions.json
├── evidence/
│   └── EV-NNN.json            (one record per file)
├── compatibility/
│   ├── versions.json
│   ├── <step>.research.json   (e.g. 16-17.research.json)
│   ├── <step>.rules.json      (populated in feature 006)
│   └── core_modules/<ver>.json (populated in feature 006)
└── gaps.json
```

## EvidenceRecord

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string | yes | `^EV-\d{3}$`; unique; equals file name |
| `rule_ids` | array[string] | yes (may be empty) | Each `^(\d+-\d+|\*)\.[a-z_]+\.[a-z0-9-]+$` |
| `category` | enum | yes | `orm, fields, decorators, views, data_files, qweb, javascript, owl, assets, manifest, security, controllers, cron, tests, python_runtime, dependencies, documentation` |
| `source_applicability` | object `{from, to}` | yes | Version IDs in the registry; `from ≤ to` |
| `target_applicability` | object `{from, to|null}` | yes | `null` = open-ended |
| `description` | string | yes | ≤ 300 chars |
| `url` | string | yes | Must start with an allow-list prefix |
| `repository` | string | yes | e.g. `odoo/odoo` |
| `revision` | string | yes | 40-hex SHA or tag in `revisions.json` |
| `locations` | array[Location] | yes, ≥1 | See below |
| `detection_method` | string | yes | Free text, or `n/a` for documentation-only records |
| `proposed_transformation` | string | yes | Edit description, or `review-only`, or `none` |
| `risk` | enum | yes | `LOW, MEDIUM, HIGH` |
| `required_validation` | array[string] | yes | Validator IDs (e.g. `syntax.python`, `static.rescan`, `runtime.install`) |
| `status` | enum | yes | `VERIFIED, DOCUMENTED_NOT_TESTED, UNVERIFIED, CONFLICTING, NOT_APPLICABLE` |
| `checked_on` | string | yes | ISO date |
| `checked_by` | string | yes | Person, agent, or `refresh-job` |
| `runtime_test_ref` | string | required iff `status == VERIFIED` | Test ID from P7 |
| `notes` | string | no | |

**Location**: `{ "branch": "17.0", "revision": "<sha>", "path": "odoo/models.py",
"line": 1694 | null, "match": "def name_get(", "kind": "present" | "absent" }`.
An `absent` location requires `line: null` and a `search_scope` (path or directory).

**State transitions**: `UNVERIFIED → DOCUMENTED_NOT_TESTED → VERIFIED`; any state →
`CONFLICTING` on a failed refresh; `CONFLICTING → DOCUMENTED_NOT_TESTED` after re-research.

## OdooVersion (`compatibility/versions.json`)

Array of objects matching
[CONTRACTS.md#odooversion](../../docs/planning/architecture/CONTRACTS.md#odooversion). Additional
validation: `major` unique and strictly increasing in file order; `research_status` uses the
matrix vocabulary; `support_status` ∈ `UNSUPPORTED, EXPERIMENTAL, SUPPORTED`; `SUPPORTED`
requires that every inbound step is `RULES_TESTED` and the version is `RUNTIME_VALIDATED`.

## RevisionCatalogue (`official_sources/revisions.json`)

`[{ "repository": "odoo/odoo", "branch": "17.0", "revision": "<sha>", "committed": "2026-11-05",
"pinned_on": "2026-11-06", "tags": [] }]`. A record's `revision` must appear here.

## AllowList (`official_sources/allow_list.json`)

`[{ "prefix": "https://github.com/odoo/odoo/", "kind": "source" }, …]` mirroring the strategy
document. `kind` ∈ `source, documentation, framework, tooling, runtime_provenance`.

## StepResearchRecord (`compatibility/<step>.research.json`)

| Field | Type | Notes |
|---|---|---|
| `step` | string | `"16-17"` |
| `revisions` | object | SHAs used for `from`, `to`, docs |
| `categories` | object | Category → `{status, evidence: [EV…], gaps: [G-R…]}`; status uses the matrix vocabulary |
| `peer_reviewed` | bool | Required for `RESEARCHED` |
| `notes` | string | |

The step's overall `research_status` is the minimum over its categories.

## ResearchGap (`gaps.json`)

`[{ "id": "G-R-07", "description": "...", "steps": ["17-18"], "categories": ["views"],
"blocks_rules": ["17-18.xml.tree-to-list"], "status": "OPEN" | "RESOLVED",
"resolved_by": ["EV-…"] }]`.

## RuleMetadata (`compatibility/<step>.rules.json`)

All non-code fields of the Rule contract
([CONTRACTS.md#rule](../../docs/planning/architecture/CONTRACTS.md#rule)) plus
`detector_ref`, `fixer_ref` (dotted names under `odooflux.rules`), and `tests` (list of test IDs
proving positive, negative, and idempotence). Feature 004 defines and validates the schema;
feature 006 populates it.

## Matrix generation inputs → outputs

Inputs: versions, step research records, gaps, rule metadata, and test-result manifest (from P5
CI). Output: `docs/planning/VERSION_COMPATIBILITY_MATRIX.md` (sections: matrix, evidence per
step, rule catalogue). The output is fully determined by the inputs. There are no timestamps
except the data's `checked_on` maximum.
