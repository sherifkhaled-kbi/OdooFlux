"""P0 User Story 3 and FR-003/004/005/006: state dir, backups, atomic writes, run log."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odooflux.core.jobs import promote as promote_mod
from odooflux.utils import atomic as atomic_mod
from odooflux.utils.atomic import atomic_write_text

from tests._support.p0 import FIXTURE, make_addons, only_run, read_runlog, run_cli, run_main, tree_digest


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Addons root is a sibling of the state dir: a state dir inside a scanned addons root is refused.
        self.addons = make_addons(self.tmp / "addons")
        self.module = self.addons / "kbi_demo"
        self.state = self.tmp / "state"

    def tearDown(self):
        self._tmp.cleanup()


class StateDirTests(_TmpCase):
    def test_state_dir_inside_scanned_path_refused(self):
        """TST-001-001 (REQ-SAF-003): a state dir inside a scanned module is refused, exit 4."""
        before = tree_digest(self.module)
        state_inside = self.module / ".odooflux_state"
        code, out = run_cli(["--module", self.module, "--from-version", "14", "--fix",
                             "--no-color", "--state-dir", state_inside])
        self.assertEqual(code, 4, out)
        self.assertFalse(state_inside.exists())
        self.assertEqual(tree_digest(self.module), before)


class AtomicWriteTests(_TmpCase):
    def test_atomic_write_interrupted(self):
        """TST-001-002 (REQ-SAF-005, F-SAFE-4): a failure before os.replace leaves the original
        content and no temporary file."""
        target = self.module / "models" / "demo.py"
        original = target.read_bytes()
        with mock.patch("os.replace", side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                atomic_write_text(target, "print('new')\n", "utf-8")
        self.assertEqual(target.read_bytes(), original)
        leftovers = [p.name for p in target.parent.iterdir() if p.name != "demo.py"]
        self.assertEqual(leftovers, [], "temporary file was not cleaned up")


class BackupTests(_TmpCase):
    def test_backup_outside_addons_path(self):
        """TST-001-017 (F-SAFE-2): the backup lives under the state dir, never in the addons path."""
        code, out = run_cli(["--addons-path", self.addons, "--from-version", "14", "--fix",
                             "--backup", "--no-color", "--state-dir", self.state])
        self.assertEqual(sorted(p.name for p in self.addons.iterdir()), ["kbi_demo"], out)
        backup = only_run(self.state) / "backup" / "kbi_demo"
        self.assertTrue((backup / "__openerp__.py").exists())
        # SC-003 / T027: a re-scan of the addons path finds only the original module
        rescan_code, rescan_out = run_cli(["--addons-path", self.addons, "--from-version", "14",
                                           "--no-color", "--state-dir", self.tmp / "s2"])
        self.assertIn("kbi_demo", rescan_out)
        self.assertNotIn("_backup_", rescan_out)

    def test_backup_verified(self):
        """TST-001-018 (FR-003, F-SAFE-3): the backup manifest is verified and matches the backup on disk."""
        run_cli(["--module", self.module, "--from-version", "14", "--fix",
                 "--no-color", "--state-dir", self.state])
        run = only_run(self.state)
        manifest = json.loads((run / "backup" / "kbi_demo.manifest.json").read_text("utf-8"))
        self.assertTrue(manifest["verified"])
        listed = sorted((f["rel_path"], f["sha256"]) for f in manifest["files"])
        self.assertEqual(listed, tree_digest(run / "backup" / "kbi_demo"))
        # The manifest lists exactly the pre-fix content of the module
        original = sorted((rel, hashlib.sha256((FIXTURE / rel).read_bytes()).hexdigest())
                          for rel, _ in listed)
        self.assertEqual(listed, original)
        events = [e["event"] for e in read_runlog(self.state)]
        self.assertIn("backup_verified", events)

    def test_backup_failure_blocks_module(self):
        """TST-001-019 (REQ-SAF-004, FR-004): a failed backup blocks every write in the module."""
        before = tree_digest(self.module)
        with mock.patch("shutil.copytree", side_effect=OSError("disk full")):
            code, out = run_main(["--module", self.module, "--from-version", "14", "--fix",
                                  "--no-color", "--state-dir", self.state])
        self.assertEqual(code, 4, out)
        self.assertEqual(tree_digest(self.module), before)
        self.assertIn("BLOCKED", out)
        events = [e["event"] for e in read_runlog(self.state)]
        self.assertIn("backup_failed", events)


class RunLogTests(_TmpCase):
    def test_run_log_lists_written_files(self):
        """TST-001-003 (REQ-SAF-006): file_written entries equal the changed files; hashes match disk."""
        before = {rel: sha for rel, sha in tree_digest(self.module)}
        run_cli(["--module", self.module, "--from-version", "14", "--fix",
                 "--no-color", "--state-dir", self.state])
        after = {rel: sha for rel, sha in tree_digest(self.module)}
        changed = {rel for rel in after if before.get(rel) != after[rel]}
        written = [e for e in read_runlog(self.state) if e["event"] == "file_written"]
        self.assertEqual({Path(e["path"]).relative_to(self.module).as_posix() for e in written},
                         changed)
        for entry in written:
            rel = Path(entry["path"]).relative_to(self.module).as_posix()
            self.assertEqual(entry["sha256_after"], after[rel])
            # A rename (__openerp__.py -> __manifest__.py) has no pre-run hash under the new name;
            # its sha256_before is the hash of the source file it came from.
            self.assertIn(entry["sha256_before"], set(before.values()))
            self.assertTrue(entry["reversible"])




FIXTURE_MODULE_ROOT = [None]


class WriteFailureTests(_TmpCase):
    """SC-006 / spec edge case: a write that fails part-way leaves no mixed module."""

    def setUp(self):
        super().setUp()
        FIXTURE_MODULE_ROOT[0] = self.module

    @staticmethod
    def _fail_second_write():
        real = atomic_mod.atomic_write_bytes
        calls = {"n": 0}

        def flaky(path, data, *args, **kwargs):
            # Count only writes into the customer module: staging into the workspace is separate.
            if str(path).startswith(str(FIXTURE_MODULE_ROOT[0])):
                calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated disk full")
            return real(path, data)

        return flaky

    def test_write_failure_restores_module_from_backup(self):
        """With a verified backup the touched files are restored; the module is BLOCKED (exit 4)."""
        before = tree_digest(self.module)
        with mock.patch.object(promote_mod, "atomic_write_bytes", side_effect=self._fail_second_write()):
            code, out = run_main(["--module", self.module, "--from-version", "14", "--fix",
                                  "--no-color", "--state-dir", self.state])
        self.assertEqual(code, 4, out)
        self.assertIn("BLOCKED", out)
        self.assertEqual(tree_digest(self.module), before, "module must be back to its original state")
        self.assertIn("module_blocked", [e["event"] for e in read_runlog(self.state)])

    def test_write_failure_without_backup_reports_partial_state(self):
        """--no-backup cannot restore; the report says so and lists written and unwritten files."""
        with mock.patch.object(promote_mod, "atomic_write_bytes", side_effect=self._fail_second_write()):
            code, out = run_main(["--module", self.module, "--from-version", "14", "--fix",
                                  "--no-backup", "--no-color", "--state-dir", self.state])
        self.assertEqual(code, 4, out)
        self.assertIn("NOT restored", out)
        self.assertIn("Unwritten", out)


if __name__ == "__main__":
    unittest.main()
