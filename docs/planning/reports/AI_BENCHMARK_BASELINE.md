# AI benchmark baseline (feature 007, T032, TST-007-016)

**What this is.** A baseline of the AI pipeline's mechanics measured with the **scripted fake provider** on a
**PROVISIONAL** synthetic fixture corpus (ADR-019 item 4). It is **not** a measure of any real model's quality, cost or
latency. No real provider was called: this environment has no network and no keys. The real-provider part of T032
("and (opt-in) one real provider") is **not run**; see `docs/reviews/fragments/ws-c-human-review.md` item AI-1.

**Reproduce.** `PYTHONPATH=src python3 -m tests.benchmarks.ai.run_benchmark --markdown` (JSON without the flag). The run
is deterministic; `tests/benchmarks/ai/test_benchmark.py` runs it in the default suite.

**Corpus.** `tests/fixtures/ai/corpus/benchmark.json`: seven single-finding scenarios over two sample files, each with a
scripted fake answer: accepted, model declined, extra definition (out of region), syntax error, truncated, protected
identifier renamed, finding not resolved. One scenario has a known-good expected output (correctness is measured only
there). The rules are test-only (`tests/unit/ai/_helpers.py`); no Knowledge Base rule is used, and the shipped
knowledge base currently has no rule with `ai_eligible = true`.

## Baseline

| Metric | Definition | Fake-provider baseline |
|---|---|---|
| Acceptance rate | accepted edits / provider requests | 14.3 % (1 of 7) |
| Correctness rate | accepted edits equal to the expected output / accepted | 100 % (1 of 1) |
| Rejection by reason | count per reason | `finding_unresolved` 1, `out_of_region` 1, `protected_identifier_changed` 1, `syntax_invalid` 1, `truncated` 1; plus `skipped:model_declined` 1 |
| Tokens per accepted edit | (input + output) / accepted, scripted usage | 1050 (scripted, not measured) |
| Calls per escalated finding | provider attempts / escalated findings | 1.00 |
| Cache effectiveness | cache hits / fixed findings on a second pass over unchanged input | 100 % (1 of 1) |
| Cost per accepted edit | configured pricing x usage / accepted | not computed: no pricing configured (null) |
| Latency (median) | request duration | not measured: the fake answers in-process |

## How to read it

- The acceptance and rejection numbers prove that every scripted failure mode is caught with its documented reason and
  that exactly one valid edit passes. They do not predict real acceptance rates.
- Tokens come from the script, so the 1050 figure is a placeholder shape, not a budget input.
- **No target is set from this baseline.** Targets and default budgets need a real-provider run on a representative
  corpus and owner approval (spec Clarifications, SC-005); until then the job budget stays mandatory and has no default.
- Quality rule (AI_ARCHITECTURE section 5): a configuration change that lowers tokens is accepted only if the correctness
  rate does not drop on the corpus. With the fake provider this is vacuous; it applies once a real run exists.

## Not run

| Item | Status |
|---|---|
| Real-provider benchmark (any provider) | not run: no network, no keys, no owner-chosen model id |
| Latency and cost per accepted edit | not measured |
| Budget defaults and targets | not set |
