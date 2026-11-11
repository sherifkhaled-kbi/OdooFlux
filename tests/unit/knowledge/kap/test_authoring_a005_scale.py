"""RC performance fix: authoring check A005 groups rules instead of comparing every pair.

Rule creation validates the whole tree twice per rule, and A005 compared every pair of active rules, building a JSON
key for each side of each pair (235k pair visits at 830 rules; millions at the 3.3k rules of a real pair). Rules that
can collide share step, detector and selector, so they are grouped once and only pairs inside a group are visited.
The findings, and their order, are exactly those of the all-pairs version (kept below as the reference).
"""

import random
import unittest
from unittest import mock

from odooflux.knowledge.authoring import checks as ac


def reference_a005(active, a002_pairs):
    out = []
    for second in range(len(active)):
        for first in range(second):
            a, b = active[first], active[second]
            if (first, second) in a002_pairs or not a.get("detector_ref"):
                continue
            if a.get("step") != b.get("step") or a.get("detector_ref") != b.get("detector_ref"):
                continue
            if ac._params_key(ac.selector_params(a.get("params"))) != ac._params_key(ac.selector_params(b.get("params"))):
                continue
            if not ac._overlap(a, b):
                continue
            both_fix = a.get("maturity") == ac.FIX_ENABLED and b.get("maturity") == ac.FIX_ENABLED
            out.append(ac._error("A005", b["id"], f"{b['id']} and {a['id']} match the same selector and may edit the same "
                                 f"files (same step and detector)", "ERROR" if both_fix else "WARNING"))
    return out


def random_rules(seed, n):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        rows.append({"id": f"s{rng.randint(1, 2)}.r{i}", "step": f"s{rng.randint(1, 2)}",
                     "detector_ref": rng.choice([None, "m:d1", "m:d2", "m:d3"]),
                     "params": {"model": rng.choice(["a", "b", "c"]), "field": rng.choice(["x", "y"]),
                                "new": rng.choice(["p", "q"])},
                     "file_kinds": rng.choice([None, [], ["py"], ["xml"], ["py", "xml"]]),
                     "maturity": rng.choice(["DETECT_ONLY", "FIX_ENABLED", "DRAFT"])})
    return rows


class A005Tests(unittest.TestCase):
    def test_findings_and_order_equal_the_all_pairs_version(self):
        compared = 0
        for seed in range(60):
            active = random_rules(seed, random.Random(seed).randint(2, 60))
            pairs = ac._a002_pairs(active)
            got = [(f.code, f.pointer, f.message, f.severity) for f in ac._a005(active, pairs)]
            want = [(f.code, f.pointer, f.message, f.severity) for f in reference_a005(active, pairs)]
            self.assertEqual(got, want, f"seed {seed}")
            compared += len(want)
        self.assertGreater(compared, 200)  # the generator really produces collisions

    def test_work_is_linear_in_the_number_of_rules_when_nothing_collides(self):
        active = [{"id": f"s1.r{i}", "step": "s1", "detector_ref": "m:d", "params": {"model": f"m{i}"},
                   "maturity": "DETECT_ONLY"} for i in range(2000)]
        calls = []
        real = ac._params_key
        with mock.patch.object(ac, "_params_key", lambda p: calls.append(1) or real(p)):
            self.assertEqual(ac._a005(active, ac._a002_pairs(active)), [])
        self.assertLess(len(calls), 3 * len(active))


if __name__ == "__main__":
    unittest.main()
