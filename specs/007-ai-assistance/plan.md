# Implementation Plan: Optional, Provider-Neutral AI Assistance

**Branch**: `007-ai-assistance` | **Date**: 2026-11-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-ai-assistance/spec.md`

## Summary

Add an optional AI subsystem that escalates only AI-eligible findings without deterministic fixes, sends minimal regions with evidence excerpts, converts responses into validated `Edit`s, enforces token budgets, caches verified results, and reports usage. Providers are adapters behind a neutral contract; the core stays stdlib-only. Design detail: [AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md](../../docs/planning/AI_ARCHITECTURE_AND_TOKEN_OPTIMIZATION.md).

**D-08 amendment (ADR-017)**: external-default, provider-agnostic gateway (`gateway.py`) with explicit data-category authorization, kill switch, per-provider model catalog (configuration), and no silent fallback. DeepSeek and Z.ai GLM first reuse `openai_compatible.py` (configured base URL); dedicated adapters only if conformance tests show gaps. Prerequisites: P3 research complete, 006 done, 008 T029; 007 must not start earlier.

## Technical Context

**Language/Version**: Python ≥3.10 (constitution Technical Constraints)
**Primary Dependencies**: stdlib only (`urllib.request`, `json`, `hashlib`); optional provider SDK adapters (extras) — not required
**Storage**: AI cache and usage files under the run state directory (`$XDG_CACHE_HOME/odooflux/ai-cache/`, ADR-013)
**Testing**: `unittest`; network contract tests opt-in via `ODOOFLUX_AI_TESTS=1`
**Target Platform**: Linux, macOS, Windows (CLI)
**Project Type**: CLI / library
**Performance Goals**: AI step adds no provider calls when disabled; cache lookup O(1) per region
**Constraints**: budgets enforced before send; no whole-file prompts; credentials never persisted
**Scale/Scope**: up to 300 modules per job (REQ-PRF-001); AI requests bounded by job budget

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| I Dependency-light core | PASS | Core uses `AIProvider` contract only; SDKs optional adapters |
| II Safe, reversible | PASS | AI edits go through workspace, validation, promotion like deterministic edits |
| III Deterministic first, validated AI | PASS | FR-003, FR-006, FR-013; D-08 FR-017, FR-019, FR-020 |
| IV Honest reporting | PASS | Rejections with reason codes; usage and cost reported; `FIXED` only by re-scan |
| V Tests | PASS | Contract tests, scripted fake provider, benchmarks |
| VI Official evidence | PASS | AI cannot create rules; evidence excerpts included in prompts (FR-013) |
| VII Layered validation | PASS | L1/L2 + protected identifiers before keeping |
| VIII Business logic | PASS | `review_required` rules keep result capped at `NEEDS_REVIEW` even when AI patch is accepted |
| IX Extensible | PASS | Provider registry with contract version |
| X Phased delivery | PASS | Entry requires P3, P5; D-08 decided |

## Project Structure

### Documentation (this feature)

```text
specs/007-ai-assistance/
├── plan.md, spec.md, research.md, data-model.md, quickstart.md, tasks.md
├── checklists/requirements.md
└── contracts/ai-provider.md, contracts/budget-and-cache.md
```

### Source Code (repository root)

```text
src/odooflux/ai/
├── providers/      fake.py, anthropic.py, openai_compatible.py (local, OpenAI, DeepSeek, Z.ai reuse it), registry.py, catalog.py (D-08)
├── gateway.py      (D-08) single entry: selection, authorization check, kill switch, timeouts, retries, no fallback
├── authorization.py (D-08) provider + data-category grants, minimisation, sensitive-content exclusion
├── catalog/        (D-08) per-provider model catalog config (JSON; no hardcoded models/prices)
├── prompts/        templates (versioned), builder.py (region selection, evidence excerpt)
├── caching/        cache.py (key derivation, store under state dir)
├── usage/          budgets.py, usage.py (accounting, cost from configured pricing)
└── escalation.py   eligibility, request lifecycle, response → Edit, protected-identifier check
tests/unit/ai/, tests/contract/ai/, tests/integration/ai/, tests/benchmarks/ai/
```

**Structure Decision**: matches [PROJECT_STRUCTURE.md](../../docs/planning/PROJECT_STRUCTURE.md) `ai/*` rows; `escalation.py` is the single integration point called by `core/engine`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Optional provider SDK adapters | Some providers' features (streaming, native caching) are only exposed via SDKs | stdlib transport is the default; SDK adapters are opt-in extras, never imported by core |
