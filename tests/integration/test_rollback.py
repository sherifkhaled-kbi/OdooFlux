"""TST-003-032 and TST-003-033 (REQ-SAF-008): rollback restores byte-identical originals; a changed
file is skipped with a conflict and kept as the user left it."""

import unittest
from pathlib import Path

from odooflux.core.recovery.rollback import rollback

from .helpers import make_module, new_tmp, start_run, tree


class RollbackTests(unittest.TestCase):
    def test_rollback_restores_bytes(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        original = tree(module)
        run_id, _state = start_run(root / "state", [module])
        self.assertNotEqual(tree(module), original)
        results = rollback(root / "state", run_id)
        self.assertTrue(any(action == "restored" for _p, action, _d in results))
        self.assertEqual(tree(module), original)

    def test_changed_file_is_skipped_as_conflict(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        run_id, _state = start_run(root / "state", [module])
        edited = module / "models" / "demo.py"
        edited.write_text("# the user changed this after the run\n", encoding="utf-8")
        results = rollback(root / "state", run_id)
        conflicts = [p for p, action, _d in results if action == "conflict"]
        self.assertEqual(conflicts, [str(edited)])
        self.assertEqual(edited.read_text(encoding="utf-8"), "# the user changed this after the run\n")
        self.assertTrue((module / "views" / "demo_views.xml").read_text(encoding="utf-8").startswith("<?xml"))


if __name__ == "__main__":
    unittest.main()
