"""Shared helpers for the opt-in runtime tests. Importing this module starts nothing; each test class is gated
by RUNTIME, so the default suite never reaches the Docker daemon (ODOOFLUX_RUNTIME_TESTS=1 enables it)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.unit._setup import SRC  # noqa: F401  (puts src/ first on sys.path; must precede odooflux)
from odooflux.validation.runtime import docker_env as de

ROOT = Path(__file__).resolve().parents[1] / "golden_fixtures" / "runtime"
RUNTIME = unittest.skipUnless(os.environ.get("ODOOFLUX_RUNTIME_TESTS") == "1",
                              "opt-in: set ODOOFLUX_RUNTIME_TESTS=1 (starts Docker containers)")


def fixture(name: str) -> Path:
    return ROOT / name


def state_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="odooflux-runtime-test-"))


def remove_state(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def labelled_resources(run_id: str) -> tuple:
    """(containers, volumes) that still carry the run label, as reported by the Docker CLI (SC-003)."""
    containers = subprocess.run(de.build_list_argv(run_id, "container"), capture_output=True, text=True,
                                check=False).stdout.split()
    volumes = subprocess.run(de.build_list_argv(run_id, "volume"), capture_output=True, text=True,
                             check=False).stdout.split()
    return containers, volumes


def any_labelled_containers() -> list:
    """Every container carrying the odooflux.run label, whatever the run (used when no run was created)."""
    return subprocess.run(["docker", "ps", "-aq", "--filter", f"label={de.LABEL_KEY}"], capture_output=True,
                          text=True, check=False).stdout.split()
