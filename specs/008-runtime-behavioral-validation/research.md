# Research: Runtime and Behavioral Validation (P7)

## Evidence IDs (correction)

The first P7 planning draft named its evidence EV-301, EV-302 and EV-303. Those IDs were already taken by
phase-3 records of feature 006 (`EV-300`–`EV-303` describe `ir.ui.view` and `ir.actions` types). The P7
evidence was therefore recorded under new IDs (EV-354 to EV-371). Mapping from the draft:

| Draft ID | Claim | Recorded as |
|---|---|---|
| EV-301 (odoo/docker master) | Repository version directories at master | EV-354, EV-359 |
| EV-302 (RNG schemas per version) | tree_view / list_view RNG files | EV-370 |
| EV-303 (CLI options) | `--update`, `--without-demo`, `--test-enable`, `--test-tags`, `--stop-after-init` | EV-371 |

The earlier note "the presence of a `20.0` directory is not evidence of an Odoo 20 release" still holds.
Odoo 20.0 has no `odoo/odoo` revision in `official_sources/revisions.json`.

## Research closure (T001–T004)

Pinned sources: `odoo/docker` master `f900094eb7492968332868d686caf22b966592ca` (2026-11-02, not archived);
its parent of the 17.0 removal `d9c2d8d50aa8eca1aadc186241bee3eac0e2d79e`. `odoo/odoo` SHAs as in
`official_sources/revisions.json` (16.0 `9f40bf6`, 17.0 `9ef8d62`, 18.0 `75d6abe`, 19.0 `58bb959`).
Revisions were read through raw GitHub and the GitHub commit/contents API. No repository was cloned.
Revisions use `branch: master` for `odoo/docker`, which has no version branches; `revisions.schema.json`
and `evidence.schema.json` accept `master` for that reason.

### T001 — G-R-13: official image provenance (closed for the claims T014 uses)

| Claim used by the runtime adapter | Status | Evidence |
|---|---|---|
| The repository is the official image source for Docker Hub `odoo` | EVIDENCED | EV-354 (README) |
| 18.0–20.0 images install Odoo from the nightly `.deb` on `nightly.odoo.com`, checked by a pinned SHA1 | EVIDENCED | EV-355 (Dockerfiles) |
| Base OS is `ubuntu:noble` for 18.0–20.0 | EVIDENCED | EV-356 |
| Container runs as user `odoo`, declares `/mnt/extra-addons` as a VOLUME, entrypoint `/entrypoint.sh` | EVIDENCED | EV-357 |
| Entrypoint reads DB user/password from environment defaults and passes `DB_ARGS` | EVIDENCED | EV-358 |
| Image tags (`odoo:19.0` etc.) and their maintenance policy | UNVERIFIED | The repository has no tags (`/tags` API returned none). Tag policy is published on Docker Hub, which is not in `allow_list.json`. The adapter pins by digest read from the local daemon (`RepoDigests`), not by tag alone. |
| `nightly.odoo.com` as a trusted host | UNVERIFIED | Not in `allow_list.json`. The SHA1 check in EV-355 is the only integrity evidence. |
| Maintenance | OBSERVED (not evidence-grade) | Repository not archived; last push 2026-11-02; 17.0 directory removed 2026-09-24 (EV-359). |
| Docker CLI isolation semantics (`--network none`, `--read-only`, label filters, `--memory`, `--cpus`, `--pids-limit`) | UNVERIFIED by evidence | Docker documentation is not allow-listed. The opt-in runtime tests exercise the behaviour; the results are in the verification log in [quickstart.md](quickstart.md#verification-log-t028). |

Status: G-R-13 is closed for the claims above. The UNVERIFIED rows stay UNVERIFIED and are not reported as
facts in reports.

### T002 — G-R-21: image source for versions ≤ 17.0 (gap retained, status capped)

Decision: **retain G-R-21 open** and cap the runtime layer for source or target versions ≤ 17.0.

Evidence:
- The 17.0 image directory is absent at master. It was removed by commit `38e5b43b` on 2026-09-24 (EV-359).
  The last 17.0 Dockerfile (parent `d9c2d8d`) installed Odoo from a nightly `.deb` on `nightly.odoo.com`.
  That host is not in `allow_list.json`, so the artifact cannot be checked against an allow-listed source.
- 16.0 and earlier have no directory at master.
- Building from pinned `odoo/odoo` source would need a Dockerfile this project would own. That is not
  evidenced and is out of scope for P7.
- The host has official `odoo:17` images (Docker Hub). Their provenance is not recorded in this repository,
  so they are not used by default.

Consequence: for these versions the runtime layer reports `UNAVAILABLE` with reason `image_unavailable`.
Status is capped at `STATIC_VALIDATED`. This is also the explicit cap the edge case in spec.md requires.

### T003 — G-R-22: install/upgrade log patterns (closed)

Patterns are in `src/odooflux/knowledge/compatibility/runtime_log_patterns.json` (schema
`knowledge/schemas/runtime_log_patterns.schema.json`). Each pattern cites EV-360 to EV-367 at 16.0–19.0.
Coverage of FR-006 classes: `registry`, `import_error`, `view_validation`, `access_rights`, `data_load`,
`asset_compile`, `missing_python_dependency`. `timeout` and `oom` are not log patterns: the adapter sets them
from the container state (`killed_reason`). Unmatched lines are `unknown`.

Known differences by version:
- Missing Python dependency: `Python library not installed` (16.0, 17.0) versus `External dependency ... not
  installed` (18.0, 19.0).
- Asset parse failure: logged as an error (16.0, EV-366) versus rendered into the bundle as a generated error
  (18.0, 19.0).
- Unknown external ID in `ir.model.access.csv`: attributed by a `context` match on the same log record (`ir.model.access`), see EV-365. On 19.0 the same fixture yields an SQL NOT NULL error on `ir_model_access.model_id`, explained by the required field in EV-376.

Not researched: 12.0–15.0 (no runtime image, G-R-21), and 20.0 (no `odoo/odoo` revision catalogued).

### T004 — G-R-23: test-runner output format (closed for 16.0–19.0)

Source: `odoo/tests/result.py` (EV-368) and `odoo/modules/loading.py` (EV-369) at 16.0–19.0.

Parser specification (input: the log of `odoo -d <db> -u <modules> --test-enable --test-tags <tags> --stop-after-init`):

1. Each log record starts with a timestamp and level. Logger names of tests have the form
   `odoo.addons.<module>.tests.<file>`; the module comes from the logger name.
2. **Failure**: a record at ERROR whose first message line is `ERROR: <Class>.<method>` or
   `FAIL: <Class>.<method>`. Outcome `error` or `fail`; test id `<module>.<Class>.<method>`.
3. **Subtest**: `Subtest <Class>.<method> <desc>` is a failure of the parent test id.
4. **Skip**: an INFO record `skipped <Class>.<method> : <reason>`. Outcome `skip`.
5. **Started**: each test that runs logs `Starting <Class>.<method> ...` at INFO on its module's test logger
   (`TestResult` startTest, EV-377). This is the completeness marker.
6. **Pass**: Odoo logs nothing for a passing test (`addSuccess` is a no-op, EV-368). A test is `pass` only when it is
   in the static test universe of the module (`def test_*` found by AST in the module's `tests/`), it started, and
   it has no fail, error or skip record. A static test that never started is not a pass: it makes the module's
   coverage `partial`.
   Observed on 19.0 (opt-in run, fixture `behavior_compare`): the `odoo.tests.stats` line
   (`<module>: <N> tests ...`, EV-368) is cumulative across runs in the same process (5 reported for 3 tests), so it is
   not used for completeness.
7. **Run-level**: `At least one test failed when loading the modules.` confirms failures during install.

Target versions in scope: 16.0, 17.0, 18.0, 19.0 (format evidenced). 20.0: format UNVERIFIED, so L5 is
`UNAVAILABLE` with reason `test_format_unverified`.

## RELAX NG (for REQ-XML-004)

EV-370: `tree_view.rng` at 16.0–17.0 and `list_view.rng` at 18.0–19.0. No `form_view.rng` at 16.0 or 18.0.
EV-363: import-time XML validation also uses `import_xml.rng` (convert.py). The adapter validates against the
per-version files listed in `compatibility/` data. It does not ship Odoo schema files. The caller supplies the
directory of the pinned Odoo source's `odoo/addons/base/rng/`; if it is absent the check reports `UNAVAILABLE`.

## Research gaps (status after this closure)

| ID | Status | Note |
|---|---|---|
| G-R-13 | CLOSED for T014 claims; tag policy and Docker CLI semantics UNVERIFIED | EV-354–EV-358 |
| G-R-21 | OPEN, capped | Versions ≤ 17.0 → `image_unavailable` (EV-359) |
| G-R-22 | CLOSED for 16.0–19.0 | EV-360–EV-367 |
| G-R-23 | CLOSED for 16.0–19.0; 20.0 UNVERIFIED | EV-368, EV-369, EV-377 |

`knowledge/gaps.json` belongs to feature 006 and was not edited. Its statuses for these gaps still read
OPEN until 006 reconciles them; the table above is the P7 record.

## Decisions

| Decision | Rationale | Alternatives |
|---|---|---|
| Docker CLI via subprocess as first backend (D-03, approved) | Ubiquitous, no SDK dependency, strong isolation primitives | Docker SDK (dependency); local virtualenv (no isolation, rejected by REQ-SEC-001) |
| Fresh database per run, install then optional upgrade | Matches what customers do after code migration | Restore customer DB (data migration is a non-goal) |
| Status table with strict precedence | Deterministic and testable (SC-001) | Score-based status (opaque) |
| L5 `coverage` attribute | Distinguishes "target tests passed" from "behaviour compared with baseline" | Treat target-only pass as full (over-claims; violates Principle VIII) |
| RNG via optional `lxml` (D-02, pending) | stdlib lacks RELAX NG | Hand-written structural checks (incomplete) |
| Error-pattern data file per version | New versions add data, not code (Principle IX) | Hardcoded regexes in adapter |

## Can and cannot be automated

See [VALIDATION_AND_TEST_STRATEGY.md § Behavioural validation](../../docs/planning/VALIDATION_AND_TEST_STRATEGY.md#layer-5--behavioural-validation).
