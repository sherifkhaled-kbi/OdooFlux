"""TST-007-013 (REQ-AI-007, FR-009, SC-003): unchanged input -> zero provider calls; cached edits are re-validated."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.unit.ai import _helpers as h
from odooflux.ai.caching.cache import ResultCache, cache_key
from odooflux.ai.escalation import Escalator
from odooflux.ai.providers.fake import FakeProvider
from odooflux.ai.providers.types import ModelDescriptor
from odooflux.ai.usage.usage import UsageLedger

TEXT = "class A:\n    def f_ok(self):\n        return old_api(1)\n"
SCRIPT = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
    "replacement": "    def f_ok(self):\n        return new_api(1)\n", "notes": "", "cannot_fix": False,
    "usage": {"input": 50, "output": 10}}}]}


def make(cache, ledger=None, script=SCRIPT, validate=h.python_validate):
    p = FakeProvider(script, models=[ModelDescriptor("fake", "fake-model")])
    esc = Escalator(p.complete, provider="fake", model="fake-model", step="s", validate=validate,
                    rescan=h.toy_rescan, cache=cache, ledger=ledger)
    return p, esc


def run(esc, text=TEXT):
    return esc.escalate_file("mod", "m.py", text, h.toy_findings("m.py", text), h.TOY_METAS)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "ai-cache"

    def test_second_run_makes_zero_calls_and_revalidates(self):
        cache = ResultCache(self.root)
        p1, esc1 = make(cache)
        r1 = run(esc1)
        self.assertEqual((len(p1.requests), cache.stats["hits"]), (1, 0))
        validated = []
        p2, esc2 = make(ResultCache(self.root), validate=lambda path, t: (validated.append(t), None)[1])
        r2 = run(esc2)
        self.assertEqual(len(p2.requests), 0)  # provider_calls == 0
        self.assertEqual(esc2.cache.stats["hits"], 1)  # cache_hits > 0
        self.assertEqual(r2.text, r1.text)
        self.assertEqual(r2.outcomes[0].outcome, "cache_hit")
        self.assertEqual(r2.outcomes[0].status, "FIXED")
        self.assertTrue(validated)  # the cached edit went through validation again

    def test_tampered_entry_is_rejected_and_deleted(self):
        cache = ResultCache(self.root)
        run(make(cache)[1])
        files = list(self.root.rglob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text())
        data["replacement"] = "    def f_ok(self):\n        return evil()\n"
        files[0].write_text(json.dumps(data))
        p, esc = make(ResultCache(self.root))
        r = run(esc)
        self.assertEqual(esc.cache.stats["tampered"], 1)
        self.assertEqual(len(p.requests), 1)  # fell back to the provider within budget
        self.assertNotIn("evil", r.text)

    def test_entry_failing_revalidation_is_deleted(self):
        cache = ResultCache(self.root)
        run(make(cache)[1])
        calls = {"n": 0}

        def validate(path, text):
            calls["n"] += 1
            return ("python-syntax", "forced") if calls["n"] == 1 else None
        p, esc = make(ResultCache(self.root), validate=validate)
        run(esc)
        self.assertEqual(esc.cache.stats["revalidation_failed"], 1)
        self.assertEqual(len(p.requests), 1)  # re-requested after the cached edit failed validation

    def test_key_contract(self):
        k1 = cache_key("region", "r", "p", "m", "v1", ["EV-2", "EV-1"], "step")
        k2 = cache_key("region", "r", "p", "m", "v1", ["EV-1", "EV-2"], "step")
        self.assertEqual(k1, k2)  # evidence ids are sorted
        for changed in (("region2", "r", "p", "m", "v1", ["EV-1", "EV-2"], "step"),
                        ("region", "r2", "p", "m", "v1", ["EV-1", "EV-2"], "step"),
                        ("region", "r", "p2", "m", "v1", ["EV-1", "EV-2"], "step"),
                        ("region", "r", "p", "m2", "v1", ["EV-1", "EV-2"], "step"),
                        ("region", "r", "p", "m", "v2", ["EV-1", "EV-2"], "step"),
                        ("region", "r", "p", "m", "v1", ["EV-1"], "step"),
                        ("region", "r", "p", "m", "v1", ["EV-1", "EV-2"], "step2")):
            self.assertNotEqual(cache_key(*changed), k1)
        self.assertEqual(len(k1), 64)

    def test_layout_and_content_hold_no_credentials(self):
        cache = ResultCache(self.root)
        run(make(cache)[1])
        (path,) = list(self.root.rglob("*.json"))
        self.assertEqual(path.parent.name, path.stem[:2])
        self.assertEqual(sorted(json.loads(path.read_text())),
                         ["created_at", "prompt_version", "replacement", "validation_digest"])

    def test_disabled_cache_reads_and_writes_nothing_and_clear_deletes(self):
        off = ResultCache(self.root, enabled=False)
        run(make(off)[1])
        self.assertFalse(self.root.exists())
        on = ResultCache(self.root)
        run(make(on)[1])
        self.assertTrue(self.root.exists())
        on.clear()
        self.assertFalse(self.root.exists())

    def test_cache_hit_is_recorded_in_the_ledger(self):
        cache = ResultCache(self.root)
        run(make(cache)[1])
        ledger = UsageLedger()
        run(make(ResultCache(self.root), ledger=ledger)[1])
        s = ledger.summary()
        self.assertEqual((s["cache_hits"], s["provider_calls"]), (1, 0))

    def test_rejected_edits_are_never_cached(self):
        bad = {"entries": [{"match": {"contains": "def f_ok"}, "response": {
            "replacement": "    def f_ok(self):\n        return old_api(1)  # still\n", "notes": "", "cannot_fix": False}}]}
        cache = ResultCache(self.root)
        run(make(cache, script=bad)[1])
        self.assertEqual(list(self.root.rglob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
