"""Importing this module puts src/ first on sys.path for the reporting tests. It only inserts: no existing sys.path
entry is ever removed."""

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
