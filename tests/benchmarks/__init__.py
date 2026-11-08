"""Benchmark harness. Sets up sys.path on import (src first; root launcher never shadows the package)."""

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path[:] = [p for p in sys.path if p not in ("", str(_REPO))]
sys.path.insert(0, str(_REPO / "src"))
