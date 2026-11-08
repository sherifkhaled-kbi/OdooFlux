"""Load OdooVersion records and transitions from knowledge data with a stdlib schema check (R-04)."""

import json
import re
from pathlib import Path

from odooflux.core.contracts.records import (
    RESEARCH_STATUSES, OdooVersion, MigrationStep)

KNOWLEDGE_FILE = Path(__file__).resolve().parents[2] / "knowledge" / "compatibility" / "versions.json"
SCHEMA_ID = "odooflux.versions/1"
SUPPORT_STATUSES = ("UNSUPPORTED", "SUPPORTED")
_PY = re.compile(r"^\d+\.\d+$")


class VersionDataError(ValueError):
    """The knowledge file does not match the schema."""


def _require(obj: dict, keys, where: str) -> None:
    for key in keys:
        if key not in obj:
            raise VersionDataError(f"{where}: missing key {key!r}")


def load_version_data(path=KNOWLEDGE_FILE):
    """Return (versions, transitions) where transitions maps (source, target) -> research_status."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA_ID:
        raise VersionDataError(f"unexpected schema {data.get('schema')!r}")
    versions, seen = [], set()
    for raw in data.get("versions", []):
        _require(raw, ("id", "python_min", "python_max", "online_releases", "support_status"), "version")
        if raw["id"] in seen:
            raise VersionDataError(f"duplicate version id {raw['id']!r}")
        seen.add(raw["id"])
        if raw["support_status"] not in SUPPORT_STATUSES:
            raise VersionDataError(f"{raw['id']}: unknown support_status {raw['support_status']!r}")
        for field in ("python_min", "python_max"):
            if raw[field] is not None and not _PY.match(raw[field]):
                raise VersionDataError(f"{raw['id']}: {field} must be M.m or null")
        try:
            versions.append(OdooVersion(
                id=raw["id"], python_min=raw["python_min"], python_max=raw["python_max"],
                online_releases=tuple(raw["online_releases"]), support_status=raw["support_status"]))
        except ValueError as exc:
            raise VersionDataError(str(exc)) from None
    majors = [v.major for v in versions]
    if len(majors) != len(set(majors)):
        raise VersionDataError("two versions share a major number")
    transitions = {}
    for raw in data.get("transitions", []):
        _require(raw, ("source", "target", "research_status"), "transition")
        if raw["research_status"] not in RESEARCH_STATUSES:
            raise VersionDataError(f"unknown research_status {raw['research_status']!r}")
        if raw["source"] not in seen or raw["target"] not in seen:
            raise VersionDataError(f"transition {raw['source']}->{raw['target']} names an unknown version")
        transitions[(raw["source"], raw["target"])] = raw["research_status"]
    return sorted(versions, key=lambda v: v.major), transitions


def steps_for_pairs(transitions: dict) -> list:
    """All transitions as MigrationStep records (for listing)."""
    return [MigrationStep(s, t, status) for (s, t), status in sorted(transitions.items())]
