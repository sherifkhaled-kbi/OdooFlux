import io
import contextlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "tests" / "golden_fixtures" / "knowledge"


def knowledge_cli(args) -> tuple:
    """Run `odooflux knowledge ...` in-process; return (exit_code, stdout)."""
    from odooflux.cli.knowledge import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in args])
    return code, buf.getvalue()


def copy_golden(name: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / name
    shutil.copytree(GOLDEN / name, tmp)
    return tmp


def git(repo: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
