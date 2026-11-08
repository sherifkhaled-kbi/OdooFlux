"""Regression tests for defects found by the failure-injection suite (TST-010-010, T021)."""

import errno
import unittest
from unittest import mock

from odooflux.core.jobs import promote as promote_mod
from odooflux.core.recovery.rollback import rollback
from odooflux.utils import atomic
from tests.integration.helpers import make_module, new_tmp, start_run, tree


class RestoreFailureTests(unittest.TestCase):
    def test_f_inj_1_failing_restore_blocks_the_module_and_rollback_finishes(self):
        """F-INJ-1: when a promotion fault is followed by a failing restore (the disk stays full), the OSError raised
        by the restore used to escape promote_module and crash the run instead of blocking the module. The module is
        now BLOCKED, the run log keeps every written file, and ``rollback`` restores the original bytes."""
        root = new_tmp()
        module = make_module(root, "kbi_demo")
        original = tree(module)
        calls = {"n": 0}

        def disk_full_from_second_write(path, data, *a, **kw):
            if str(path).startswith(str(module)):
                calls["n"] += 1
                if calls["n"] >= 2:  # the second promotion write and every restore write after it
                    raise OSError(errno.ENOSPC, "No space left on device")
            return atomic.atomic_write_bytes(path, data)

        with mock.patch.object(promote_mod, "atomic_write_bytes", side_effect=disk_full_from_second_write):
            run_id, state = start_run(root / "state", [module])
        entry = state["modules"][0]
        self.assertEqual(entry["status"], "BLOCKED")
        self.assertIn("run rollback", entry["report"]["block_reason"])
        rollback(root / "state", run_id)
        self.assertEqual(tree(module), original)


if __name__ == "__main__":
    unittest.main()
