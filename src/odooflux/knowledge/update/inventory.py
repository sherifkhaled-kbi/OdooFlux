"""Unified Community + Enterprise module inventory and dependency resolver (feature 012, plan addendum B3).

Library only. Nothing here executes snapshot text: manifests are parsed with ``ast.parse`` and the single top-level
dict node is evaluated with ``ast.literal_eval`` (literal nodes only). A manifest that is not a literal dict is recorded
with a closed ``parse_error`` code and no dependencies; it is never partly trusted.

Shapes:
- ``build_part`` -> one source's part (``modules``, ``skipped``, ``parse_errors``). For ``confidentiality ==
  "enterprise"`` the part keeps module facts only (names, depends, flags, digests): no paths and no file contents.
- ``merge`` -> the unified inventory (``schemas/inventory.schema.json``). A module declared by two sources is a conflict:
  recorded, not resolved to either source.
- ``verify_inventory`` -> findings (empty list means consistent).
- ``resolve`` -> closure of custom modules over inventory and custom dependencies (unresolved / conflicted / cycles).
- ``carry_forward_compat`` -> dependency-existence check for carried Enterprise modules (plan B4). It checks existence
  only, never source verification.
"""

import ast
import functools
import hashlib
import json
import re
from pathlib import Path

from odooflux.dependencies.graph import topo_order
from odooflux.knowledge import validator as _validator
from odooflux.knowledge.release.canonical import CanonicalError, digest_obj

SCHEMA_ID = "odooflux.inventory/1"
MAX_MANIFEST_BYTES = 256 * 1024
MANIFEST_NAME = "__manifest__.py"
MANIFEST_SUFFIX = "/" + MANIFEST_NAME
CONFIDENTIALITY = ("public", "enterprise")
PARSE_ERROR_CODES = ("TOO_LARGE", "SYNTAX", "NOT_A_DICT_LITERAL", "NOT_LITERAL", "DUPLICATE_KEY", "BAD_DEPENDS",
                     "BAD_FLAG", "DUPLICATE_IN_SOURCE")

_NAME_RE = re.compile(r"[a-z0-9_]{1,64}")
_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}")
_PART_RECORD_KEYS = frozenset({"depends", "installable", "auto_install", "manifest_digest", "path_digest"})
_PART_KEYS = frozenset({"source_id", "confidentiality", "modules", "skipped", "skipped_nested", "parse_errors"})
_MODULE_KEYS = frozenset({"source_id", "confidentiality", "depends", "installable", "auto_install", "manifest_digest"})


class InventoryError(ValueError):
    """Malformed input to the inventory API (never raised for a bad manifest, which becomes a parse_error record)."""


def _is_name(value) -> bool:
    return isinstance(value, str) and _NAME_RE.fullmatch(value) is not None


def _is_source_id(value) -> bool:
    return isinstance(value, str) and _SOURCE_RE.fullmatch(value) is not None


def _valid_names(seq) -> bool:
    return isinstance(seq, (list, tuple)) and all(_is_name(item) for item in seq)


def _check_confidentiality(value) -> None:
    if value not in CONFIDENTIALITY:
        raise InventoryError(f"confidentiality must be one of {CONFIDENTIALITY}, not {value!r}")


def _check_source_id(value) -> None:
    if not _is_source_id(value):
        raise InventoryError(f"invalid source_id {value!r}")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_manifest(data: bytes):
    """Return (literal dict, None) or (None, parse_error code). Never executes anything."""
    try:
        tree = ast.parse(data, filename=MANIFEST_NAME, mode="exec")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None, "SYNTAX"
    body = tree.body
    if len(body) != 1 or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Dict):
        return None, "NOT_A_DICT_LITERAL"
    node = body[0].value
    seen = set()
    for key in node.keys:
        if isinstance(key, ast.Constant):
            if key.value in seen:
                return None, "DUPLICATE_KEY"
            seen.add(key.value)
    try:
        value = ast.literal_eval(node)  # literal nodes only: a Call/Name/Attribute raises ValueError here
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None, "NOT_LITERAL"
    if not isinstance(value, dict):
        return None, "NOT_A_DICT_LITERAL"
    return value, None


def _error_record(code: str, manifest_digest: str, path_digest: str) -> dict:
    return {"depends": [], "installable": False, "auto_install": False, "manifest_digest": manifest_digest,
            "path_digest": path_digest, "parse_error": code}


def _read_record(entry: dict, store) -> dict:
    path = entry["path"]
    manifest_digest = entry["sha256"]
    path_digest = _sha256_hex(path.encode("utf-8"))
    if entry["size"] > MAX_MANIFEST_BYTES:
        return _error_record("TOO_LARGE", manifest_digest, path_digest)
    data = store.get(manifest_digest)  # verify-on-read; a corrupt blob raises SourceError(SNAPSHOT_CORRUPT)
    if len(data) > MAX_MANIFEST_BYTES:
        return _error_record("TOO_LARGE", manifest_digest, path_digest)
    value, code = _parse_manifest(data)
    if value is None:
        return _error_record(code, _sha256_hex(data), path_digest)
    depends = value.get("depends", [])
    if not _valid_names(depends):
        return _error_record("BAD_DEPENDS", _sha256_hex(data), path_digest)
    installable = value.get("installable", True)
    if not isinstance(installable, bool):
        return _error_record("BAD_FLAG", _sha256_hex(data), path_digest)
    auto_install = value.get("auto_install", False)
    if isinstance(auto_install, bool):
        auto_bool = auto_install
    elif _valid_names(auto_install):
        auto_bool = len(auto_install) > 0
    else:
        return _error_record("BAD_FLAG", _sha256_hex(data), path_digest)
    return {"depends": sorted(set(depends)), "installable": installable, "auto_install": auto_bool,
            "manifest_digest": _sha256_hex(data), "path_digest": path_digest}


def _module_name(path: str):
    """Module name for a manifest path, or None when the path is not one of the three recognised module roots:
    `<m>/__manifest__.py` (repo root, any source), `addons/<m>/__manifest__.py` and
    `odoo/addons/<m>/__manifest__.py` (Community layouts). Anything deeper is not a module root."""
    dirs = path.split("/")[:-1]
    if len(dirs) == 1:
        return dirs[0]
    if len(dirs) == 2 and dirs[0] == "addons":
        return dirs[1]
    if len(dirs) == 3 and dirs[0] == "odoo" and dirs[1] == "addons":
        return dirs[2]
    return None


def build_part(snapshot, store, *, source_id, confidentiality) -> dict:
    """Module facts of one source snapshot. Only the three module roots in `_module_name` are modules; the module name is
    the module directory name and must match the name rule (else `skipped`). Manifests deeper than those roots are
    ignored and counted in `skipped_nested`. A root-level `__manifest__.py` is counted in `skipped`."""
    _check_source_id(source_id)
    _check_confidentiality(confidentiality)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("entries"), list):
        raise InventoryError("snapshot must carry an entries list")
    if snapshot.get("source_id") != source_id:
        raise InventoryError(f"snapshot source_id {snapshot.get('source_id')!r} != {source_id!r}")
    skipped = 0
    skipped_nested = 0
    found: dict = {}
    for entry in sorted(snapshot["entries"], key=lambda e: e["path"]):
        path = entry["path"]
        if path == MANIFEST_NAME:
            skipped += 1  # manifest at the tree root: no module directory
            continue
        if not path.endswith(MANIFEST_SUFFIX):
            continue
        name = _module_name(path)
        if name is None:
            skipped_nested += 1  # not a module root: never a module
            continue
        if not _is_name(name):
            skipped += 1
            continue
        found.setdefault(name, []).append((path, _read_record(entry, store)))
    modules: dict = {}
    parse_errors = []
    for name in sorted(found):
        occurrences = found[name]
        if len(occurrences) > 1:
            # Two manifests claim one module name inside one source: neither is chosen; the record is an error.
            record = _error_record("DUPLICATE_IN_SOURCE",
                                   digest_obj(sorted(rec["manifest_digest"] for _, rec in occurrences)),
                                   digest_obj(sorted(_sha256_hex(p.encode("utf-8")) for p, _ in occurrences)))
        else:
            record = occurrences[0][1]
        modules[name] = record
        if "parse_error" in record:
            parse_errors.append(name)
    return {"source_id": source_id, "confidentiality": confidentiality, "modules": modules, "skipped": skipped,
            "skipped_nested": skipped_nested, "parse_errors": parse_errors}


def _check_part(part) -> None:
    if not isinstance(part, dict) or set(part) != _PART_KEYS:
        raise InventoryError("malformed part")
    problems = _validator.check(part, _schema()["$defs"]["part"])
    if problems:
        raise InventoryError(f"malformed part at {problems[0][0] or '/'}: {problems[0][1]}")
    for name, rec in part["modules"].items():
        if not _is_name(name) or not isinstance(rec, dict):
            raise InventoryError(f"malformed part module {name!r}")
        keys = set(rec)
        code = rec.get("parse_error")
        if keys - {"parse_error"} != _PART_RECORD_KEYS or (code is not None and code not in PARSE_ERROR_CODES):
            raise InventoryError(f"malformed part record {name!r}")
    expected = sorted(n for n, rec in part["modules"].items() if "parse_error" in rec)
    if part["parse_errors"] != expected:
        raise InventoryError("parse_errors does not match the module records")


def merge(parts) -> dict:
    """Unified inventory from source parts. Modules declared by two or more sources are conflicts, not resolved."""
    if not isinstance(parts, (list, tuple)):
        raise InventoryError("parts must be a list")
    for part in parts:
        _check_part(part)
    sources = sorted(({"source_id": p["source_id"], "confidentiality": p["confidentiality"]} for p in parts),
                     key=lambda s: s["source_id"])
    ids = [s["source_id"] for s in sources]
    if len(set(ids)) != len(ids):
        raise InventoryError("duplicate source_id among parts")
    by_name: dict = {}
    for part in parts:
        for name, rec in part["modules"].items():
            by_name.setdefault(name, []).append((part["source_id"], part["confidentiality"], rec))
    modules: dict = {}
    conflicts: list = []
    unparsed: list = []
    for name in sorted(by_name):
        entries = sorted(by_name[name], key=lambda e: e[0])
        if len(entries) > 1:
            conflicts.append({"module": name, "sources": [e[0] for e in entries]})
            continue
        source_id, confidentiality, rec = entries[0]
        if "parse_error" in rec:
            unparsed.append({"module": name, "source_id": source_id, "code": rec["parse_error"]})
            continue
        modules[name] = {"source_id": source_id, "confidentiality": confidentiality,
                         "depends": list(rec["depends"]), "installable": rec["installable"],
                         "auto_install": rec["auto_install"], "manifest_digest": rec["manifest_digest"]}
    inventory = {"schema": SCHEMA_ID, "sources": sources, "modules": modules, "conflicts": conflicts,
                 "unparsed": unparsed}
    inventory["digest"] = digest_obj(inventory)
    return inventory


@functools.lru_cache(maxsize=1)
def _schema() -> dict:
    path = Path(__file__).resolve().parents[1] / "schemas" / "inventory.schema.json"  # static package data, not knowledge content
    return json.loads(path.read_text(encoding="utf-8"))


def _body(inventory: dict) -> dict:
    return {key: value for key, value in inventory.items() if key != "digest"}


def verify_inventory(inventory) -> list:
    """Findings for an inventory. An empty list means: schema shape ok, digest recomputes, conflicts consistent,
    modules reference declared sources only, and enterprise records carry no extra keys."""
    findings: list = []

    def add(code: str, where: str, detail: str) -> None:
        findings.append({"code": code, "where": where, "detail": detail})

    if not isinstance(inventory, dict):
        return [{"code": "NOT_A_MAPPING", "where": "", "detail": "inventory must be a JSON object"}]
    schema = _schema()
    problems = _validator.check(inventory, schema)
    for pointer, message in problems:
        add("SCHEMA", pointer or "/", message)
    if problems:
        return findings  # structure is unreliable beyond this point
    declared = {s["source_id"]: s["confidentiality"] for s in inventory["sources"]}
    source_ids = [s["source_id"] for s in inventory["sources"]]
    if len(set(source_ids)) != len(source_ids) or source_ids != sorted(source_ids):
        add("ORDER", "/sources", "sources must be unique and sorted by source_id")
    conflicted = {c["module"]: c["sources"] for c in inventory["conflicts"]}
    unparsed_names = {u["module"] for u in inventory["unparsed"]}
    module_schema = schema["$defs"]["module"]
    names = list(inventory["modules"])
    if names != sorted(names):
        add("ORDER", "/modules", "modules must be sorted by name")
    for name in names:
        record = inventory["modules"][name]
        where = f"/modules/{name}"
        if not _is_name(name):
            add("BAD_MODULE_NAME", where, f"module name {name!r} is not allowed")
        record_problems = _validator.check(record, module_schema)
        for pointer, message in record_problems:
            add("SCHEMA", where + pointer, message)
        if record_problems:
            continue
        if record["source_id"] not in declared:
            add("UNKNOWN_SOURCE", where, f"source {record['source_id']!r} is not declared")
        elif declared[record["source_id"]] != record["confidentiality"]:
            add("CONFIDENTIALITY_MISMATCH", where, "record confidentiality differs from its declared source")
        if record["depends"] != sorted(set(record["depends"])):
            add("ORDER", where + "/depends", "depends must be sorted and unique")
        if name in conflicted or name in unparsed_names:
            add("CONFLICT_INCONSISTENT", where, "module is listed as conflicted or unparsed and also resolved")
    unparsed = inventory["unparsed"]
    if unparsed != sorted(unparsed, key=lambda u: (u["module"], u["source_id"])):
        add("ORDER", "/unparsed", "unparsed must be sorted by (module, source_id)")
    for item in unparsed:
        if item["source_id"] not in declared:
            add("UNKNOWN_SOURCE", f"/unparsed/{item['module']}", f"source {item['source_id']!r} is not declared")
        if item["module"] in inventory["modules"] or item["module"] in conflicted:
            add("CONFLICT_INCONSISTENT", f"/unparsed/{item['module']}", "unparsed module is also resolved")
    conflict_names = [c["module"] for c in inventory["conflicts"]]
    if conflict_names != sorted(conflict_names):
        add("ORDER", "/conflicts", "conflicts must be sorted by module")
    for item in inventory["conflicts"]:
        where = f"/conflicts/{item['module']}"
        srcs = item["sources"]
        if srcs != sorted(set(srcs)) or len(srcs) < 2:
            add("CONFLICT_INCONSISTENT", where, "conflict needs at least two sorted, unique sources")
        for src in srcs:
            if src not in declared:
                add("UNKNOWN_SOURCE", where, f"source {src!r} is not declared")
        if item["module"] in inventory["modules"]:
            add("CONFLICT_INCONSISTENT", where, "conflicted module must not also be resolved")
    try:
        recomputed = digest_obj(_body(inventory))
    except CanonicalError as exc:
        add("DIGEST_UNCOMPUTABLE", "/digest", str(exc))
    else:
        if recomputed != inventory["digest"]:
            add("DIGEST_MISMATCH", "/digest", "digest does not match the canonical digest of the content")
    return findings


def _require_valid(inventory, label: str) -> None:
    findings = verify_inventory(inventory)
    if findings:
        raise InventoryError(f"{label} fails verification: {findings[0]['code']} at {findings[0]['where']}")


def resolve(inventory, custom_modules) -> dict:
    """Closure of custom modules over inventory and custom-to-custom dependencies. Cross-repository chains are followed.

    `resolved[m]`: direct (sorted custom deps as given), transitive (closure minus direct and m), custom (reached custom
    modules), by_source (reached inventory modules grouped by source_id, direct included).
    `unresolved[m]`: reached names that are not in the inventory (or unparsed) and not custom. Explicit, never assumed.
    `conflicted[m]`: reached names that are conflicted between sources. Their dependencies are not expanded.
    `cycles`: strongly connected groups over the reached graph. `enterprise_dependent`: custom modules whose closure
    reaches an Enterprise module (or a conflict involving an Enterprise source).
    """
    _require_valid(inventory, "inventory")
    if not isinstance(custom_modules, dict):
        raise InventoryError("custom_modules must be a mapping of module name to dependency list")
    custom: dict = {}
    for name, deps in custom_modules.items():
        if not _is_name(name):
            raise InventoryError(f"invalid custom module name {name!r}")
        if not isinstance(deps, (list, tuple)) or not all(isinstance(d, str) for d in deps):
            raise InventoryError(f"dependencies of {name!r} must be a list of names")
        custom[name] = sorted(set(deps))
    modules = inventory["modules"]
    conflicts = {c["module"]: c["sources"] for c in inventory["conflicts"]}
    unparsed = {u["module"] for u in inventory["unparsed"]}
    confidentiality_of = {s["source_id"]: s["confidentiality"] for s in inventory["sources"]}

    def status(name: str) -> str:
        if name in custom and (name in modules or name in conflicts or name in unparsed):
            return "conflicted"  # a custom name that shadows an inventory name is ambiguous: not expanded
        if name in custom:
            return "custom"
        if name in conflicts:
            return "conflicted"
        if name in modules:
            return "inventory"
        return "unknown"

    def edges(name: str) -> list:
        kind = status(name)
        if kind == "custom":
            return custom[name]
        if kind == "inventory":
            return list(modules[name]["depends"])
        return []

    graph: dict = {}
    stack = list(custom)
    while stack:
        name = stack.pop()
        if name in graph:
            continue
        graph[name] = edges(name)
        stack.extend(graph[name])
    _, cycles, _ = topo_order(graph)

    def closure(root: str) -> set:
        seen: set = set()
        todo = [root]
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            todo.extend(graph[name])
        return seen

    def enterprise(name: str) -> bool:
        if name in modules and modules[name]["confidentiality"] == "enterprise":
            return True
        return name in conflicts and any(confidentiality_of.get(s) == "enterprise" for s in conflicts[name])

    resolved: dict = {}
    unresolved: dict = {}
    conflicted: dict = {}
    enterprise_dependent: list = []
    for root in sorted(custom):
        reach = closure(root)
        direct = custom[root]
        others = reach - {root}
        by_source: dict = {}
        for name in sorted(n for n in reach if status(n) == "inventory"):
            by_source.setdefault(modules[name]["source_id"], []).append(name)
        resolved[root] = {
            "direct": direct,
            "transitive": sorted(others - set(direct)),
            "custom": sorted(n for n in others if status(n) == "custom"),
            "by_source": {sid: by_source[sid] for sid in sorted(by_source)},
        }
        unknown = sorted(n for n in reach if status(n) == "unknown")
        if unknown:
            unresolved[root] = unknown
        conflicted_here = sorted(n for n in reach if status(n) == "conflicted")
        if conflicted_here:
            conflicted[root] = conflicted_here
        if any(enterprise(n) for n in reach):
            enterprise_dependent.append(root)
    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "conflicted": conflicted,
        "cycles": sorted(sorted(c) for c in cycles),
        "enterprise_dependent": sorted(enterprise_dependent),
    }


def carry_forward_compat(old_inventory, new_inventory, *, enterprise_only=True) -> list:
    """For each carried module (Enterprise only by default), every `depends` entry must still exist in the new unified
    inventory. Returns `[{"module", "missing": [...]}]`; an empty list means the existence check passed. This is
    dependency-checked, not source-verified."""
    _require_valid(old_inventory, "old inventory")
    _require_valid(new_inventory, "new inventory")
    findings = []
    for name in sorted(old_inventory["modules"]):
        record = old_inventory["modules"][name]
        if enterprise_only and record["confidentiality"] != "enterprise":
            continue
        missing = sorted(dep for dep in record["depends"] if dep not in new_inventory["modules"])
        if missing:
            findings.append({"module": name, "missing": missing})
    return findings
