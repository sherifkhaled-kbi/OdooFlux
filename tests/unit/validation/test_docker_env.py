"""TST-008-004 (REQ-VAL-004, REQ-SEC-001, REQ-SEC-002, FR-005): Docker adapter command construction.

Pure argv builders and a fake runner only. No Docker command that starts a container or pulls an image runs
in this module; the opt-in runtime tests in tests/runtime/ exercise the real daemon.
"""

import unittest

from .._setup import SRC  # noqa: F401  (puts src/ first on sys.path)
from odooflux.validation.runtime import docker_env as de

RUN = "r0123456789ab"
LABEL = f"odooflux.run={RUN}"
DIGEST = "odoo@sha256:" + "a" * 64
PG_DIGEST = "postgres@sha256:" + "b" * 64
MOD_A = "/work/modules/kbi_one"
MOD_B = "/work/modules/kbi_two"
MODULES = [(MOD_A, "kbi_one"), (MOD_B, "kbi_two")]
SOCKET = f"odooflux-{RUN}-socket"
DATA = f"odooflux-{RUN}-data"
LIMITS = de.Limits(cpu=2.0, memory_mb=2048, wall_time_s=600, network="none", pids=512)


def option_values(argv, flag):
    return [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == flag]


def mount_sources(argv):
    """Each -v value as (source, destination, options)."""
    parsed = []
    for spec in option_values(argv, "-v"):
        parts = spec.split(":")
        parsed.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return parsed


def odoo_argv():
    return de.build_odoo_argv(RUN, f"odooflux-{RUN}-install-1", DIGEST, SOCKET, DATA, MODULES,
                              ["odoo", "-d", "odoo", "-i", "kbi_one,kbi_two", "--stop-after-init"], LIMITS)


class OdooContainerArgvTests(unittest.TestCase):
    def test_network_is_none_and_no_privileged_mode(self):
        argv = odoo_argv()
        self.assertEqual(option_values(argv, "--network"), ["none"])
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("host", option_values(argv, "--network"))

    def test_labelled_with_run_id(self):
        argv = odoo_argv()
        self.assertIn(LABEL, option_values(argv, "--label"))

    def test_limits_are_passed_from_the_limits_record(self):
        argv = odoo_argv()
        self.assertEqual(option_values(argv, "--cpus"), ["2.0"])
        self.assertEqual(option_values(argv, "--memory"), ["2048m"])
        self.assertEqual(option_values(argv, "--pids-limit"), ["512"])

    def test_image_reference_is_used_exactly_as_given(self):
        argv = odoo_argv()
        self.assertEqual(argv.count(DIGEST), 1)
        self.assertNotIn("odoo:19.0", argv)

    def test_filesystem_and_privilege_hardening(self):
        argv = odoo_argv()
        self.assertIn("--read-only", argv)
        self.assertEqual(option_values(argv, "--cap-drop"), ["ALL"])
        self.assertIn("no-new-privileges", option_values(argv, "--security-opt"))

    def test_command_follows_the_image(self):
        argv = odoo_argv()
        image_index = argv.index(DIGEST)
        self.assertEqual(argv[image_index + 1:image_index + 3], ["odoo", "-d"])
        self.assertEqual(argv[0:2], ["docker", "run"])


class MountTests(unittest.TestCase):
    def test_module_copies_are_mounted_read_only_and_nothing_else_from_the_host(self):
        argv = odoo_argv()
        mounts = mount_sources(argv)
        host_mounts = [m for m in mounts if m[0].startswith("/") or m[0].startswith(".")]
        self.assertEqual(host_mounts, [
            (MOD_A, "/mnt/extra-addons/kbi_one", "ro"),
            (MOD_B, "/mnt/extra-addons/kbi_two", "ro"),
        ])

    def test_named_volumes_are_the_only_other_sources(self):
        mounts = mount_sources(odoo_argv())
        named = {m[0] for m in mounts} - {MOD_A, MOD_B}
        self.assertEqual(named, {SOCKET, DATA})

    def test_no_bind_mount_is_writable(self):
        for source, _destination, options in mount_sources(odoo_argv()):
            if source.startswith("/"):
                self.assertEqual(options, "ro", source)

    def test_postgres_container_mounts_only_the_socket_volume(self):
        argv = de.build_postgres_argv(RUN, f"odooflux-{RUN}-pg", PG_DIGEST, SOCKET, LIMITS)
        self.assertEqual(mount_sources(argv), [(SOCKET, "/var/run/postgresql", "")])
        self.assertEqual(option_values(argv, "--network"), ["none"])
        self.assertIn(LABEL, option_values(argv, "--label"))
        self.assertNotIn("--privileged", argv)


class PrepareAndTeardownArgvTests(unittest.TestCase):
    def test_scratch_volumes_are_created_with_the_run_label(self):
        argv = de.build_volume_create_argv(RUN, SOCKET)
        self.assertEqual(argv[:2], ["docker", "volume"])
        self.assertIn("create", argv)
        self.assertIn(LABEL, option_values(argv, "--label"))
        self.assertEqual(argv[-1], SOCKET)

    def test_listing_is_filtered_by_run_label_for_containers_and_volumes(self):
        for kind, subcommand in (("container", ["docker", "ps", "-aq"]), ("volume", ["docker", "volume", "ls", "-q"])):
            argv = de.build_list_argv(RUN, kind)
            self.assertEqual(argv[:len(subcommand)], subcommand)
            self.assertIn(f"label={LABEL}", option_values(argv, "--filter"))

    def test_removal_forces_and_drops_anonymous_volumes(self):
        argv = de.build_remove_containers_argv(["c1", "c2"])
        self.assertEqual(argv[:4], ["docker", "rm", "-f", "-v"])
        self.assertEqual(argv[4:], ["c1", "c2"])
        self.assertEqual(de.build_remove_volumes_argv([SOCKET])[:3], ["docker", "volume", "rm"])

    def test_kill_targets_one_named_container(self):
        self.assertEqual(de.build_kill_argv("c1"), ["docker", "kill", "c1"])

    def test_image_inspect_uses_the_local_daemon_only(self):
        argv = de.build_image_inspect_argv("odoo:19.0")
        self.assertEqual(argv[:3], ["docker", "image", "inspect"])
        self.assertIn("odoo:19.0", argv)
        self.assertNotIn("pull", argv)


class TeardownWithFakeRunnerTests(unittest.TestCase):
    """Teardown is idempotent and issues removals only for resources that carry the run label."""

    class Recorder:
        def __init__(self, listings):
            self.listings = listings          # argv subcommand kind -> stdout lines
            self.calls = []

        def __call__(self, argv, timeout=None):
            self.calls.append(list(argv))
            if argv[:2] == ["docker", "ps"]:
                out = "\n".join(self.listings.get("container", []))
            elif argv[:3] == ["docker", "volume", "ls"]:
                out = "\n".join(self.listings.get("volume", []))
            elif argv[:2] == ["docker", "rm"]:
                self.listings["container"] = [c for c in self.listings.get("container", []) if c not in argv[4:]]
                out = ""
            elif argv[:3] == ["docker", "volume", "rm"]:
                self.listings["volume"] = [v for v in self.listings.get("volume", []) if v not in argv[3:]]
                out = ""
            else:
                out = ""
            return de.CommandResult(returncode=0, stdout=out, stderr="")

    def handle(self):
        return de.EnvHandle(run_id=RUN, version="19.0", image=DIGEST, postgres_image=PG_DIGEST,
                            socket_volume=SOCKET, data_volume=DATA, modules=tuple(MODULES),
                            limits=LIMITS, state_dir="/unused", steps=(), postgres_container=f"odooflux-{RUN}-pg")

    def test_nothing_labelled_means_no_removal_command(self):
        recorder = self.Recorder({})
        warnings = de.DockerEnvironment(runner=recorder).teardown(self.handle())
        self.assertEqual(warnings, [])
        self.assertFalse([c for c in recorder.calls if c[1:2] in (["rm"], ["kill"]) or c[1:3] == ["volume", "rm"]])

    def test_labelled_leftovers_are_removed_then_listing_is_empty_again(self):
        recorder = self.Recorder({"container": [f"odooflux-{RUN}-pg"], "volume": [SOCKET, DATA]})
        warnings = de.DockerEnvironment(runner=recorder).teardown(self.handle())
        self.assertEqual(warnings, [])
        removals = [c for c in recorder.calls if c[1:2] == ["rm"]]
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0][-1], f"odooflux-{RUN}-pg")
        volume_removals = [c for c in recorder.calls if c[1:3] == ["volume", "rm"]]
        self.assertEqual(volume_removals[0][3:], [SOCKET, DATA])


class LimitsTests(unittest.TestCase):
    def test_defaults_are_positive_and_network_is_none(self):
        limits = de.Limits()
        self.assertGreater(limits.cpu, 0)
        self.assertGreater(limits.memory_mb, 0)
        self.assertGreater(limits.wall_time_s, 0)
        self.assertGreater(limits.pids, 0)
        self.assertEqual(limits.network, "none")


if __name__ == "__main__":
    unittest.main()
