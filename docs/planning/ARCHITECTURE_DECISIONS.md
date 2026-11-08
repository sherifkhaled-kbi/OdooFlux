# Architecture Decision Records

Status values: **Accepted** (binding for implementation), **Proposed – approval pending** (the
default plan assumes it; a maintainer must confirm; see the linked `D-NN` in
[PLANNING_GAPS_AND_ASSUMPTIONS.md](PLANNING_GAPS_AND_ASSUMPTIONS.md)).

---

## ADR-001 — `src/` layout; legacy script untouched until cut-over

**Status:** Accepted

**Context.** The repository has one application file, `odooflux.py`, at the root. A package
directory named `odooflux/` next to it would shadow `import odooflux` as soon as it contained an
`__init__.py`. The planning brief forbids shadowing, moving, or changing the existing entry point.

**Decision.**
- The target package lives at `src/odooflux/`. Nothing under `src/` is on `sys.path` today, so it
  cannot shadow the root module.
- Scaffolding contains **no `__init__.py` files**, only `.gitkeep`, so no importable package exists
  until Phase P2 deliberately creates one.
- Phases P0 and P1 work on the legacy `odooflux.py` (safety fixes and characterisation tests).
- Phase P2 builds `src/odooflux/` and performs the cut-over: the root `odooflux.py` becomes a thin
  launcher that delegates to `src/odooflux/cli/` only after the characterisation suite passes
  (REQ-ARC-004).

**Consequences.** No import ambiguity during transition. Packaging metadata (`pyproject.toml`) is
introduced only in P2, subject to D-09.

---

## ADR-002 — Dependency policy: stdlib core, optional adapters

**Status:** Proposed – approval pending (D-01). Already applied in constitution 2.0.0.

**Context.** Constitution 1.0.0 Principle I required a single stdlib-only file. The objectives
need capabilities the standard library lacks: JavaScript parsing (OBJ-002), RELAX NG validation
of view archs (stdlib has none), container control for runtime validation (OBJ-009), and
optional AI SDKs.

**Decision.** The core stays stdlib-only. Optional third-party dependencies are allowed only in
adapters (`parsers/javascript`, `validation/runtime`, `validation/static` RNG, `ai/providers`,
`reporting/terminal` rich mode), declared as optional extras. A missing adapter downgrades results
to `NEEDS_REVIEW`; it never fails silently or claims success.

**Alternatives rejected.** Stay stdlib-only: JS and runtime validation would be impossible, which
contradicts OBJ-002/OBJ-009. Allow dependencies anywhere: loses zero-install analysis.

---

## ADR-003 — Span-based edits ("parse to locate, splice to edit")

**Status:** Accepted

**Decision.** Parsers are used to **find** constructs and their exact byte spans and to
**validate** results, never to re-serialise whole files. Every change is an `Edit`
(see [architecture/CONTRACTS.md](architecture/CONTRACTS.md#edit)) spliced into the original
text. Bytes outside edit spans are preserved exactly (REQ-TRF-004).

**Why.** Re-serialising through `ast.unparse`, `ElementTree.write`, or a JS printer loses
comments, quoting, attribute order, and formatting, which makes customer diffs unreviewable.

---

## ADR-004 — Python: stdlib `ast` + `tokenize`

**Status:** Accepted

**Decision.** Use `ast` (node `lineno/col_offset/end_lineno/end_col_offset`) for structure and
`tokenize` for comments, decorators, and exact token spans. `libcst` (MIT) was evaluated: it is
format-preserving but third-party. It may be added later as an optional adapter if a rule cannot
be implemented with spans; that needs a new ADR.

**Constraint.** The tool's interpreter must parse every supported source version's code. Odoo
12.0 requires Python ≥3.5 (EV-125), so its syntax is a subset accepted by Python 3.10+ `ast`,
except removed constructs such as `async` used as an identifier. That case is handled as a
parse finding (REQ-PY-004).

---

## ADR-005 — XML: stdlib expat span locator; optional RNG adapter

**Status:** Accepted (RNG adapter part: Proposed, D-02)

**Decision.** A span locator built on `xml.parsers.expat` (start-tag byte offsets via
`CurrentByteIndex`) plus a small attribute lexer gives exact element and attribute spans.
`xml.etree.ElementTree` is used for well-formedness and structure checks. RELAX NG validation
against Odoo's `odoo/addons/base/rng/*.rng` needs `lxml` (BSD): it is an optional validation
adapter. When it is absent the layer reports "unavailable", which caps the result status.

---

## ADR-006 — JavaScript: optional parser adapter, detection-only fallback

**Status:** Proposed – approval pending (D-02)

**Context.** The standard library cannot parse JavaScript.

| Option | Licence | Pros | Cons |
|---|---|---|---|
| `tree-sitter` + `tree-sitter-javascript` (Python bindings) | MIT | Error-tolerant, exact byte spans, maintained, prebuilt wheels | Binary wheels; grammar version pinning |
| `esprima` (Python port) | BSD-2 | Pure Python | Unmaintained; ES2017 only (no modern syntax used by Odoo ≥16) |
| Node.js + `acorn` subprocess | MIT | Reference-quality parser | Requires Node runtime; process boundary |

**Decision (proposed).** Use the `tree-sitter` adapter for JS structure and spans. Without it, a
stdlib lexer (string/comment/template/regex-literal aware) supports **detection only**; JS edits
are disabled and results are `NEEDS_REVIEW` (REQ-JS-001).

---

## ADR-007 — Version graph of consecutive major steps

**Status:** Accepted

**Decision.** The Version Graph is the chain of on-premise major versions in the registry
(12.0 → 13.0 → … → 19.0 → future). A request s→t is planned as consecutive steps. Odoo Online
intermediate releases (x.1–x.4) are attributed to the next on-premise major version, which is
where on-premise users first see them (EV-001 lists them separately; for example, the 18.1
`jsonrpc` rename ships on-premise in 19.0, EV-007/EV-115).

**Runtime at intermediate versions.** Source transformations for intermediate steps run in
memory and are validated per step (syntax and static layers). Runtime installation is required
only at the **target** version by default, because OdooFlux migrates module source, not database
data (a non-goal). An intermediate runtime check is optional (`--validate-intermediate`) for
users who must upgrade a database step by step.

---

## ADR-008 — Evidence status is separate from rule maturity

**Status:** Accepted

**Decision.** Evidence status describes the **claim** (`VERIFIED`, `DOCUMENTED_NOT_TESTED`,
`UNVERIFIED`, `CONFLICTING`, `NOT_APPLICABLE`). Rule maturity describes the **rule**
(`DRAFT`, `DETECT_ONLY`, `FIX_ENABLED`, `RETIRED`). A rule may be `FIX_ENABLED` only if its
evidence is `DOCUMENTED_NOT_TESTED` or `VERIFIED` and its positive/negative/idempotence tests
pass. Evidence becomes `VERIFIED` only after a runtime test on the target version confirms the
behaviour (Phase P7).

---

## ADR-009 — Knowledge base stored as JSON data

**Status:** Accepted

**Decision.** Version registry, evidence records, rule metadata, and core-module lists are JSON
files under `src/odooflux/knowledge/`, validated by a stdlib schema checker. YAML was rejected
because it needs a third-party parser in the core. Rule **code** (detectors/fixers) lives under
`src/odooflux/rules/<language>/`; rule **metadata** references the code by ID.

---

## ADR-010 — Presentation-independent report schema

**Status:** Accepted

**Decision.** A versioned report model (`reporting/model`) is the single source. Renderers:
terminal (stdlib ANSI; optional `rich` adapter), static HTML (stdlib `string.Template`, inline CSS,
no JavaScript dependencies, offline), JSON (canonical), SARIF 2.1.0, unified diff.

---

## ADR-011 — Runtime validation in disposable containers

**Status:** Accepted (D-03 approved by the project owner, 2026-11-07)

**Decision.** Layer 4/5 validation runs the target Odoo version in disposable
containers (Odoo plus PostgreSQL), driven through the Docker CLI by an adapter. The customer
module copy is mounted read-only, the network is disabled by default, and CPU, memory, and time
are limited. Image provenance must be official. The Odoo-maintained `github.com/odoo/docker`
repository is the candidate source; it was not yet researched (gap G-R-13). Running customer
code in a local virtualenv was rejected because it gives no isolation (REQ-SEC-001).

---

## ADR-012 — AI as an Edit-producing plugin

**Status:** Accepted

**Decision.** An AI provider returns replacement text for a bounded region (one function, class
body, or XML element) chosen by the engine. The engine turns it into an `Edit` and validates it
exactly like a deterministic edit. Whole-file AI rewrites are not allowed. Providers implement a
neutral interface; transport uses `urllib` by default, with optional SDK adapters.

---

## ADR-013 — Job workspace, backups, and state directory

**Status:** Accepted

**Decision.** Each run gets a run ID and a state directory, `--state-dir`. It defaults to the
user cache directory (`$XDG_CACHE_HOME/odooflux` or `~/.cache/odooflux`) and is refused if it
lies inside any scanned path. The state directory holds `runs/<run-id>/{work,backup,log}`.
Modules are copied to `work/`, transformed and validated there, and promoted file by file with
atomic replace after the backup is verified. The run log enables rollback and resume.

---

## ADR-014 — Revised phase order

**Status:** Accepted. See [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md).

**Decision.** The provisional order P0…P9 is kept, with these dependency refinements:
- P7 (runtime/behavioural validation) depends only on P2, so it may run in parallel with P3–P6.
- P8 (reporting) depends on P2 (schema) and P7 (status model).
- P3 research data entry may start after P1; its code depends on P2.

---

## ADR-015 — One Spec Kit feature per phase, no git branches

**Status:** Accepted

**Decision.** Spec Kit 1.3.1 here uses sequential feature directories (`specs/NNN-name`) and
`.specify/feature.json`; it creates no branches. Each roadmap phase is one feature (001–010).
Branching is left to the implementer's own workflow.

---

## ADR-016 — Test runner: stdlib `unittest`

**Status:** Accepted

**Decision.** Tests use `unittest`, consistent with the stdlib core. Runtime and AI test suites
are opt-in through environment variables (`ODOOFLUX_RUNTIME_TESTS=1`, `ODOOFLUX_AI_TESTS=1`).
`pytest` may be used by developers as a runner (it can run `unittest` tests) but is not required.

---

## ADR-017 — D-08: external-first, provider-agnostic AI with explicit data authorization

**Status:** Accepted (D-08 approved by the project owner, 2026-11-07)

**Decision.**
- External AI is the default provider *type*; local endpoints (Ollama, vLLM, any compatible
  self-hosted endpoint) are optional. No GPU, local model, or inference service is required for
  install, startup, or normal operation.
- Supported external providers: Anthropic Claude, OpenAI GPT models, DeepSeek, and GLM via Z.ai.
  The user selects provider and model. Model identifiers are configuration backed by a
  per-provider model catalog. Nothing hardcodes a model name, and capabilities (context window,
  structured output, tool calling) are per model.
- All AI-dependent operations go through one gateway in `src/odooflux/ai/`, independent of the
  Odoo version-specific upgrade logic. It provides provider and model selection, API key
  configuration, configurable endpoints, provider-specific adapters, timeouts and retries, token
  and cost tracking where supported, explicit errors, and **no silent provider fallback**.
- AI stays off until explicitly enabled (ADR-012, spec 007 FR-001). Sending customer source code to
  a provider requires explicit authorization that names the provider and the data categories.
  Credentials, secrets, database dumps, and unrelated customer data are never sent. Source is
  minimised before sending. API keys and prompt content are not logged. The customer can disable
  external transmission. Without authorization, transmission is blocked, not redirected to another
  provider.

**Interpretation to confirm.** "External-first default" is read as the default provider type. AI
remains disabled until enabled, as spec 007 FR-001 requires. Confirm this reading before P6 starts.

**Scope split against spec 007 (P6).**

| Requirement | Status |
|---|---|
| Provider contract, registry, fake provider, bounded retries, budgets, cache, usage, redacted credentials, eligibility, validated edits | Already in 007 (T001–T028) |
| Anthropic adapter (007 T030) | Already in 007 |
| OpenAI-compatible adapter with configurable base URL (007 T031) | Already in 007; covers OpenAI GPT, DeepSeek, Z.ai, Ollama, and vLLM only if their endpoints are configured through it |
| Named provider list in 007 Clarifications ("Which providers ship in P6?") | **Changed by D-08**: add DeepSeek and Z.ai as first-class providers |
| Per-provider model catalog with capability metadata; no hardcoded models | **New**; needs a spec amendment before implementation |
| Per-provider data-category authorization and a transmission kill switch | **New** beyond 007 FR-001 consent flag; needs a spec amendment |
| No-silent-fallback enforcement, tested | **New test cases** in 007 scope |
| Provider-specific adapters beyond Anthropic and OpenAI-compatible (DeepSeek, Z.ai GLM) | **New feature** unless the OpenAI-compatible adapter proves sufficient for them |

Items marked "new" are not started. They belong to 007 as amendments, or to a separate Spec Kit
feature if the owner prefers. No phase has been expanded automatically.

**Consequences.** Live provider tests stay opt-in (ADR-016). The stdlib-only core rule (ADR-002)
still holds: provider SDKs remain optional adapters.

## ADR-018 — Feature 006 amendment: run parameters, DETECT_ONLY renamed-model/dependency/XPath rules

**Status:** Accepted (D-A1, D-A2, D-A4, D-A6, D-A7 approved by the project owner, 2026-11-07). D-A3 and D-A5 not approved for now.

**Decision.** `bind_rule(meta, modules, run_params=None)` is accepted; behaviour is unchanged for `None`, run params are validated against declared rule inputs, static/run key conflicts are a `BindingError`, missing required inputs skip the rule with an INFO gap (never silently). `*.manifest.version-prefix` is bound per run as DETECT_ONLY. The renamed-model family is DETECT_ONLY with review-required diagnostics. Removed-module records may carry optional `replaced_by`, only with authoritative evidence. A version-pinned view index and `tools/extract_view_index.py` are added; an unavailable index is never proof of XPath compatibility.

**Not approved.** Automatic version-prefix rewriting (D-A3) and automatic renamed-model transformation (D-A5) stay disabled until authoritative evidence, ambiguity analysis and golden tests show safe behaviour.

**Consequences.** All new migration rules are DETECT_ONLY unless a separate decision approves AUTO_TRANSFORM. The 52 existing rules keep their behaviour.

## ADR-019 — Framework-first delivery and non-blocking human review

**Status:** Accepted (project owner, 2026-11-07). Supersedes the "blocked behind human approval" treatment in [FRAMEWORK_COMPLETION_PLAN.md](FRAMEWORK_COMPLETION_PLAN.md) where they conflict. The plan's classification (framework / minimal corpus / Knowledge Base) and the KB backlog stay in force.

**Decision.**
1. Work items carry a *work state*, separate from the run/release statuses (`VERIFIED_SUCCESS` … `BLOCKED`), which are unchanged:
   `IMPLEMENTED` (technical work done) · `VERIFIED` (required automated checks passed) · `PENDING_HUMAN_REVIEW` (technical work and available automation done; human sign-off outstanding) · `BLOCKED_TECHNICAL` (a genuine technical dependency) · `DEFERRED_KB` (Knowledge Base expansion postponed, backlog ID required).
2. `PENDING_HUMAN_REVIEW` is not a failure, not an approval and not certification. Only a human can record approval, and only in the review register.
3. A human-gated task is split into a technical part (marked `[X]` when IMPLEMENTED and VERIFIED) and a certification part. The original task (T025, T035, T044, T059, 010 T023 and similar) stays unchecked, with a line "Certification: PENDING_HUMAN_REVIEW, register ID FHR-nnn". No agent marks an original human-review requirement satisfied.
4. Automated tests may use a **provisional validation corpus**: fixtures and expected outputs labelled `PROVISIONAL`, produced to test framework mechanics. They are never represented as approved migration truth. Every report, support statement and matrix entry that depends on them must say so.
5. `docs/reviews/FINAL_HUMAN_REVIEW_REGISTER.md` collects every pending human item. Agents write register fragments in `docs/reviews/fragments/`; the orchestrator consolidates them.
6. Production certification stays blocked while any mandatory register item is open. Framework implementation may be declared complete without it.

**Unchanged safeguards.** L3 dependency-integrity is mandatory (UNAVAILABLE blocks release readiness). D-08 AI authorization, kill switch and no-fallback rules. SC-005 (no automatic edits from `review_required` rules). All new rules stay DETECT_ONLY. No behavioural-equivalence claim when source-side validation is unavailable.

**Defaults assumed for the open plan decisions** (revisable; recorded in the register): validation path 17.0→18.0 (OD-2); 002 reconciled, not re-executed (OD-6); knowledge data packaged in the wheel (OD-5); version-prefix stays opt-in, REQ-MAN-002 wording change left to the owner (OD-4); only the provisional path is described as supported, with a provisional label (OD-7); Docker check on 18.0 runs once, source-side behavioural comparison reports UNAVAILABLE if no 17.0 image (OD-8).

**Consequences.** The work-state vocabulary lives in task notes and docs, not in code statuses, so no schema or status-model change is required.

## ADR-020 — Knowledge Acquisition Pipeline: releases, packages and offline-first knowledge

**Status:** PROPOSED (planning only; not approved by the project owner). Spec: `specs/011-knowledge-acquisition-pipeline/`. Open owner decisions OD-K1 to OD-K12 are listed in its research.md; the defaults below are recommendations, not decisions.

**Decision.**
1. A *knowledge release* is an immutable, complete knowledge tree plus `release.json`, identified by a sha256 digest (`kr-` + 12 hex). The packaged knowledge tree is the implicit *built-in release*; with no active release every layout, loader behaviour and output stays byte-identical.
2. Installed releases live in a kb-home directory outside the package (default XDG data dir, `ODOOFLUX_KB_HOME`), with an atomically written `active.json` pointer, rollback, and a hash-chained audit log. This extends ADR-009 (KB as JSON under `src/odooflux/knowledge/`); JSON remains the only record format. YAML and SQLite are rejected (SQLite only above a stated measured threshold).
3. The portable knowledge package is a deterministic ZIP (`.ofkp`) with a sha256 manifest, read through a hardened extractor (canonical relative paths, no links, no duplicates, size and ratio caps, staging then atomic move). Import recomputes gates locally; an imported package never enables an unverified FIX_ENABLED rule (default: refuse).
4. Knowledge acquisition is offline-first: pinned immutable revisions (SHA), content-addressed snapshots, structural diff extraction with full file accounting, a change ledger with stable ids and dispositions, deterministic data-driven candidate rules (always DETECT_ONLY or DRAFT), coverage with eight separately denominated metrics, and gates that block a "complete" claim. Only `source fetch --allow-network` may use the network. AI may only propose (D-08 grants, never evidence, never confirms renames).
5. `migrate` resolves the active release read-only, fails closed on a corrupt release, surfaces missing or partial transition coverage, never treats missing knowledge as success, and records release id and digest in the report through an optional additive `knowledge_release` field.

**Not decided here.** Automatic FIX_ENABLED, automatic rename confirmation (ADR-018 stays), package signing, hosted distribution. Certification of any built release stays `PENDING_HUMAN_REVIEW` (ADR-019).

**Points of tension with existing ADRs (for the owner).**
- ADR-009 places the KB under `src/odooflux/knowledge/`; installed releases live elsewhere (extension, needs owner confirmation).
- The report schema pins `schema_version` to `1.0.0` and REPORTING_AND_UX says it increments on breaking changes; the additive field needs a `1.1.0` value (OD-K4).
- Ten built-in FIX_ENABLED rules have no VERIFIED evidence today (0 of 200); the stricter KAP gate applies to releases only, built-in rules are grandfathered.
- ADR-002 is still "Proposed" while the constitution applies it; KAP relies on it.

**Open owner decisions (recommended defaults):** OD-K1 kb-home location and env var (`ODOOFLUX_KB_HOME`, XDG); OD-K2 package container (ZIP, DEFLATE); OD-K3 unverified FIX_ENABLED on import (refuse, opt-in downgrade); OD-K4 report schema bump (1.1.0 only when field present); OD-K5 package authenticity (digest pin only); OD-K6 Enterprise/OCA/OpenUpgrade scope (local inputs only, derived Enterprise data not exported); OD-K7 audit log reuse; OD-K8 named benchmark sets (golden corpus, synthetic); OD-K9 redaction module (`utils/redaction.py`); OD-K10 activating PARTIAL releases (allowed with warning); OD-K11 rule history sidecar and built-in dup checks opt-in; OD-K12 SQLite revisit threshold.

**Scope clarification (project owner message, KAP round): approval identity deferred.** Authenticated approver identity, identity verification, RBAC and human approval workflows are out of scope for the current release (backlog item FE-1 in `docs/planning/kap/FUTURE_ENHANCEMENTS.md`). The approval reference taken by `knowledge rule promote` is recorded metadata only and is not authenticated approval. No task, release activation or KAP completion is blocked on it. All technical gates (provenance verification, rule validation, conflict detection, FIX_ENABLED eligibility, package integrity) are unchanged. ADR-020 itself remains PROPOSED.
