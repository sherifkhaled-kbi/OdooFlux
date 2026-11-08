"""Build the wheel once per process from a clean copy of the project (nothing is written into the repo)."""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_cache: dict = {}


def tooling_gap() -> str:
    """Why a wheel cannot be built offline here, or '' when it can."""
    probe = subprocess.run([sys.executable, "-c", "import setuptools, wheel"], capture_output=True, text=True)
    if probe.returncode:
        return "setuptools and wheel are required for an offline build (--no-build-isolation): " + \
            probe.stderr.strip().splitlines()[-1]
    return ""


def build_wheel() -> Path:
    if "wheel" in _cache:
        return _cache["wheel"]
    work = Path(tempfile.mkdtemp(prefix="odooflux-wheel-"))
    src = work / "project"
    src.mkdir()
    for name in ("pyproject.toml", "MANIFEST.in"):
        if (REPO / name).is_file():
            shutil.copy2(REPO / name, src / name)
    shutil.copytree(REPO / "src", src / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "*.pyc"))
    out = work / "dist"
    proc = subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation",
                           "--no-index", "-w", str(out)], cwd=src, capture_output=True, text=True, timeout=600)
    if proc.returncode:
        raise RuntimeError("wheel build failed:\n" + proc.stdout[-2000:] + proc.stderr[-2000:])
    _cache["wheel"] = next(out.glob("odooflux-*.whl"))
    return _cache["wheel"]


def wheel_names(wheel: Path) -> set:
    with zipfile.ZipFile(wheel) as zf:
        return set(zf.namelist())
