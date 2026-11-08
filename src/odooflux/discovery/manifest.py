"""Manifest reading with ``ast.literal_eval``: the core never executes customer code (FR-011, FR-019)."""

import ast
from pathlib import Path
from typing import Optional

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")


def read_manifest(path: Path):
    """Return (dict, None) for a valid literal manifest, or (None, error message)."""
    try:
        value = ast.literal_eval(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError) as exc:
        return None, f"manifest is not a literal dict: {exc}"
    if not isinstance(value, dict):
        return None, "manifest is not a literal dict"
    return value, None


def declared_version(manifest: Optional[dict]) -> Optional[str]:
    if manifest and isinstance(manifest.get("version"), str):
        return manifest["version"]
    return None
