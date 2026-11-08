"""Importing this module puts src/ first on sys.path (shared by the P2 unit and integration tests)."""

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "src"
sys.path[:] = [p for p in sys.path if p not in ("", str(REPO))]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
