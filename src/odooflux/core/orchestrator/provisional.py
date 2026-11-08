"""Provisional-corpus labelling of a run (ADR-019 item 4): a run is labelled PROVISIONAL when asked with
``--provisional-corpus`` or when a module sits under a directory carrying a ``PROVISIONAL.md`` marker. The label lands
in ``state["provisional"]`` and every renderer shows it. The label is never an approval."""

from pathlib import Path

MARKER = "PROVISIONAL.md"


def marker_for(module_path) -> bool:
    """True when the module directory or any ancestor contains the PROVISIONAL.md marker."""
    path = Path(module_path).resolve()
    return any((p / MARKER).is_file() for p in (path, *path.parents))


def provisional_label(from_version: int, to_version: int, reason: str) -> dict:
    return {"active": True, "labels": [
        f"{from_version}.0->{to_version}.0 rules validated only against the PROVISIONAL corpus; "
        f"not approved migration truth ({reason})"]}


def provisional_for(module_paths, from_version: int, to_version: int, flag: bool = False):
    """Return the ``provisional`` state value, or None when the run is not provisional."""
    if flag:
        return provisional_label(from_version, to_version, "--provisional-corpus")
    if any(marker_for(p) for p in module_paths):
        return provisional_label(from_version, to_version, f"{MARKER} marker found")
    return None
