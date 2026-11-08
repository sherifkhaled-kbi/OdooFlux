"""Regression suites. Importing this package puts src/ first on sys.path and keeps the root
launcher (odooflux.py) from shadowing the odooflux package."""

import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path[:] = [p for p in sys.path if p not in ("", str(_REPO))]
sys.path.insert(0, str(_REPO / "src"))
