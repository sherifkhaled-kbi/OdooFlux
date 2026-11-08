"""Refuse report output paths inside scanned modules (FR-009, REQ-SEC-003). Paths are resolved first, so ``..`` and
symlinks into a module are caught; a sibling directory that merely shares a name prefix is not inside."""

from pathlib import Path
from typing import Optional


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def check_output_paths(outputs: dict, scanned_roots: list) -> Optional[str]:
    """*outputs* maps an option name to a path (or None). Returns a message for the first offending path, else None.
    The ``.index.json`` sibling of ``--diff`` shares its directory, so one check covers it."""
    roots = [Path(r).resolve() for r in scanned_roots]
    for option, value in outputs.items():
        if not value:
            continue
        resolved = Path(value).expanduser().resolve()
        for root in roots:
            if _inside(resolved, root):
                return (f"{option} path {resolved} is inside the scanned module or addons path {root}; reports are "
                        f"never written into scanned code. Choose a path outside the modules and addons path "
                        f"(REQ-SEC-003)")
    return None
