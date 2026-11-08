#!/usr/bin/env python3
"""OdooFlux launcher (P2 cut-over, R-01). The implementation lives in src/odooflux.

``src/`` goes first on ``sys.path`` and the repository root is removed, so this script never
shadows the package of the same name.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if os.path.abspath(sys.path[0] or os.curdir) == _ROOT:
    sys.path.pop(0)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from odooflux.builtins import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
