"""TST-010-010 (T020; REQ-SAF-005, REQ-SAF-008, REQ-SAF-009): failure injection at every write, promotion, backup,
backup-verify, checkpoint, rollback, resume and runtime-teardown seam. Each injection runs the real pipeline on a
fixture copy and asserts that originals are byte-identical or restorable via rollback, that the module is BLOCKED
where the contract says, that no partial promotion remains and that no labelled runtime resource is left."""

import errno
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.integration.helpers import make_module, new_tmp, start_run, tree
from odooflux.builtins import build_context
from odooflux.core.jobs import promote as promote_mod
from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.orchestrator.run import SourceChangedError
from odooflux.core.recovery.resume import resume
from odooflux.core.recovery.rollback import rollback
from odooflux.utils import atomic

NAMES = ["kbi_a", "kbi_b", "kbi_c"]


def _disk_full():
    return OSError(errno.ENOSPC, "No space left on device")





class Killed(BaseException):
    """A kill signal: not an Exception, so no handler in the pipeline may swallow it as a normal failure."""


def _fixture(count=1):
    root = new_tmp()
    modules = [make_module(root / "src", n) for n in NAMES[:count]]
    return root, modules, [tree(m) for m in modules]


def _no_temp_files(case, module):
    leftovers = [p for p in Path(module).rglob("*.tmp")]
    case.assertEqual(leftovers, [], "an interrupted atomic write must not leave temp files in the module")


_TARGET = {"dir": ""}


def _writing_into(module):
    return _TARGET["dir"].startswith(str(module))


class _tracking_mkstemp:
    """Record the directory of the temp file atomic_write_bytes is filling, so fsync can be failed per target."""

    def __enter__(self):
        self.real = atomic.tempfile.mkstemp

        def mkstemp(*a, **kw):
            _TARGET["dir"] = str(kw.get("dir", ""))
            return self.real(*a, **kw)

        self.patch = mock.patch.object(atomic.tempfile, "mkstemp", mkstemp)
        self.patch.start()

    def __exit__(self, *exc):
        self.patch.stop()


class FakeDocker:
    """A stateful stand-in for the Docker CLI that records labelled volumes and containers."""

    def __init__(self, fail_on=None, undeletable=False):
        self.volumes, self.containers = set(), set()
        self.fail_on, self.undeletable = fail_on, undeletable

    def __call__(self, argv, timeout=None):
        from odooflux.validation.runtime import docker_env as de
        argv = list(argv)
        if self.fail_on and self.fail_on(argv):
            return de.CommandResult(1, "", "injected docker failure")
        out = ""
        if argv[:3] == ["docker", "image", "inspect"]:
            out = json.dumps([f"{argv[-1].split(':')[0]}@sha256:{'a' * 64}"])
        elif argv[:2] == ["docker", "logs"]:
            out = de.READY_MARKER
        elif argv[:3] == ["docker", "volume", "create"]:
            self.volumes.add(argv[-1])
        elif argv[:2] == ["docker", "run"] and "--name" in argv:
            self.containers.add(argv[argv.index("--name") + 1])
        elif argv[:2] == ["docker", "ps"]:
            out = "\n".join(sorted(self.containers))
        elif argv[:3] == ["docker", "volume", "ls"]:
            out = "\n".join(sorted(self.volumes))
        elif argv[:2] == ["docker", "rm"] and not self.undeletable:
            self.containers -= set(argv[4:])
        elif argv[:3] == ["docker", "volume", "rm"] and not self.undeletable:
            self.volumes -= set(argv[3:])
        return de.CommandResult(0, out, "")


class FailureInjectionTests(unittest.TestCase):
    def _blocked_clean(self, entry, module, original, reason_part):
        self.assertEqual(entry["status"], "BLOCKED")
        self.assertIn(reason_part, entry["report"]["block_reason"])
        self.assertEqual(tree(module), original, "a blocked module must be byte-identical to the original")
        _no_temp_files(self, module)

    # --- write (workspace staging) -------------------------------------------------------------------
    def test_write_disk_full_blocks_and_leaves_original(self):
        root, (module,), (original,) = _fixture()
        real = Path.write_bytes

        def write_bytes(path, data):
            if "work" in Path(path).parts:
                raise _disk_full()
            return real(path, data)

        with mock.patch.object(Path, "write_bytes", write_bytes):
            _run, state = start_run(root / "state", [module])
        self._blocked_clean(state["modules"][0], module, original, "workspace failed")

    # --- promote --------------------------------------------------------------------------------------
    def test_promote_fault_at_each_file_leaves_no_partial_promotion(self):
        for k in (1, 2, 3):
            with self.subTest(file=k):
                root, (module,), (original,) = _fixture()
                calls = {"n": 0}

                def failing(path, data, *a, **kw):
                    if str(path).startswith(str(module)):
                        calls["n"] += 1
                        if calls["n"] == k:
                            raise _disk_full()
                    return atomic.atomic_write_bytes(path, data)

                with mock.patch.object(promote_mod, "atomic_write_bytes", side_effect=failing):
                    _run, state = start_run(root / "state", [module])
                entry = state["modules"][0]
                if calls["n"] < k:
                    self.skipTest(f"fixture promotes only {calls['n']} files")
                self._blocked_clean(entry, module, original, "promotion failed")

    def test_promote_fsync_failure_inside_atomic_write(self):
        root, (module,), (original,) = _fixture()
        real = atomic.os.fsync
        fired = []

        def fsync(fd):
            if _writing_into(module) and not fired:
                fired.append(1)  # one transient fault: the first fsync of a module file
                raise _disk_full()
            return real(fd)

        with mock.patch.object(atomic.os, "fsync", fsync), _tracking_mkstemp():
            _run, state = start_run(root / "state", [module])
        self._blocked_clean(state["modules"][0], module, original, "promotion failed")

    def test_promote_replace_failure_cleans_temp_file(self):
        root, (module,), (original,) = _fixture()
        real = atomic.os.replace

        def replace(src, dst):
            if str(dst).startswith(str(module)):
                raise _disk_full()
            return real(src, dst)

        with mock.patch.object(atomic.os, "replace", replace):
            _run, state = start_run(root / "state", [module])
        self._blocked_clean(state["modules"][0], module, original, "promotion failed")

    # --- backup ---------------------------------------------------------------------------------------
    def test_backup_copy_failure_blocks_before_any_write(self):
        root, (module,), (original,) = _fixture()
        with mock.patch.object(promote_mod.shutil, "copytree", side_effect=_disk_full()):
            _run, state = start_run(root / "state", [module])
        self._blocked_clean(state["modules"][0], module, original, "backup failed")

    def test_backup_verify_mismatch_blocks_before_any_write(self):
        root, (module,), (original,) = _fixture()
        real = promote_mod.digest_tree

        def digest(path):
            result = real(path)
            return result[:-1] if "backup" in Path(path).parts else result

        with mock.patch.object(promote_mod, "digest_tree", side_effect=digest):
            _run, state = start_run(root / "state", [module])
        self._blocked_clean(state["modules"][0], module, original, "backup failed")

    # --- checkpoint -----------------------------------------------------------------------------------
    def test_checkpoint_failure_is_recoverable_by_rollback_and_resume(self):
        for recover in ("rollback", "resume"):
            with self.subTest(recover=recover):
                root, modules, originals = _fixture(3)
                real = RunDir.write_state
                seen = {"saves": 0}

                def write_state(run, state):
                    states = [m["status"] for m in state["modules"]]
                    if "PROMOTED" in states:
                        seen["saves"] += 1
                        if seen["saves"] == 1:
                            raise _disk_full()
                    return real(run, state)

                with mock.patch.object(RunDir, "write_state", write_state):
                    with self.assertRaises(OSError):
                        start_run(root / "state", modules)
                (run_dir,) = list((root / "state" / "runs").iterdir())
                if recover == "rollback":
                    rollback(root / "state", run_dir.name)
                    for module, original in zip(modules, originals):
                        self.assertEqual(tree(module), original)
                else:
                    # kbi_a was promoted but its checkpoint was lost: resume refuses (source_digest changed,
                    # contracts/recovery.md) and rollback still restores every file.
                    ctx = build_context()
                    with self.assertRaises(SourceChangedError):
                        resume(root / "state", run_dir.name, ctx.registries, layer3=ctx.layer3)
                    rollback(root / "state", run_dir.name)
                    for module, original in zip(modules, originals):
                        self.assertEqual(tree(module), original)

    # --- kill between backup verification and promotion; resume ---------------------------------------
    def test_kill_between_backup_verify_and_promote_then_resume_or_rollback(self):
        for recover in ("resume", "rollback"):
            with self.subTest(recover=recover):
                root, modules, originals = _fixture(2)
                with mock.patch("odooflux.core.orchestrator.run.promote_module", side_effect=Killed()):
                    with self.assertRaises(Killed):
                        start_run(root / "state", modules)
                for module, original in zip(modules, originals):
                    self.assertEqual(tree(module), original, "nothing is promoted before the kill point")
                (run_dir,) = list((root / "state" / "runs").iterdir())
                if recover == "rollback":
                    rollback(root / "state", run_dir.name)
                else:
                    ctx = build_context()
                    final = resume(root / "state", run_dir.name, ctx.registries, layer3=ctx.layer3)
                    self.assertEqual({m["status"] for m in final["modules"]}, {"PROMOTED"})
                    rollback(root / "state", run_dir.name)
                for module, original in zip(modules, originals):
                    self.assertEqual(tree(module), original)

    def test_failure_during_resume_then_second_resume_completes(self):
        root, modules, originals = _fixture(3)

        def stop_after_a(name):
            if name == "kbi_a":
                raise Killed()

        with self.assertRaises(Killed):
            start_run(root / "state", modules, hook=stop_after_a)
        (run_dir,) = list((root / "state" / "runs").iterdir())
        ctx = build_context()

        def stop_after_b(name):
            if name == "kbi_b":
                raise Killed()

        with self.assertRaises(Killed):
            resume(root / "state", run_dir.name, ctx.registries, layer3=ctx.layer3, hook=stop_after_b)
        final = resume(root / "state", run_dir.name, ctx.registries, layer3=ctx.layer3)
        self.assertEqual({m["status"] for m in final["modules"]}, {"PROMOTED"})
        rollback(root / "state", run_dir.name)
        for module, original in zip(modules, originals):
            self.assertEqual(tree(module), original)

    # --- rollback -------------------------------------------------------------------------------------
    def test_rollback_fault_then_retry_restores_everything(self):
        root, modules, originals = _fixture(2)
        run_id, _state = start_run(root / "state", modules)
        from odooflux.core.recovery import rollback as rb
        calls = {"n": 0}

        def failing(path, data):
            calls["n"] += 1
            if calls["n"] == 2:
                raise _disk_full()
            return atomic.atomic_write_bytes(path, data)

        with mock.patch.object(rb, "atomic_write_bytes", side_effect=failing):
            with self.assertRaises(OSError):
                rollback(root / "state", run_id)
        rollback(root / "state", run_id)  # a second attempt must finish the job
        for module, original in zip(modules, originals):
            self.assertEqual(tree(module), original)
            _no_temp_files(self, module)

    # --- runtime teardown (docker adapter, stub runner) -----------------------------------------------
    def _env(self, docker):
        from odooflux.validation.runtime import docker_env as de
        return de, de.DockerEnvironment(runner=docker, readiness_timeout_s=1, sleep=lambda s: None)

    def test_runtime_teardown_removes_every_labelled_resource(self):
        docker = FakeDocker()
        de, env = self._env(docker)
        handle = env.prepare("19.0", [], de.Limits(), state_dir=tempfile.mkdtemp())
        self.assertTrue(docker.volumes and docker.containers)
        self.assertEqual(env.teardown(handle), [])
        self.assertEqual((docker.volumes, docker.containers), (set(), set()))
        self.assertEqual(env.teardown(handle), [], "teardown is idempotent")

    def test_runtime_prepare_failure_tears_down_what_it_created(self):
        for stage, fail in (("second volume", lambda a: a[:3] == ["docker", "volume", "create"] and "data" in a[-1]),
                            ("database start", lambda a: a[:2] == ["docker", "run"])):
            with self.subTest(stage=stage):
                docker = FakeDocker(fail_on=fail)
                de, env = self._env(docker)
                with self.assertRaises(de.EnvironmentUnavailable):
                    env.prepare("19.0", [], de.Limits(), state_dir=tempfile.mkdtemp())
                self.assertEqual((docker.volumes, docker.containers), (set(), set()))

    def test_runtime_teardown_failure_is_reported_with_cleanup_command(self):
        docker = FakeDocker()
        de, env = self._env(docker)
        handle = env.prepare("19.0", [], de.Limits(), state_dir=tempfile.mkdtemp())
        docker.undeletable = True
        warnings = env.teardown(handle)
        self.assertTrue(any("docker rm -f -v" in w for w in warnings))
        docker.undeletable = False
        self.assertEqual(env.teardown(handle), [])
        self.assertEqual((docker.volumes, docker.containers), (set(), set()))


if __name__ == "__main__":
    unittest.main()
