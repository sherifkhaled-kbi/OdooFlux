"""P0 regression helpers, moved from tests/regression/helpers.py (002 T007). Offline, stdlib only."""

import shutil
import subprocess
import sys
from pathlib import Path

from tests._support.digest import tree_digest  # noqa: F401  (re-exported for the P0 tests)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "odooflux.py"
FIXTURE = REPO_ROOT / "tests" / "golden_fixtures" / "p0_kbi_demo_v14"

SRC_ROOT = REPO_ROOT / "src"
# The package lives in src/; the root odooflux.py is the launcher and must never shadow it.
TESTS_ROOT = REPO_ROOT / "tests"


def _ensure_import_paths() -> None:
    """Drop only the shadowing entries ('' and the repository root); keep every other entry (for example the
    ``tests/`` directory that ``tests/contract/__init__.py`` adds); add ``src`` once, first; never duplicate."""
    sys.path[:] = [p for p in sys.path if p not in ("", str(REPO_ROOT))]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    if str(TESTS_ROOT) not in sys.path:
        sys.path.append(str(TESTS_ROOT))


_ensure_import_paths()


def make_addons(tmp, fixture=FIXTURE, name="kbi_demo") -> Path:
    """Copy *fixture* to ``<tmp>/<name>`` and return the addons root *tmp*."""
    root = Path(tmp)
    shutil.copytree(fixture, root / name)
    return root


def run_cli(args) -> tuple:
    """Run odooflux.py with *args*; return (exit_code, combined output)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300,
    )
    return proc.returncode, proc.stdout


def run_main(args) -> tuple:
    """Run odooflux.main() in-process (so tests can patch internals); return (exit_code, stdout)."""
    import contextlib
    import io
    from unittest import mock

    from odooflux.builtins import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in args])
    return code, buf.getvalue()


def only_run(state_dir) -> Path:
    """The single run directory under <state_dir>/runs/."""
    runs = sorted((Path(state_dir) / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {runs}"
    return runs[0]


def read_runlog(state_dir) -> list:
    import json

    log = only_run(state_dir) / "log" / "run_log.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
