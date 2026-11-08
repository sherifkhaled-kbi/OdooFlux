"""TST-004-011 (SC-006): full knowledge validation completes in under 5 seconds (opt-in benchmark)."""

import os
import time
import unittest

from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.loader import KNOWLEDGE_ROOT, load_knowledge


@unittest.skipUnless(os.environ.get("ODOOFLUX_BENCH") == "1", "set ODOOFLUX_BENCH=1 to run")
class KnowledgeValidatePerfTests(unittest.TestCase):
    def test_full_validation_under_five_seconds(self):
        start = time.perf_counter()
        validate_knowledge(load_knowledge(KNOWLEDGE_ROOT))
        self.assertLess(time.perf_counter() - start, 5.0)


if __name__ == "__main__":
    unittest.main()
