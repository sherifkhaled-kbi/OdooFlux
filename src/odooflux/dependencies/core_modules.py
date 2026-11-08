"""``*.deps.unknown-dependency`` (REQ-DEP-001): ``depends`` entries against the scanned modules and the
official core module lists (``knowledge/compatibility/core_modules.json``, pinned to registry SHAs).

- CRITICAL: the dependency is in the source core list, absent from the target core list, and not scanned
  (a core module that was removed or renamed).
- WARNING: the name is in neither list nor scanned (possibly an Enterprise or third-party module; the
  Enterprise source is not indexed, so this is not decidable).
- Nothing is reported when the target list is unknown. Without a source list the unknown name is a WARNING.

- With ``replaced_by`` data (FR-020, per-module official evidence): a removed module with a recorded successor is a
  DETECT_ONLY ``*.deps.removed-with-successor`` finding (a suggestion, no edit); one without says "no successor known".

Manifests are read with ``ast.literal_eval`` only (FR-019).
"""

import json
from pathlib import Path

from odooflux.core.contracts.records import Finding
from odooflux.discovery.manifest import MANIFEST_NAMES, read_manifest
from odooflux.validation.dependency.integrity import CORE_MODULES_FILE, load_core_modules

RULE_ID = "*.deps.unknown-dependency"
SUCCESSOR_RULE_ID = "*.deps.removed-with-successor"
SUGGESTION = "Declare the module's source, scan it together with this module, or replace the dependency."


def core_list(version: str):
    """Shipped core module names for ``version``, or None when no list exists for it."""
    return load_core_modules(version)


def load_replaced_by(version: str) -> dict:
    """``{removed module: {"successors": [...], "evidence": [...]}}`` for the step ending at ``version`` (may be empty)."""
    if not CORE_MODULES_FILE.is_file():
        return {}
    data = json.loads(CORE_MODULES_FILE.read_text(encoding="utf-8"))
    for record in data.get("versions", []):
        if record.get("id") == version:
            return dict(record.get("replaced_by") or {})
    return {}


def _successor(replaced_by, dep):
    """The usable ``replaced_by`` entry for ``dep``: it needs successors and evidence, else None (never inferred)."""
    entry = (replaced_by or {}).get(dep)
    if isinstance(entry, dict) and entry.get("successors") and entry.get("evidence"):
        return entry
    return None


def _line_of(text: str, name: str) -> int:
    for quote in ("'", '"'):
        index = text.find(quote + name + quote)
        if index >= 0:
            return text.count("\n", 0, index) + 1
    return 1


def check_unknown_dependencies(module_paths, *, source_core, target_core, replaced_by=None) -> list:
    """Findings for every unresolved dependency of the given module directories."""
    manifests = []
    for raw in module_paths:
        root = Path(raw)
        path = next((root / n for n in MANIFEST_NAMES if (root / n).is_file()), None)
        if path is None:
            continue
        manifest, error = read_manifest(path)
        if error:
            continue
        depends = [d for d in (manifest.get("depends") or []) if isinstance(d, str)]
        manifests.append((root.name, path, depends))
    scanned = {name for name, _path, _deps in manifests}
    if target_core is None:
        return []
    findings = []
    for name, path, depends in manifests:
        text = path.read_text(encoding="utf-8", errors="replace")
        for dep in depends:
            if dep in scanned or dep in target_core:
                continue
            removed = source_core is not None and dep in source_core
            entry = _successor(replaced_by, dep) if removed else None
            if entry:
                names = ", ".join(repr(n) for n in entry["successors"])
                refs = ", ".join(entry["evidence"])
                findings.append(Finding(
                    rule_id=SUCCESSOR_RULE_ID, path=str(path), line=_line_of(text, dep), severity="CRITICAL",
                    message=(f"module {name!r} depends on {dep!r}, which the target version no longer ships; "
                             f"official evidence names successor {names} ({refs})"),
                    suggestion=f"Review replacing {dep!r} with {names}; no edit is applied.",
                    matched=dep, evidence=tuple(entry["evidence"])))
                continue
            severity = "CRITICAL" if removed else "WARNING"
            reason = ("is a core module of the source version that the target version no longer ships"
                      if removed else "is neither a scanned module nor a core module of the target version")
            if removed and replaced_by is not None:
                reason += "; no successor known"
            findings.append(Finding(rule_id=RULE_ID, path=str(path), line=_line_of(text, dep),
                                    severity=severity, message=f"module {name!r} depends on {dep!r}, which {reason}",
                                    suggestion=SUGGESTION, matched=dep))
    return sorted(findings, key=lambda f: (f.path, f.line, f.matched))
