# Official Evidence Register (planning seed)

This register records the official evidence gathered **during planning** on 2026-11-06. It is the
seed for the machine-readable knowledge base built in Phase P3
([specs/004-official-source-intelligence](../../../specs/004-official-source-intelligence/)).
It is deliberately limited to claims that were directly inspected. It is **not** a complete
compatibility study; see the gaps section and
[../VERSION_COMPATIBILITY_MATRIX.md](../VERSION_COMPATIBILITY_MATRIX.md).

## Method

- Shallow clones of `https://github.com/odoo/odoo` and `https://github.com/odoo/documentation`,
  one per branch, pinned to the commit SHA below. Branches are moving targets, so **the SHA is
  the evidence revision**; re-verify against a newer SHA when refreshing.
- Claims were checked with targeted `grep` on the pinned files. "Line" is the 1-based line at that
  SHA. `ABSENT` means the construct was searched for in that file and not found.
- No unofficial source was used. No runtime test was executed, so no record is runtime-tested.

## Pinned revisions

| Repo | Branch | Commit SHA | Committed |
|---|---|---|---|
| odoo/odoo | 12.0 | `ba1ba88874e2ae9716e59ec199eb739d58c3f771` | 2024-01-29 |
| odoo/odoo | 13.0 | `4cc086d330b73514fbc64a7fcf22d8a7a9f1b691` | 2024-01-31 |
| odoo/odoo | 14.0 | `cc0060e889603eb2e47fa44a8a22a70d7d784185` | 2024-10-22 |
| odoo/odoo | 15.0 | `3a28e5b0adbb36bdb1155a6854cdfbe4e7f9b187` | 2024-11-01 |
| odoo/odoo | 16.0 | `9f40bf622c5531739321e59276c307319198e22b` | 2026-11-06 |
| odoo/odoo | 17.0 | `9ef8d62331b128bcd288528e4639e0901d85fcc8` | 2026-11-05 |
| odoo/odoo | 18.0 | `75d6abe5979ac9e8d85d097dad0e7b559ef07326` | 2026-11-06 |
| odoo/odoo | 19.0 | `58bb9591d4cb08c4d5d4426222c9257f101ad250` | 2026-11-06 |
| odoo/documentation | 12.0 | `c6556f144db6e3b9a94ddf1e6f586e0ab4f38a40` | — |
| odoo/documentation | 13.0 | `f7407ebae9886f5662a55fb14753a0db00187a63` | — |
| odoo/documentation | 14.0 | `cbf8a7bf815b51ae6277f83999c3267fff4cd67f` | — |
| odoo/documentation | 15.0 | `f6b84ed59624ba8f0db2b1d0f7097e435550bb7e` | — |
| odoo/documentation | 16.0 | `f61c6f0d8df0a849b3e15cb24eaf9c10c52332d7` | — |
| odoo/documentation | 17.0 | `fbf3e3a6ef0bda7c30b28f213848deca17c2a872` | — |
| odoo/documentation | 18.0 | `cc3890dc84189dfa58680242d7e96c816f2dec27` | — |
| odoo/documentation | 19.0 | `706918083dbd7dbc8e70c658d3ca63d700f94228` | — |

URL form for a source location:
`https://github.com/odoo/odoo/blob/<SHA>/<path>#L<line>`.

## Evidence status used here

All records below are `DOCUMENTED_NOT_TESTED`: the behaviour is shown by official source or
documentation at a pinned SHA, but no OdooFlux rule or runtime test has exercised it. A record
becomes `VERIFIED` only after the Phase P5/P7 validation defined in
[../OFFICIAL_SOURCES_STRATEGY.md](../OFFICIAL_SOURCES_STRATEGY.md#evidence-statuses).

## Documentation evidence

| ID | Claim | Source | Location |
|---|---|---|---|
| EV-001 | The official ORM changelog lists per-release ORM changes from Odoo Online 15.2 to 19.0 (cumulative in the 19.0 docs) | odoo/documentation 19.0 `7069180` | `content/developer/reference/backend/orm/changelog.rst` (whole file) |
| EV-002 | 19.0: `odoo.osv` deprecated (PR #217708) | same | changelog line 14 |
| EV-003 | 19.0: `record._cr`, `record._context`, `record._uid` deprecated (PR #193636) | same | line 15 |
| EV-004 | 18.2 (on-premise: 19.0): `read_group` deprecated in favour of `_read_group` (backend) and `formatted_read_group` (public) (PR #163300) | same | line 40 |
| EV-005 | 18.2: `@api.private` added to distinguish RPC-exposed methods | same | line 42 |
| EV-006 | 18.1: constraints and indexes declared as model attributes (PR #175783) | same | line 52 |
| EV-007 | 18.1: `json` controllers renamed `jsonrpc` (route `type`) (PR #183636) | same | line 53 |
| EV-008 | 18.0: searching by name implemented as `_search_display_name` | same | line 59 |
| EV-009 | 18.0: new `check_access`, `has_access`, `_filtered_access` combine access rights and rules | same | line 61 |
| EV-010 | 17.2 (on-premise: 18.0): field attribute `group_operator` renamed `aggregator` (PR #127353) | same | line 82 |
| EV-011 | 16.4 (on-premise: 17.0): `name_get` deprecated; read `display_name` instead | same | line 108 |
| EV-012 | 16.3: `_read_group` has a new signature | same | line 115 |
| EV-013 | 15.3 (on-premise: 16.0): `search` argument `args` renamed `domain`; `browse` rejects `str` ids; `fields_get_keys`/`get_xml_id` deprecated; `_mapped_cache` removed; `limit` attribute of One2many/Many2many removed (PR #83687) | same | lines 150–156 |
| EV-014 | 15.2 (on-premise: 16.0): `_sequence` removed; `column_format` and `deprecated` field attributes removed (PR #82727) | same | lines 165–167 |
| EV-015 | No ORM changelog page exists in the 12.0–15.0 documentation branches | odoo/documentation 12.0–15.0 | `git ls-tree` on the pinned SHAs |

## Source-code evidence

Paths are relative to the repository root at the pinned SHA for that branch.

| ID | Claim | Evidence (branch: path:line) |
|---|---|---|
| EV-101 | `@api.one` and `@api.multi` exist in 12.0 and are removed in 13.0 | 12.0: `odoo/api.py:336` (`multi`), `:355` (`one`); 13.0: `odoo/api.py` ABSENT |
| EV-102 | `@api.returns` exists through 18.0 and is removed in 19.0 | 12.0: `odoo/api.py:238`; 18.0: `odoo/api.py:359`; 19.0: `odoo/orm/decorators.py` ABSENT and no `def returns` anywhere under `odoo/` |
| EV-103 | `sudo(user)` (12.0) became `sudo(flag=True)` plus `with_user(user)` in 13.0; the flag form persists to 19.0 | 12.0: `odoo/models.py:4789` `def sudo(self, user…`; 13.0: `odoo/models.py:5157` `def sudo(self, flag…`, `:5189` `def with_user(`; 19.0: `odoo/orm/models.py:5973` |
| EV-104 | `BaseModel.name_get` exists in 17.0 and is removed in 18.0 | 17.0: `odoo/models.py:1694`; 18.0: ABSENT |
| EV-105 | `user_has_groups` exists in 17.0 and is removed in 18.0 | 17.0: `odoo/models.py:1559`; 18.0: ABSENT |
| EV-106 | `_name_search` (17.0) replaced by `_search_display_name` (18.0) | 17.0: `odoo/models.py:1773`; 18.0: `odoo/models.py:1823` |
| EV-107 | `fields_view_get` on `BaseModel` through 15.0; 16.0 provides `get_view` and logs that `_fields_view_get` is deprecated | 15.0: `odoo/models.py:1704`; 16.0: `odoo/addons/base/models/ir_ui_view.py:2684` (`get_view`), `:2764` (deprecation) |
| EV-108 | Field parameter `states` exists in 16.0; 17.0 warns "Since Odoo 17, property … states is no longer supported"; absent in 18.0 | 16.0: `odoo/fields.py:324`; 17.0: `odoo/fields.py:540`; 18.0: ABSENT |
| EV-109 | 17.0 view validation rejects `attrs` and `states` view attributes ("Since 17.0, the "attrs" and "states" attributes are no longer used") | 17.0: `odoo/addons/base/models/ir_ui_view.py:394` |
| EV-110 | `odoo.exceptions.Warning` is an alias (`Warning = UserError`) in 12.0/13.0, a subclass of `UserError` in 14.0–16.0, and no longer defined as a class in 17.0 | 12.0: `odoo/exceptions.py:37`; 14.0: `:132`; 16.0: `:129`; 17.0: no `class Warning` |
| EV-111 | `SavepointCase` exists through 16.0 and is removed in 17.0 | 16.0: `odoo/tests/common.py:826`; 17.0: ABSENT |
| EV-112 | The view type selection has `tree` in 17.0 and `list` (no `tree`) in 18.0 | 17.0: `odoo/addons/base/models/ir_ui_view.py:163`; 18.0: `:153` `('list',`, `('tree',` ABSENT |
| EV-113 | `ir.cron.numbercall` exists in 17.0 and is removed in 18.0 | 17.0: `odoo/addons/base/models/ir_cron.py:67`; 18.0: ABSENT |
| EV-114 | `res.users.groups_id` (18.0) renamed `group_ids` (19.0) | 18.0: `odoo/addons/base/models/res_users.py:386`; 19.0: `:257` (`group_ids`), `groups_id` field ABSENT |
| EV-115 | 19.0: `@route(type='json')` is a deprecated alias of `type='jsonrpc'` | 19.0: `odoo/http.py:814` |
| EV-116 | 19.0: `_sql_constraints` is no longer supported (warning only; constraints are not applied); `Constraint` table objects replace it | 19.0: `odoo/orm/model_classes.py:163`; `odoo/orm/table_objects.py:79` |
| EV-117 | The `<act_window>` data-file tag is deprecated in 16.0 and both `<act_window>` and `<report>` tag handlers are removed in 17.0 | 16.0: `odoo/tools/convert.py:342` (deprecation), `:278` (`_tag_report`); 17.0: both ABSENT |
| EV-118 | Field attribute `group_operator` (17.0) → `aggregator` (18.0) | 17.0: `odoo/fields.py:323`; 18.0: `odoo/fields.py:193` |
| EV-119 | Kanban `t-name="kanban-box"` is the template name in 17.0, deprecated in 18.0 (new `card` template), and no longer referenced in 19.0's arch parser | 17.0: `addons/web/static/src/views/kanban/kanban_arch_parser.js:10`; 18.0: `:11`; 19.0: ABSENT |
| EV-120 | The `rpc` service is registered in 17.0; 18.0 exports an `rpc` function and no longer registers the service | 17.0: `addons/web/static/src/core/network/rpc_service.js:140`; 18.0: `addons/web/static/src/core/network/rpc.js:65`, `rpc_service.js` ABSENT |
| EV-121 | JS transpilation of native modules is triggered by the `@odoo-module` comment (16.0/17.0); from 18.0 `is_odoo_module` also receives the asset URL | 17.0: `odoo/tools/js_transpiler.py:673`; 18.0: `:675` |
| EV-122 | `odoo.define(name, deps, factory)` remains the module loader API in 17.0 (positional `deps`) | 17.0: `addons/web/static/src/module_loader.js:29` |
| EV-123 | The manifest `assets` key is read by `ir.asset` in 15.0 | 15.0: `odoo/addons/base/models/ir_asset.py:216` |
| EV-124 | The manifest `qweb` key is read by the web client in 14.0 | 14.0: `addons/web/controllers/main.py:589` |
| EV-125 | Minimum Python declared by Odoo: 12.0 `>=3.5`, 14.0 `>=3.6`, 16.0 `>=3.7`, 17.0 and 18.0 `>=3.10`; 19.0 `MIN_PY_VERSION = (3, 10)` | `setup.py` lines 59/58/64/66/68; 19.0: `odoo/release.py:39` |

## Corrections to the previous audit

Comparing against [../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md](../../reviews/ODOO_MODULE_UPGRADER_AUDIT.md):

- **F-PY-3** said `@api.returns` "still exists". That holds through 18.0 only. It is **removed in
  19.0** (EV-102). Deleting it is therefore correct for 19.0 targets and wrong for ≤18.0 targets,
  and in both cases the return-value conversion semantics need review.
- The current tool says `@api.one`/`@api.multi` were "removed in v14+". They were removed in
  **13.0** (EV-101).
- The current tool says `odoo.exceptions.Warning` was "removed in v14". It became a deprecated
  subclass in 14.0–16.0 and was removed in **17.0** (EV-110).
- The current tool says `<tree>` was "deprecated in v18 and replaced by `<list>`". At the pinned
  SHAs the view type is `list` from 18.0 (EV-112). Whether 18.0 still accepts a `<tree>` arch root
  was **not** verified; that is a research gap (G-R-07).
- The current tool says `odoo.define()` was "removed in v17+". The loader API `odoo.define(name,
  deps, factory)` still exists in 17.0 (EV-122). The legacy `odoo.define(name, function (require)
  {…})` form was not verified as accepted or rejected; that is a research gap (G-R-08).
- New, not covered by the current tool: EV-104/105/106/108/111/113/114/115/116/117/118/119/120.
  EV-116 is high-impact: a v19 migration that leaves `_sql_constraints` in place silently loses
  database constraints.

## Research gaps (seed list)

| ID | Gap |
|---|---|
| G-R-01 | No ORM changelog for 12.0→15.0 transitions (EV-015). Those transitions need source diff research. |
| G-R-02 | Odoo Enterprise source not accessed (no authorised access during planning). |
| G-R-03 | OWL framework (`odoo/owl`) version per Odoo release, and OWL API changes, not yet researched. |
| G-R-04 | QWeb directive changes (`t-esc`/`t-raw`/`t-out`) not yet researched beyond presence counts. |
| G-R-05 | Asset bundle names and the 15.0 transition from XML asset templates to manifest `assets`, beyond EV-123/124. |
| G-R-06 | XML view RNG schema differences per version (`odoo/addons/base/rng/`) not diffed. |
| G-R-07 | Whether 18.0 accepts a `<tree>` arch root (backward compatibility) is not verified. |
| G-R-08 | Acceptance of the legacy `odoo.define(name, function(require){})` form in 17.0+ is not verified. |
| G-R-09 | `<chatter/>` tag introduction version and `oe_chatter` support window (source counts were ambiguous). |
| G-R-10 | Security model changes (`res.groups`, `ir.rule`, ACL CSV columns) per version. |
| G-R-11 | Controller/HTTP changes before 19.0 (`auth`, `csrf`, `type='http'` behaviours). |
| G-R-12 | Data-migration requirements between versions (official upgrade scripts are a service; `upgrade-util` is official but not yet reviewed). |

Gaps G-R-13 to G-R-23 were added while writing the feature specifications. The canonical list of
all gaps is [../PLANNING_GAPS_AND_ASSUMPTIONS.md §2](../PLANNING_GAPS_AND_ASSUMPTIONS.md#2-research-gaps).

## Additional evidence recorded in feature research

| Range | Location | Topic |
|---|---|---|
| EV-201 – EV-212 | [specs/004-official-source-intelligence/research.md](../../../specs/004-official-source-intelligence/research.md) | QWeb `t-out`/`t-raw`/`t-esc`, RNG via lxml, 12.0 namespace facts, `message_post_with_template`, `website.published.mixin` (still present in 18.0), `_cr`/`_uid` deprecation, `has_group(s)`, `spreadsheet_dashboard` |
| EV-301 – EV-303 | [specs/008-runtime-behavioral-validation/research.md](../../../specs/008-runtime-behavioral-validation/research.md) | `odoo/docker` contents, view RNG files, Odoo CLI options for runtime validation |

All of these are `DOCUMENTED_NOT_TESTED` and use the same pinned SHAs (or the SHA stated in the record).
