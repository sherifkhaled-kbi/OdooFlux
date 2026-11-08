# Product Requirements

Source of truth for product-level requirements. Every Spec Kit functional requirement (`FR-…`)
traces to one or more `REQ-…` IDs here, and every `REQ-…` traces to a phase, tasks, and tests in
[REQUIREMENTS_TRACEABILITY_MATRIX.md](REQUIREMENTS_TRACEABILITY_MATRIX.md).

Verification methods: **UT** unit test, **IT** integration test, **GT** golden-fixture test,
**RT** runtime (containerised Odoo) test, **FI** failure-injection test, **BM** benchmark,
**RV** documented review/inspection, **EV** evidence audit.

## Product objectives

| ID | Objective |
|---|---|
| OBJ-001 | Multi-version migration from any researched source version to any higher supported version |
| OBJ-002 | Complete compatibility analysis, safe transformation, and validation across all module artefacts |
| OBJ-003 | Official Odoo research forming a traceable, version-specific knowledge base |
| OBJ-004 | Evidence-only compatibility rules |
| OBJ-005 | Efficient, provider-independent AI assistance |
| OBJ-006 | Clear, actionable terminal and HTML reports with structured exports |
| OBJ-007 | Extensible architecture |
| OBJ-008 | Migration safety and recovery |
| OBJ-009 | Verifiable results with disclosed limits |

## Requirements

### SAF — Safety and recovery (OBJ-008)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-SAF-001 | Analysis and `--dry-run` MUST NOT create, modify, rename, or delete anything inside scanned module or addons paths. | SHA-256 of every file and the directory listing are identical before and after an analysis and a dry-run on every golden fixture. | IT, GT | P0 |
| REQ-SAF-002 | No transformed file may be written unless it passes the syntax validator for its file type. | Injecting a fixer that emits invalid Python/XML/manifest results in zero writes for that file and a `rejected` edit record with the parser error. | UT, FI | P0 |
| REQ-SAF-003 | Backups MUST be created outside every scanned addons path and verified (file count and checksums) before any write. | Backup path is not under any `--addons-path`/module parent scanned; verification mismatch aborts the module with exit code for tool error. | IT, FI | P0 |
| REQ-SAF-004 | A failed or unverifiable backup MUST abort writes for that module. | Simulated backup failure → module status `BLOCKED`, zero files modified. | FI | P0 |
| REQ-SAF-005 | File writes MUST be atomic (temporary file + atomic replace on the same filesystem). | Killing the process during a write never leaves a truncated or partially written target file (fault injection at each write step). | FI | P0 |
| REQ-SAF-006 | Every write MUST be recorded in a run log (path, pre-hash, post-hash, edit IDs, backup location). | Run log entries exist for 100 % of written files and allow restore via the rollback command. | IT | P0 (log), P2 (rollback) |
| REQ-SAF-007 | Transformations MUST operate on an isolated working copy; results are promoted only after validation. | During a run the original module is unchanged until the promote step; promotion failure leaves originals intact. | IT, FI | P2 |
| REQ-SAF-008 | The tool MUST provide rollback of a completed or partial run from its run log. | Rollback restores byte-identical originals for all files listed in the run log on every golden fixture. | IT | P2 |
| REQ-SAF-009 | Long runs MUST checkpoint per module and support resume. | Interrupting a multi-module run and resuming finishes with the same final report as an uninterrupted run. | IT, FI | P2 |
| REQ-SAF-010 | Legacy unsafe auto-fixes (in-tag XML comments, decorator removal that breaks indentation, `size=` comma breakage, `.sudo(<bool>)` rewrite, JS comments in Python) MUST be removed or corrected. | Each audit reproduction (F-XML-1, F-PY-1, F-PY-2, F-PY-5, F-PY-6) has a regression test that passes. | UT, GT | P0 |

### TST — Test foundation and quality (OBJ-009)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-TST-001 | The project MUST have an automated test suite runnable with a single documented command using the standard library runner. | `python -m unittest discover -s tests` runs all non-runtime tests and exits 0 on main. | IT | P1 |
| REQ-TST-002 | Every rule and fixer MUST have positive, negative, and idempotence tests. | A coverage check lists every registered rule and fails if any lacks the three test kinds. | UT | P1 (harness), P5 (rules) |
| REQ-TST-003 | Golden fixture modules MUST exist for each supported source version and include expected outputs and reports. | One fixture per source version in the registry; golden comparison is byte-exact. | GT | P1, P5 |
| REQ-TST-004 | Characterisation tests MUST capture current legacy behaviour before any refactor. | Characterisation suite passes on the legacy entry point before Phase P2 begins and after cut-over (or documents each intended difference). | GT | P1 |
| REQ-TST-005 | Every fixed defect MUST add a regression test referencing its finding ID. | Each `F-…` finding marked resolved has a test whose name or docstring cites the ID. | RV | P0–P9 |
| REQ-TST-006 | Tests requiring Docker, network, or AI providers MUST be isolated and skippable. | Default test run passes with no network and no Docker; marked suites run only when explicitly enabled. | IT | P1 |

### ARC — Architecture and extensibility (OBJ-007)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-ARC-001 | Core components MUST use only the Python standard library; optional dependencies MUST be isolated in adapters. | Import-graph test proves no core module imports a non-stdlib package. | UT | P2 |
| REQ-ARC-002 | Versions, rules, parsers, validators, AI providers, runtime environments, and report renderers MUST be registered through registries with documented contracts. | Adding a sample plugin of each kind requires no edit to `core/`; contract tests pass for each. | UT, RV | P2 |
| REQ-ARC-003 | No maximum Odoo version may be hardcoded in the engine. | Static search finds no version literal outside the version registry data and tests; a synthetic version 20 fixture loads via data only. | UT | P2 |
| REQ-ARC-004 | The legacy CLI MUST keep working until cut-over, and cut-over MUST preserve documented CLI options or document replacements. | Characterisation suite (REQ-TST-004) passes on the new entry point, or each difference is listed in the change record. | GT | P2 |
| REQ-ARC-005 | Output MUST be deterministic for identical inputs and configuration. | Two runs on the same fixture produce byte-identical JSON reports (excluding timestamps/durations fields). | IT | P2 |
| REQ-ARC-006 | Plugins MUST declare a contract version; incompatible plugins MUST be rejected with a clear error. | Loading a plugin with a mismatched contract version fails with a specific error and does not crash the run. | UT | P2 |

### VER — Multi-version engine (OBJ-001)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-VER-001 | A Version Registry MUST describe each Odoo version (identifier, release lineage, Python range, research status, support status). | Registry entries exist for 12.0–19.0; status values match the compatibility matrix. | UT | P2 (schema), P3 (data) |
| REQ-VER-002 | A Version Graph MUST compute the ordered internal steps for any requested source→target path. | For every pair (s, t) with s < t in the registry, the planner returns the consecutive steps s→s+1…t-1→t. | UT | P2 |
| REQ-VER-003 | Requests for unsupported or unresearched paths MUST be refused or downgraded explicitly, never silently processed. | Requesting a path with a step in `NOT_ASSESSED` returns `BLOCKED` (or `NEEDS_REVIEW` with `--allow-unverified`) and names the missing steps. | UT, IT | P2 |
| REQ-VER-004 | Rules MUST be applied in step order, with declared dependencies and conflict resolution. | Ordering test with rules that depend on each other produces the documented order; conflicting edits are rejected and reported. | UT | P2 |
| REQ-VER-005 | Adding a new Odoo version MUST be possible by adding data, rules, and fixtures only. | A documented procedure is followed in a test that adds a synthetic version without editing core code. | IT, RV | P2, P5 |
| REQ-VER-006 | The source version MUST be detected from the manifest and cross-checked against the requested source version. | Mismatch produces a finding; detection is correct for all golden fixtures. | UT | P2 |

### EVD — Official evidence and knowledge base (OBJ-003, OBJ-004)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-EVD-001 | Every rule MUST reference at least one evidence record with an official URL and immutable revision. | Rule-loading validation fails for any rule without a valid evidence reference. | UT | P3 |
| REQ-EVD-002 | Evidence records MUST use the defined schema and status vocabulary. | Schema validation passes for all records; unknown status values are rejected. | UT | P3 |
| REQ-EVD-003 | Only rules whose evidence status permits it may run fixers; `UNVERIFIED`/`CONFLICTING` rules MAY only detect. | Engine refuses to apply fixes for rules with those statuses (test with a fixture rule). | UT | P3, P5 |
| REQ-EVD-004 | Evidence sources MUST be restricted to an allow-list of official domains/repositories. | Validation rejects records citing any URL outside the allow-list. | UT | P3 |
| REQ-EVD-005 | A documented, repeatable refresh workflow MUST re-verify evidence against new SHAs and new versions. | Refresh procedure produces a diff report of changed/broken locations for a test pair of SHAs. | IT, RV | P3 |
| REQ-EVD-006 | The Version Compatibility Matrix MUST be generated from knowledge-base data, not hand-edited. | Matrix regeneration is deterministic; hand edits are detected by a test. | UT | P3 |

### TRF — Transformation contract (OBJ-002, OBJ-008)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-TRF-001 | Every change MUST be expressed as an Edit with ID, rule ID, file, span, before text, after text, and validation requirements. | All applied changes in a run appear as Edit records in the report; none lack required fields. | UT | P2 (contract), P4 |
| REQ-TRF-002 | Overlapping edits MUST be detected and resolved by documented precedence, or rejected. | Conflict test with overlapping spans yields the documented outcome. | UT | P4 |
| REQ-TRF-003 | Every fixer MUST be idempotent. | Applying the transformation pipeline twice produces identical output on every golden fixture. | GT | P4, P5 |
| REQ-TRF-004 | Edits MUST preserve untouched source bytes (formatting, comments, quoting, line endings, encoding). | Byte comparison outside edit spans is identical for every golden fixture. | GT | P4 |
| REQ-TRF-005 | A finding MAY be marked fixed only if re-scanning the validated output no longer produces it. | Report fix counts equal the difference between pre-fix and post-fix scans on every fixture. | IT | P0 (re-scan), P2 |

### PY — Python and ORM (OBJ-002)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-PY-001 | Python analysis MUST use syntax-aware parsing (`ast`/`tokenize`) for detection and edit spans; multi-line constructs MUST be detected. | Multi-line field definitions, decorators, and imports in fixtures are detected with correct spans. | UT | P4 |
| REQ-PY-002 | Decorator, import, exception, and field-attribute rules MUST be implemented as evidence-backed rules per step. | Each rule in the P5 rule catalogue has evidence, tests, and correct step gating. | UT, EV | P5 |
| REQ-PY-003 | Semantics-changing ORM constructs (e.g., removed `@api.one`, `@api.returns`, `name_get`, `_sql_constraints`, overrides of `create`/`write`) MUST be flagged for review unless a documented safe transformation exists. | Fixtures with these constructs produce `NEEDS_REVIEW` findings with evidence links; no silent rewrites. | UT, GT | P5 |
| REQ-PY-004 | The tool MUST parse customer Python written for every supported source version's Python range. | Fixture modules using syntax valid for each source version's minimum Python parse successfully under the tool's interpreter. | UT | P4 |

### XML — Views, data files, QWeb (OBJ-002)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-XML-001 | XML analysis MUST be structure-aware, with precise spans for elements and attributes. | Span locator returns exact byte ranges for elements/attributes on fixtures including multi-line attributes and comments. | UT | P4 |
| REQ-XML-002 | `attrs`/`states` view attributes MUST be converted into Python-expression modifiers (`invisible`, `readonly`, `required`, `column_invisible`) when convertible; otherwise left unchanged and flagged. | Converter test corpus (operators `=`, `!=`, `in`, `not in`, `<`, `>`, `|`, `&`, `!`, nested) produces expected expressions; unconvertible inputs yield findings and no edit. | UT, GT | P4, P5 |
| REQ-XML-003 | View-type and arch changes (`tree`→`list`, kanban template, chatter) MUST be evidence-backed rules gated by step. | Rule tests confirm step gating per EV-112/EV-119 and chatter evidence once researched. | UT, EV | P5 |
| REQ-XML-004 | Every written XML file MUST be well-formed and every modified view arch MUST pass RNG validation for the target version when the schema is available. | Validation layer rejects malformed output; RNG validation runs when the target RNG is present in the knowledge base. | UT, IT | P0 (well-formed), P7 (RNG) |
| REQ-XML-005 | QWeb directive changes MUST be covered by evidence-backed rules. | Rules exist for researched directive changes; unresearched ones are listed as gaps. | UT, EV | P5 |

### JS — JavaScript, OWL, assets (OBJ-002)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-JS-001 | JavaScript analysis MUST NOT rely on regex alone for structural transforms; a JS parser adapter MUST be used for edits. | Without the adapter, JS findings are detect-only and results are `NEEDS_REVIEW`; with it, edit spans come from the parse tree. | UT | P4 |
| REQ-JS-002 | OWL, service, registry, and module-system changes MUST be covered by evidence-backed rules per step. | Rules for EV-120/121/122 and researched OWL changes exist with tests. | UT, EV | P5 |
| REQ-JS-003 | Asset bundle declarations (manifest `assets`, legacy `qweb` key, XML asset templates) MUST be analysed and migrated where evidence allows. | Fixtures with each style produce the expected findings/edits per step (EV-123/124). | UT, GT | P5 |
| REQ-JS-004 | Written JS files MUST pass syntax validation when the adapter is present. | Invalid JS output is rejected before promotion. | UT | P4 |

### MAN / DEP — Manifest and dependencies (OBJ-002)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-MAN-001 | Manifests MUST be parsed with `ast.literal_eval`; `__openerp__.py` handling MUST happen only in write mode. | Parse errors become findings; analyze mode never renames or copies manifests. | UT, IT | P0 (no write), P2 |
| REQ-MAN-002 | Version bumps MUST preserve the module's own version suffix unless the user opts out. | `14.0.2.3.1` → `19.0.2.3.1` by default. | UT | P0 |
| REQ-MAN-003 | Manifest `data`, `demo`, and asset paths MUST be checked for existence and load order. | Missing files and security-after-views ordering produce findings on fixtures. | UT | P5 |
| REQ-DEP-001 | Module `depends` MUST be checked against the target version's core module list and the scanned custom modules. | Unknown or removed dependencies produce findings; list provenance cites evidence. | UT, EV | P5 |
| REQ-DEP-002 | Multi-module runs MUST process modules in dependency order. | Topological order test; cycles are reported, not crashed on. | UT | P2 |
| REQ-DEP-003 | Cross-module references (models, fields, XML IDs, groups) MUST be resolved where data is available and unresolved references reported. | Fixture with a dangling XML ID / missing field produces a finding. | UT | P5, P7 |

### ACL — Module security artefacts (OBJ-002)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-ACL-001 | ACL CSV files, record rules, and groups MUST be scanned for version-specific changes. | Fixtures with renamed fields/models used in security data (e.g., EV-114) produce findings. | UT | P5 |
| REQ-ACL-002 | Runtime validation MUST check that access rights load and that declared groups resolve. | Runtime test on the install fixture reports ACL load errors as `FAILED` with log excerpt. | RT | P7 |

### BIZ — Business logic (OBJ-002, OBJ-009)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-BIZ-001 | Risky constructs (ORM overrides, computed fields, onchange, constraints, multi-company, transactions, scheduled actions, controllers) MUST be inventoried per module. | Inventory lists every occurrence in fixtures with location and risk class. | UT | P5 |
| REQ-BIZ-002 | The tool MUST run the module's own tests on the source and target versions when runtime validation is enabled and compare results. | Behavioural report shows pass/fail per test on both versions for the behavioural fixture. | RT | P7 |
| REQ-BIZ-003 | The report MUST state the behavioural verification scope and limits explicitly. | Every report contains a verification-scope section; no `VERIFIED_SUCCESS` without behavioural tests. | IT | P7, P8 |

### VAL — Validation layers and result statuses (OBJ-009)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-VAL-001 | Layer 1 syntax validation for Python, XML, manifest (and JS with adapter) MUST run before any promotion. | See REQ-SAF-002. | UT | P0, P2 |
| REQ-VAL-002 | Layer 2 static compatibility MUST re-scan output against target rules. | Post-fix scan results are attached to the report. | IT | P2 |
| REQ-VAL-003 | Layer 3 dependency integrity MUST check modules, models, fields, XML IDs, groups, Python packages. | Fixture with each kind of broken reference yields a finding. | UT | P5, P7 |
| REQ-VAL-004 | Layer 4 runtime validation MUST install and upgrade the module in an isolated, disposable target-version environment and analyse logs. | Install fixture yields `INSTALL_VERIFIED`; broken fixture yields `FAILED` with log excerpts. | RT | P7 |
| REQ-VAL-005 | Layer 5 behavioural validation MUST run module tests and configured scenarios. | See REQ-BIZ-002. | RT | P7 |
| REQ-VAL-006 | Result statuses MUST follow the exact conditions in the validation strategy; unavailable mandatory layers MUST cap the status. | Status decision table test covers every combination of layer outcomes. | UT | P2 (model), P7 |

### AI — Optional AI assistance (OBJ-005)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-AI-001 | AI MUST be disabled by default and provider-neutral behind a provider interface. | Core has no provider imports; a fake provider passes the contract tests. | UT | P6 |
| REQ-AI-002 | AI MAY be invoked only for findings marked AI-eligible that no deterministic rule fixes. | Engine test: deterministic-fixable findings are never sent to AI. | UT | P6 |
| REQ-AI-003 | AI output MUST be converted into Edits and pass all validation layers plus protected-identifier checks. | Fake provider returning a renamed field/model/import is rejected. | UT | P6 |
| REQ-AI-004 | Context MUST be minimal (function-level where possible) with fresh line numbers from the content sent. | Prompt-builder test: context excludes unrelated functions and line numbers match the sent text. | UT | P6 |
| REQ-AI-005 | Per-request, per-file, per-module, and per-job token budgets MUST be enforced; truncation MUST be detected. | Budget-exceeding requests are not sent; truncated responses are rejected with a specific reason. | UT | P6 |
| REQ-AI-006 | Token usage and cost (when pricing data is configured) MUST be reported per request and in total. | Report contains usage fields matching the fake provider's reported usage. | UT | P6 |
| REQ-AI-007 | Verified results MUST be cacheable by content hash, rule ID, provider, model, and prompt version. | Second run on unchanged input makes zero provider calls. | IT | P6 |
| REQ-AI-008 | Credentials MUST come from environment or a secrets file, never CLI arguments, and MUST be redacted from all outputs. | Secret-scan test of logs/reports finds no credential; CLI rejects key-as-argument after deprecation window. | UT | P6, P9 |

### REP — Reporting and UX (OBJ-006)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-REP-001 | A versioned, presentation-independent report schema MUST be the single source for all outputs. | All renderers consume the schema object; JSON output validates against the published schema. | UT | P2 (schema), P8 |
| REQ-REP-002 | Terminal output MUST show progress, stage, per-module and per-file results, and actionable guidance, and work without colour. | Snapshot tests for colour and no-colour modes. | UT | P8 |
| REQ-REP-003 | A self-contained static HTML report MUST be produced (no external network resources). | HTML file opens offline; contains every section in the schema. | UT | P8 |
| REQ-REP-004 | SARIF and unified-diff exports MUST be available. | SARIF validates against SARIF 2.1.0 schema; diff applies cleanly with `patch`. | UT | P8 |
| REQ-REP-005 | Exit codes MUST be configurable with `--fail-on` and documented. | Exit code table test for each threshold. | UT | P0 (basic), P8 |
| REQ-REP-006 | Reports MUST include evidence links, rejected edits, validation results per layer, verification limits, AI usage, durations, and recovery instructions. | Schema test asserts all sections exist; golden reports contain them. | GT | P8 |

### SEC — Tool security (OBJ-008)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-SEC-001 | Customer code MUST never be executed outside an isolated runtime environment. | Static check: no `exec`/`import` of scanned code in core; runtime layer uses containers with no host mounts except the read-only module copy. | UT, RV | P2, P7 |
| REQ-SEC-002 | Runtime environments MUST enforce CPU, memory, time, and network limits. | Runtime test with a looping module is terminated at the time limit and reported `FAILED`. | RT, FI | P7 |
| REQ-SEC-003 | Files written by the tool outside the module (logs, debug, cache) MUST go to a tool-owned directory, never into customer modules. | Run on fixture leaves no tool artefacts inside the module. | IT | P0, P6 |
| REQ-SEC-004 | Prompt-injection content in customer code MUST NOT alter tool behaviour; AI output is data only. | Fixture with injection comments produces no deviation in plan or validation outcome. | UT | P6 |
| REQ-SEC-005 | An audit log of actions (reads of config, writes, AI requests metadata, runtime launches) MUST be produced. | Audit log contains an entry per action type in an integration run. | IT | P9 |

### PRF — Performance and scale (OBJ-007)

| ID | Requirement | Acceptance criterion | Verify | Phase |
|---|---|---|---|---|
| REQ-PRF-001 | Analysis of a repository of 300 synthetic modules (≈30 files each) MUST complete within a documented budget on the reference machine. | Benchmark result recorded; budget set in Phase P9 from P2 baseline, regression >20 % fails CI. | BM | P2 (baseline), P9 |
| REQ-PRF-002 | Incremental analysis MUST skip unchanged files using content hashes. | Second run on unchanged input re-parses zero files. | IT | P9 |
| REQ-PRF-003 | Parallel execution MUST be safe and produce deterministic output. | Parallel and serial runs produce identical reports. | IT | P9 |
| REQ-PRF-004 | Memory use MUST stay bounded per worker. | Benchmark peak RSS recorded and below the documented budget. | BM | P9 |

## Non-goals (explicit)

- Migrating database data. OdooFlux migrates module **source**; data migration scripts are
  flagged and templated but not executed against customer databases.
- Supporting Odoo versions older than 12.0.
- Claiming Enterprise module compatibility without authorised Enterprise source access.
