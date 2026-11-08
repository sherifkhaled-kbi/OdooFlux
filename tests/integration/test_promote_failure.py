"""TST-003-031 (REQ-SAF-007): a promotion fault on file k restores files 1..k-1 and blocks the module."""

import unittest
from unittest import mock

from odooflux.core.jobs import promote as promote_mod
from odooflux.utils import atomic

from .helpers import make_module, new_tmp, start_run, tree

FAILURES = {"n": 0}


MODULE = {"root": ""}


def _fail_second_module_write(path, data, *args, **kwargs):
    # Count only writes into the customer module; staging into the workspace is a separate step.
    if str(path).startswith(MODULE["root"]):
        FAILURES["n"] += 1
        if FAILURES["n"] == 2:
            raise OSError("injected fault on file 2")
    return atomic.atomic_write_bytes(path, data)


class PromoteFailureTests(unittest.TestCase):
    def test_fault_on_file_k_restores_earlier_files_and_blocks(self):
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        original = tree(module)
        MODULE["root"] = str(module)
        FAILURES["n"] = 0
        with mock.patch.object(promote_mod, "atomic_write_bytes", side_effect=_fail_second_module_write):
            _run_id, state = start_run(root / "state", [module], backup=True)
        entry = state["modules"][0]
        self.assertEqual(entry["status"], "BLOCKED")
        self.assertIn("promotion failed", entry["report"]["block_reason"])
        self.assertEqual(tree(module), original, "files 1..k-1 must be back to their original bytes")


if __name__ == "__main__":
    unittest.main()
