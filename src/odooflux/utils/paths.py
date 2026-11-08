"""Path containment checks (symlinks must not escape a module root)."""

from pathlib import Path


def is_within(child, root) -> bool:
    """True when *child* resolves to *root* or a path below it."""
    child_r = Path(child).resolve()
    root_r = Path(root).resolve()
    return child_r == root_r or root_r in child_r.parents
