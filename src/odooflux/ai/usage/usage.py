"""Usage accounting and cost from configured pricing (REQ-AI-006, FR-008, SC-004).

``Usage.input`` counts non-cached input tokens and ``Usage.cached`` counts tokens served from a provider cache; the
adapters normalise to that. Cost is computed here from catalog pricing, never taken from a provider, and is None
when pricing is absent or incomplete.
"""

from collections import Counter

NO_PRICING_LABEL = "pricing not configured"


def compute_cost(usage, pricing):
    """Cost in the catalog's currency unit, or None when pricing is absent or lacks input/output prices."""
    if not pricing:
        return None
    inp, out = pricing.get("input_per_mtok"), pricing.get("output_per_mtok")
    if not isinstance(inp, (int, float)) or not isinstance(out, (int, float)):
        return None
    cached_price = pricing.get("cached_per_mtok")
    if not isinstance(cached_price, (int, float)):
        cached_price = inp
    return (usage.input * inp + usage.output * out + usage.cached * cached_price) / 1_000_000


def _blank():
    return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost": 0.0, "unpriced": 0}


class UsageLedger:
    def __init__(self):
        self.records: list = []
        self.budget_events: list = []

    def record(self, rec) -> None:
        self.records.append(rec)

    @staticmethod
    def _sent(rec) -> bool:
        return rec.attempts > 0  # cache hits, budget skips and gateway blocks never reached an adapter (0 attempts)

    def summary(self) -> dict:
        sent = [r for r in self.records if self._sent(r)]
        by_model, by_module = {}, {}
        totals = _blank()
        for r in sent:
            for table, key in ((by_model, f"{r.provider}/{r.model}"), (by_module, r.module)):
                row = table.setdefault(key, _blank())
                self._add(row, r)
            self._add(totals, r)
        rejections = Counter(r.outcome.split(":", 1)[1] for r in self.records if r.outcome.startswith("rejected:"))
        out = {
            "requests": len(sent),
            "attempts": sum(r.attempts for r in sent),
            "provider_calls": len(sent),
            "cache_hits": sum(1 for r in self.records if r.outcome == "cache_hit"),
            "totals": self._finish(totals, sent),
            "by_model": {k: self._finish(v) for k, v in sorted(by_model.items())},
            "by_module": {k: self._finish(v) for k, v in sorted(by_module.items())},
            "outcomes": dict(Counter(r.outcome for r in self.records)),
            "rejections": dict(rejections),
            "budget_events": list(self.budget_events),
        }
        return out

    @staticmethod
    def _add(row, r) -> None:
        row["requests"] += 1
        row["input_tokens"] += r.input_tokens
        row["output_tokens"] += r.output_tokens
        row["cached_tokens"] += r.cached_tokens
        if r.cost is None:
            row["unpriced"] += 1
        else:
            row["cost"] += r.cost
        row["estimated"] = row.get("estimated", False) or r.estimated

    @staticmethod
    def _finish(row, sent=None) -> dict:
        unpriced = row.pop("unpriced")
        cost = row.pop("cost")
        row.setdefault("estimated", False)
        if unpriced or (sent is not None and not sent):
            row["cost"] = None
            if unpriced:
                row["cost_label"] = NO_PRICING_LABEL
        else:
            row["cost"] = cost
        return row
