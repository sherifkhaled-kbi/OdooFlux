"""Baseline benchmark (R-09, SC-007): wall time and peak RSS for analysing a generated repository
in a child process. Usage: python bench_analyze.py REPO_DIR [--from 14]. Prints one JSON line."""

import json
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def measure(repo: Path, from_version: int = 14) -> dict:
    state = Path(tempfile.mkdtemp())
    cmd = [sys.executable, str(REPO / "odooflux.py"), "--addons-path", str(repo),
           "--from-version", str(from_version), "--no-color", "--state-dir", str(state)]
    start = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    wall = time.perf_counter() - start
    peak_kib = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss  # Linux: KiB
    modules = sum(1 for p in repo.iterdir() if p.is_dir())
    return {"modules": modules, "wall_seconds": round(wall, 2), "peak_rss_mib": round(peak_kib / 1024, 1),
            "exit_code": proc.returncode}


if __name__ == "__main__":
    print(json.dumps(measure(Path(sys.argv[1]))))
