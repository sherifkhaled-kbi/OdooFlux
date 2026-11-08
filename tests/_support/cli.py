"""Run the root launcher ``odooflux.py`` as a subprocess (REQ-TST-001)."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "odooflux.py"
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class CompletedRun:
    exit: int
    stdout: str
    stderr: str


def run_legacy_cli(args, cwd=None) -> CompletedRun:
    """Run ``odooflux.py`` with *args* (``--no-color`` is always added) and a 120 s timeout."""
    argv = [str(a) for a in args]
    if "--no-color" not in argv:
        argv.append("--no-color")
    proc = subprocess.run([sys.executable, str(SCRIPT), *argv], cwd=None if cwd is None else str(cwd),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=TIMEOUT_SECONDS)
    return CompletedRun(proc.returncode, proc.stdout, proc.stderr)
