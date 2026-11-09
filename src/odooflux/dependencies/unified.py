"""Unified Community + Enterprise dependency coverage for migrate (feature 012, plan addendum B3/B5).

The active knowledge release is the only authority. Inventories are read from `<knowledge tree>/inventory/<M.0>.json`
(the knowledge tree of an installed release is `<release>/knowledge`). There is no edition flag, no network, and nothing
is executed: inventories are plain verified JSON.

- `load_inventories` reads and verifies every inventory file of the tree. An absent directory gives {}. A file that does
  not verify is a `UnifiedError` (fail closed); a bad file is never skipped.
- `resolve_custom` resolves the closure of each custom module over the source and target inventories (built on
  `knowledge.update.inventory.resolve`) and gives every module a coverage verdict:
  COMPLETE: every dependency resolves on both versions, and when the closure reaches an Enterprise module both versions
  carry an Enterprise source. INCOMPLETE: anything else, with stable reason codes.
- `migration_coverage` returns None when neither version of the migration has an inventory. That is today's flow.

Enterprise facts are never named in a message: only counts. Dependency names come from the user's own manifests.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.knowledge.update import inventory as _inventory

INVENTORY_DIR = "inventory"
COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
FINDING_ID = "KB-COVERAGE-INCOMPLETE"
_LABEL = re.compile(r"[A-Za-z0-9._-]{1,32}")
_MODULE = re.compile(r"[a-z0-9_]{1,64}")


class UnifiedError(ValueError):
    """An inventory cannot be used. `code` is a stable closed code; the message never carries inventory content."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ModuleCoverage:
    name: str
    verdict: str
    reasons: tuple = ()                 # sorted codes: INVENTORY_MISSING:<v>, UNRESOLVED:<v>, CONFLICTED:<v>,
                                        # ENTERPRISE_INVENTORY_MISSING:<v>, BAD_MODULE_NAME
    unresolved: dict = field(default_factory=dict)   # {version: (names,)}
    conflicted: dict = field(default_factory=dict)   # {version: (names,)}
    by_family: dict = field(default_factory=dict)    # {version: {"public": (names,), "enterprise": (names,)}}
    enterprise_dependent: bool = False
    enterprise_reached: int = 0         # distinct Enterprise modules reached: a count, never a name
    in_cycle: bool = False


@dataclass(frozen=True)
class UnifiedResolution:
    source: str
    target: str
    modules: dict                       # {module name: ModuleCoverage}, sorted by name

    def incomplete(self) -> dict:
        return {name: cov for name, cov in self.modules.items() if cov.verdict == INCOMPLETE}


def load_inventories(knowledge_root) -> dict:
    """{version label: verified inventory} for `<knowledge_root>/inventory/*.json`. Absent directory: {}."""
    directory = Path(knowledge_root) / INVENTORY_DIR
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise UnifiedError("INVENTORY_NOT_A_DIRECTORY", f"{INVENTORY_DIR} is not a directory")
    loaded: dict = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".json" or not path.is_file():
            raise UnifiedError("INVENTORY_UNEXPECTED_ENTRY", "the inventory directory holds a non-inventory entry")
        label = path.stem
        if not _LABEL.fullmatch(label):
            raise UnifiedError("INVENTORY_BAD_NAME", f"{path.name} does not name a version")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UnifiedError("INVENTORY_UNREADABLE", f"{path.name}: {type(exc).__name__}") from None
        findings = _inventory.verify_inventory(document)
        if findings:
            # The finding's pointer may name an inventory module, so only its code is reported.
            raise UnifiedError("INVENTORY_INVALID", f"{path.name}: {findings[0]['code']}")
        loaded[label] = document
    return loaded


def _families(inventory) -> dict:
    return {source["source_id"]: source["confidentiality"] for source in inventory["sources"]}


def _has_enterprise(inventory) -> bool:
    return any(source["confidentiality"] == "enterprise" for source in inventory["sources"])


def resolve_custom(inventories, source_version: str, target_version: str, custom_modules) -> UnifiedResolution:
    """Coverage of every custom module. `custom_modules` maps a module name to its `depends` names."""
    if not isinstance(custom_modules, dict):
        raise UnifiedError("BAD_CUSTOM_MODULES", "custom modules must be a mapping of name to dependency list")
    versions = (source_version, target_version)
    valid = {name: list(deps) for name, deps in custom_modules.items() if _MODULE.fullmatch(name)}
    sides: dict = {}
    for version in versions:
        inventory = inventories.get(version)
        if inventory is None:
            sides[version] = None
            continue
        sides[version] = (inventory, _inventory.resolve(inventory, valid))
    modules: dict = {}
    for name in sorted(custom_modules):
        if name not in valid:
            modules[name] = ModuleCoverage(name=name, verdict=INCOMPLETE, reasons=("BAD_MODULE_NAME",))
            continue
        reasons: set = set()
        unresolved: dict = {}
        conflicted: dict = {}
        by_family: dict = {}
        enterprise_names: set = set()
        enterprise_dependent = False
        in_cycle = False
        for version in versions:
            side = sides[version]
            if side is None:
                reasons.add(f"INVENTORY_MISSING:{version}")
                continue
            inventory, result = side
            families = _families(inventory)
            grouped: dict = {}
            for source_id, names in result["resolved"][name]["by_source"].items():
                family = families[source_id]
                grouped.setdefault(family, []).extend(names)
                if family == "enterprise":
                    enterprise_names.update(names)
            by_family[version] = {family: tuple(sorted(names)) for family, names in grouped.items()}
            if result["unresolved"].get(name):
                unresolved[version] = tuple(result["unresolved"][name])
                reasons.add(f"UNRESOLVED:{version}")
            if result["conflicted"].get(name):
                conflicted[version] = tuple(result["conflicted"][name])
                reasons.add(f"CONFLICTED:{version}")
            if name in result["enterprise_dependent"]:
                enterprise_dependent = True
            if any(name in cycle for cycle in result["cycles"]):
                in_cycle = True
        if enterprise_dependent:
            for version in versions:
                side = sides[version]
                if side is not None and not _has_enterprise(side[0]):
                    reasons.add(f"ENTERPRISE_INVENTORY_MISSING:{version}")
        modules[name] = ModuleCoverage(
            name=name, verdict=INCOMPLETE if reasons else COMPLETE, reasons=tuple(sorted(reasons)),
            unresolved=unresolved, conflicted=conflicted, by_family=by_family,
            enterprise_dependent=enterprise_dependent, enterprise_reached=len(enterprise_names), in_cycle=in_cycle)
    return UnifiedResolution(source=source_version, target=target_version, modules=modules)


def migration_coverage(knowledge_tree, source_version: str, target_version: str, custom_modules):
    """None when neither version of the migration has an inventory (the flow is exactly today's). Otherwise the
    resolution. Raises `UnifiedError` when any inventory in the tree does not verify."""
    inventories = load_inventories(knowledge_tree)
    if source_version not in inventories and target_version not in inventories:
        return None
    return resolve_custom(inventories, source_version, target_version, custom_modules)


def coverage_message(cov: ModuleCoverage) -> str:
    parts = []
    for version in sorted(cov.unresolved):
        parts.append(f"unresolved dependencies on {version}: {', '.join(cov.unresolved[version])}")
    for version in sorted(cov.conflicted):
        parts.append(f"dependencies in conflict on {version}: {', '.join(cov.conflicted[version])}")
    for reason in cov.reasons:
        code, _, version = reason.partition(":")
        if code == "INVENTORY_MISSING":
            parts.append(f"no module inventory for {version} in the active release")
        elif code == "ENTERPRISE_INVENTORY_MISSING":
            parts.append(f"Enterprise module inventory for {version} is not in the active release")
        elif code == "BAD_MODULE_NAME":
            parts.append("the module name cannot be matched in the inventory")
    if cov.enterprise_dependent:
        parts.append(f"{cov.enterprise_reached} Enterprise module(s) reached")
    return ("dependency coverage is INCOMPLETE: " + "; ".join(parts)
            + ". Auto-fix edits are withheld for this module; detection still runs.")


def withheld_records(resolution: UnifiedResolution) -> dict:
    """{module name: {"reasons", "message"}} for INCOMPLETE modules. This is what a migrate run stores in its state."""
    return {name: {"reasons": list(cov.reasons), "message": coverage_message(cov)}
            for name, cov in sorted(resolution.incomplete().items())}
