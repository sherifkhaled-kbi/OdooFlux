"""Integration tests for P2 (workspace, recovery, CLI contract). Sets up sys.path on import."""

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path[:] = [p for p in sys.path if p not in ("", str(_REPO))]
sys.path.insert(0, str(_REPO / "src"))
