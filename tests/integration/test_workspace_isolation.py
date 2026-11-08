"""TST-003-015 (REQ-SAF-007, FR-012): the source digest is unchanged until promotion."""

import unittest
from unittest import mock
from pathlib import Path

from odooflux.core.jobs import promote as promote_mod
from odooflux.core.orchestrator import run as run_mod
from odooflux.utils.hashing import digest_tree

from .helpers import make_module, new_tmp, start_run


class WorkspaceIsolationTests(unittest.TestCase):
    def test_source_digest_unchanged_while_staging_and_changed_after_promotion(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        before = digest_tree(module)
        samples = []
        real_stage = promote_mod.stage_edits

        def sampled_stage(work_root, module_path, edits):
            samples.append(("before-stage", digest_tree(Path(module_path)) == before))
            real_stage(work_root, module_path, edits)
            samples.append(("after-stage", digest_tree(Path(module_path)) == before))

        with mock.patch.object(run_mod, "stage_edits", side_effect=sampled_stage):
            start_run(root / "state", [module])
        self.assertEqual(samples, [("before-stage", True), ("after-stage", True)])
        self.assertNotEqual(digest_tree(module), before)  # promotion happened after validation


if __name__ == "__main__":
    unittest.main()
