"""TST-007-016 (REQ-AI-005, REQ-AI-006): benchmark harness for AI assistance (docs/planning/AI_ARCHITECTURE... section 5).

Default mode runs the committed AI fixture corpus against the scripted FAKE provider. The numbers describe the
framework (eligibility, response checks, validation, re-scan, cache, accounting), not the quality of any model.
A real-provider run is opt-in (``--live PROVIDER``, needs ODOOFLUX_AI_TESTS=1, a key and a catalog model id) and was
not run when this baseline was recorded.

    PYTHONPATH=src python3 -m tests.benchmarks.ai.run_benchmark [--markdown]
"""

import json
import statistics
import sys
import tempfile
from pathlib import Path

from tests.unit.ai import _helpers as h
from odooflux.ai.caching.cache import ResultCache
from odooflux.ai.escalation import Escalator
from odooflux.ai.providers.fake import FakeProvider
from odooflux.ai.providers.types import ModelDescriptor
from odooflux.ai.usage.usage import UsageLedger

CORPUS = h.FIXTURES / "corpus" / "benchmark.json"


def load_corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def _focused(text: str, focus: str) -> list:
    """Findings inside the function (or on the line) that contains ``focus``: one scenario, one finding."""
    lines = text.splitlines()
    at = next(i for i, ln in enumerate(lines, 1) if focus in ln)
    return [f for f in h.toy_findings("m.py", text) if at <= f.line <= at + 1]


def _escalator(provider, ledger, cache):
    return Escalator(provider.complete, provider="fake", model="fake-model", step="bench", validate=h.python_validate,
                     rescan=h.toy_rescan, ledger=ledger, cache=cache)


def run_scenarios(cache_root: Path) -> dict:
    corpus = load_corpus()
    ledger = UsageLedger()
    cache = ResultCache(cache_root)
    outcomes, accepted_edits, expected_hits, escalated = [], [], 0, 0
    for sc in corpus["scenarios"]:
        text = h.corpus(sc["file"])
        provider = FakeProvider(h.script(sc["script"][:-5]), models=[ModelDescriptor("fake", "fake-model")])
        findings = _focused(text, sc["focus"])
        result = _escalator(provider, ledger, cache).escalate_file(sc["id"], "m.py", text, findings, h.TOY_METAS)
        escalated += len(result.outcomes)
        outcomes.extend((sc["id"], o) for o in result.outcomes)
        for edit in result.edits:
            accepted_edits.append(edit)
            want = next((v for k, v in sc["expected"].items() if k in edit.before), None)
            expected_hits += int(want is not None and edit.after == want)
    summary = ledger.summary()
    requests = summary["requests"]
    accepted = summary["outcomes"].get("accepted", 0)
    return {
        "scenarios": len(corpus["scenarios"]),
        "eligible_findings_escalated": escalated,
        "provider_requests": requests,
        "accepted": accepted,
        "acceptance_rate": (accepted / requests) if requests else None,
        "correctness_rate": (expected_hits / accepted) if accepted else None,
        "rejection_by_reason": summary["rejections"],
        "other_outcomes": {k: v for k, v in summary["outcomes"].items() if not k.startswith("rejected:")},
        "tokens_per_accepted_edit": ((summary["totals"]["input_tokens"] + summary["totals"]["output_tokens"]) / accepted)
        if accepted else None,
        "calls_per_finding": (summary["attempts"] / escalated) if escalated else None,
        "cost_per_accepted_edit": None,
        "cost_note": "pricing not configured (fake provider)",
        "latency_median_ms": None,
        "latency_note": "not measured: the fake provider answers in-process",
        "totals": summary["totals"],
    }


def run_second_pass(cache_root: Path) -> dict:
    """Cache effectiveness: re-run the accepted scenario on unchanged input with the populated cache."""
    text = h.corpus("sample_models.py.txt")
    sc = load_corpus()["scenarios"][0]
    provider = FakeProvider(h.script("mixed"), models=[ModelDescriptor("fake", "fake-model")])
    cache = ResultCache(cache_root)
    ledger = UsageLedger()
    result = _escalator(provider, ledger, cache).escalate_file(
        sc["id"], "m.py", text, _focused(text, sc["focus"]), h.TOY_METAS)
    fixed = [o for o in result.outcomes if o.status == "FIXED"]
    hits = sum(1 for o in result.outcomes if o.outcome == "cache_hit")
    return {"eligible_fixed_on_first_pass": len(fixed), "cache_hits": hits,
            "provider_calls_second_pass_for_cached_findings": 0 if hits == len(fixed) else None,
            "cache_effectiveness": (hits / len(fixed)) if fixed else None}


def run_benchmark() -> dict:
    root = Path(tempfile.mkdtemp(prefix="odooflux-ai-bench-")) / "ai-cache"
    first = run_scenarios(root)
    second = run_second_pass(root)
    return {"provider": "fake (scripted)", "corpus": "PROVISIONAL synthetic fixtures", "first_pass": first,
            "second_pass": second, "live": "not run"}


def to_markdown(result: dict) -> str:
    f, s = result["first_pass"], result["second_pass"]

    def pct(x):
        return "n/a" if x is None else f"{x * 100:.1f} %"
    rows = [
        ("Acceptance rate (accepted / provider requests)", pct(f["acceptance_rate"])),
        ("Correctness rate (accepted equal to expected / accepted)", pct(f["correctness_rate"])),
        ("Rejection by reason", ", ".join(f"{k}: {v}" for k, v in sorted(f["rejection_by_reason"].items())) or "none"),
        ("Other outcomes", ", ".join(f"{k}: {v}" for k, v in sorted(f["other_outcomes"].items())) or "none"),
        ("Tokens per accepted edit", "n/a" if f["tokens_per_accepted_edit"] is None
         else f"{f['tokens_per_accepted_edit']:.1f}"),
        ("Calls per escalated finding", "n/a" if f["calls_per_finding"] is None else f"{f['calls_per_finding']:.2f}"),
        ("Cache effectiveness (hits / fixed findings, second pass)", pct(s["cache_effectiveness"])),
        ("Cost per accepted edit", f["cost_note"]),
        ("Latency (median)", f["latency_note"]),
    ]
    return "\n".join(["| Metric | Fake-provider baseline |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--live" in argv:
        print("live benchmark: not implemented in this baseline; run ODOOFLUX_AI_TESTS=1 contract tests instead",
              file=sys.stderr)
        return 2
    result = run_benchmark()
    print(to_markdown(result) if "--markdown" in argv else json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
