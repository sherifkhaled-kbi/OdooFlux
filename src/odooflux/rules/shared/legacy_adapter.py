"""Legacy adapter: the P0 rule tables and fixers as engine steps named ``legacy-<from>-<to>`` (FR-021, R-07).

One rule per file kind. The whole legacy table for that kind runs in one ``check_content`` call, so
its per-line deduplication matches the P0 script exactly. Per-rule granularity comes with P5.
"""

from pathlib import Path

from odooflux.core.engine.step_runner import Step
from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.rules.shared.legacy_rules import (
    MigrationReport, _rules_for_file, apply_manifest_fixes, apply_python_fixes, apply_xml_fixes,
    check_content)
from odooflux.discovery.manifest import MANIFEST_NAMES


def _kind(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    if name in MANIFEST_NAMES:
        return "manifest"
    dot = name.rfind(".")
    return name[dot + 1:] if dot > 0 else "none"


class LegacyRule:
    contract_version = CONTRACT_VERSION
    depends: tuple = ()

    def __init__(self, kind: str, from_version: int, to_version: int):
        self.key = f"legacy.{kind}"
        self.step = f"legacy-{from_version}-{to_version}"
        self._from, self._to = from_version, to_version

    def detect(self, document) -> list:
        scratch = MigrationReport(module_path="", from_version=self._from, to_version=self._to)
        rules = _rules_for_file(Path(document.path), to_version=self._to)
        if rules is not None:
            check_content(document.text, document.path, rules, self._from, scratch)
        return scratch.issues


def legacy_rules_for(path: str, from_version: int, to_version: int) -> list:
    if _rules_for_file(Path(path), to_version=to_version) is None:
        return []
    return [LegacyRule(_kind(path), from_version, to_version)]


def fixer_for(path: str, from_version: int, to_version: int):
    """Callable(path, text) -> text for the file kind, or None when the kind is detect-only (JS, CSS)."""
    kind = _kind(path)
    if kind == "manifest":
        return lambda p, t: apply_manifest_fixes(t, from_version, to_version=to_version)
    if kind == "py":
        return lambda p, t: apply_python_fixes(t, from_version, to_version=to_version)
    if kind == "xml":
        return lambda p, t: apply_xml_fixes(t, from_version, to_version=to_version)
    return None


def step_for(path: str, from_version: int, to_version: int, *, transform: bool, extra_rules=()) -> Step:
    rules = legacy_rules_for(path, from_version, to_version) + [
        r for r in extra_rules if getattr(r, "step", "") in ("*", f"legacy-{from_version}-{to_version}")]
    step_id = f"legacy-{from_version}-{to_version}"
    return Step(step_id=step_id, rules=rules,
                transform=fixer_for(path, from_version, to_version) if transform else None)
