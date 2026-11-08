"""L3 dependency integrity (REQ-VAL-003, REQ-DEP-003, FR-003).

Static checks of module references against the scanned modules and the target version's core module
list. Files are only parsed: Python with ``ast``, XML with ``xml.etree``, CSV with ``csv``, manifests with
``ast.literal_eval`` (through ``read_manifest``). Nothing from the scanned tree is imported or executed.

Reference rules (a reference is checked only when its owner is decidable):
- ``depends``: satisfied by a scanned module or by the core list for the target. Otherwise
  ``integrity.missing_module`` (WARNING): it may be an Enterprise module, which is not indexed (D-05).
- XML IDs (``ref=``, ``eval="ref(...)"``, ``inherit_id``, menu ``parent``/``action``, CSV ``*:id``
  columns, ``env.ref``): an unqualified ID belongs to the module itself; a qualified ``mod.xid`` belongs to
  ``mod``. Checked only when the owner is scanned: ``integrity.dangling_xml_id``.
- Groups (``groups=``, ``group_id``/``groups_id`` refs, CSV ``group_id:id``): same owner rule, reported as
  ``integrity.missing_group``.
- Models (``env['x']``, ``_inherit``, relational comodels, ``model=`` on records, ``model_*`` XML IDs):
  checked only when the model name is in the owning module's namespace (``<module>.`` prefix). Reported as
  ``integrity.dangling_model`` when no scanned module defines it with ``_name``.
- Fields: names used in view architectures and record fields are checked against the model's declared
  ``fields.*`` attributes only when the model is defined by scanned modules and has no non-local parent.
  Reported as ``integrity.dangling_field``.
- Python packages: a top-level third-party import not listed in ``external_dependencies.python``, and
  not stdlib, not ``odoo``, not a local name: ``integrity.missing_python_package`` (WARNING). Packages that
  Odoo itself requires are not indexed, so they can be reported.

Limitations: references that cannot be decided are counted and named in the ValidationResult reason. The
layer ran, so an all-decided-clean run is PASS and undecided references are carried as limits (the report's
verification scope states them, REQ-BIZ-003). FAIL when a broken reference was found. UNAVAILABLE only when
no module could be read.
"""

import ast
import csv
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from odooflux.core.contracts.records import Finding, ValidationResult
from odooflux.discovery.manifest import MANIFEST_NAMES, read_manifest
from odooflux.discovery.modules import iter_module_files
from odooflux.knowledge.loader import KNOWLEDGE_ROOT
from odooflux.utils.astnodes import all_nodes, parse as parse_cached

CORE_MODULES_FILE = KNOWLEDGE_ROOT / "compatibility" / "core_modules.json"
ENTERPRISE_MODULES_FILE = KNOWLEDGE_ROOT / "compatibility" / "enterprise_modules.json"
DATA_KEYS = ("data", "demo", "init_xml", "update_xml", "demo_xml")
GROUP_FIELDS = frozenset({"groups_id", "group_id", "group_ids"})
ORM_FIELDS = frozenset({"id", "display_name", "create_uid", "create_date", "write_uid", "write_date",
                        "__last_update"})
RELATIONAL = frozenset({"Many2one", "One2many", "Many2many"})
STDLIB = frozenset(sys.stdlib_module_names)
PY_IMPORT_ALIASES = {"python_dateutil": "dateutil", "pillow": "pil", "pyyaml": "yaml", "pyjwt": "jwt",
                     "beautifulsoup4": "bs4"}
REF_CALL = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")

RULES = {
    "missing_module": ("integrity.missing_module", "WARNING"),
    "dangling_model": ("integrity.dangling_model", "CRITICAL"),
    "dangling_field": ("integrity.dangling_field", "CRITICAL"),
    "dangling_xml_id": ("integrity.dangling_xml_id", "CRITICAL"),
    "missing_group": ("integrity.missing_group", "CRITICAL"),
    "missing_python_package": ("integrity.missing_python_package", "WARNING"),
}


def load_core_modules(target_version: str) -> Optional[frozenset]:
    """Top-level core addon names for a target version, or None when no list is shipped for it."""
    if not CORE_MODULES_FILE.is_file():
        return None
    data = json.loads(CORE_MODULES_FILE.read_text(encoding="utf-8"))
    for record in data.get("versions", []):
        if record.get("id") == target_version:
            return frozenset(record.get("modules", []))
    return None


def load_enterprise_modules() -> frozenset:
    """Enterprise-only module names (seed list, D-05). A dependency on one is INFO, not WARNING."""
    if not ENTERPRISE_MODULES_FILE.is_file():
        return frozenset()
    data = json.loads(ENTERPRISE_MODULES_FILE.read_text(encoding="utf-8"))
    return frozenset(m for m in data.get("modules", []) if isinstance(m, str))


@dataclass
class _Module:
    name: str
    root: Path
    manifest_path: str
    manifest_text: str
    depends: tuple
    declared_imports: frozenset
    local_names: frozenset
    xml_docs: list = field(default_factory=list)     # (path str, text, root element)
    csv_docs: list = field(default_factory=list)     # (path str, text, rows)
    py_docs: list = field(default_factory=list)      # (path str, text, ast tree)


@dataclass
class _ClassInfo:
    name_attr: Optional[str]
    inherit: tuple
    inherit_line: int
    has_inherits: bool
    fields: frozenset
    comodels: tuple       # ((model name, line), ...)


def _line_of(text: str, needle: str, default: int = 1) -> int:
    if not needle:
        return default
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else default


def _str_const(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _str_list(node) -> tuple:
    single = _str_const(node)
    if single is not None:
        return (single,)
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(v for v in (_str_const(e) for e in node.elts) if v is not None)
    return ()


def _is_fields_call(call: ast.Call) -> bool:
    return (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "fields")


def _comodel_of(call: ast.Call) -> Optional[str]:
    if call.func.attr not in RELATIONAL:
        return None
    if call.args and _str_const(call.args[0]) is not None:
        return _str_const(call.args[0])
    for kw in call.keywords:
        if kw.arg == "comodel_name":
            return _str_const(kw.value)
    return None


def _class_info(node: ast.ClassDef) -> Optional[_ClassInfo]:
    name_attr, inherit, inherit_line, has_inherits = None, (), node.lineno, False
    fields, comodels = set(), []
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target, value = stmt.targets[0].id, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            target, value = stmt.target.id, stmt.value
        else:
            continue
        if target == "_name":
            name_attr = _str_const(value)
        elif target == "_inherit":
            inherit, inherit_line = _str_list(value), value.lineno
        elif target == "_inherits":
            has_inherits = True
        elif isinstance(value, ast.Call) and _is_fields_call(value):
            fields.add(target)
            comodel = _comodel_of(value)
            if comodel:
                comodels.append((comodel, value.lineno))
    if name_attr is None and not inherit:
        return None
    return _ClassInfo(name_attr, inherit, inherit_line, has_inherits, frozenset(fields), tuple(comodels))


def _is_env(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "env") or (isinstance(node, ast.Name) and node.id == "env")


def _arch_fields(elem):
    """(name, element) for field elements of a view architecture; does not descend into fields."""
    for child in elem:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "field":
            if child.get("name"):
                yield child.get("name"), child
        elif child.tag != "xpath":
            yield from _arch_fields(child)


def _load_module(root: Path):
    """(module, notes): module is None when its manifest cannot be read. notes are undecided kinds."""
    notes = []
    manifest_file = next((root / n for n in MANIFEST_NAMES if (root / n).is_file()), None)
    if manifest_file is None:
        return None, [f"manifest unreadable ({root.name}: no manifest)"]
    manifest, error = read_manifest(manifest_file)
    if error:
        return None, [f"manifest unreadable ({root.name}: {error})"]
    depends = tuple(d for d in (manifest.get("depends") or []) if isinstance(d, str))
    ext = manifest.get("external_dependencies") or {}
    declared = set()
    for pkg in (ext.get("python") or []) if isinstance(ext, dict) else []:
        if isinstance(pkg, str):
            norm = pkg.strip().lower().replace("-", "_")
            declared |= {norm, PY_IMPORT_ALIASES.get(norm, norm)}
    local = {root.name} | {p.name for p in root.iterdir() if p.is_dir()} | {p.stem for p in root.glob("*.py")}
    module = _Module(name=root.name, root=root, manifest_path=str(manifest_file),
                     manifest_text=manifest_file.read_text(encoding="utf-8", errors="replace"),
                     depends=depends, declared_imports=frozenset(declared), local_names=frozenset(local))
    files = {str(p): p for p in iter_module_files(root)}
    for key in DATA_KEYS:
        for rel in manifest.get(key) or []:
            if not isinstance(rel, str):
                continue
            if not rel.endswith((".xml", ".csv")):
                notes.append("data files other than XML and CSV")
                continue
            path = root / rel
            if not path.is_file():
                notes.append("declared data files missing")
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if rel.endswith(".xml"):
                try:
                    module.xml_docs.append((str(path), text, ET.fromstring(path.read_bytes())))
                except ET.ParseError:
                    notes.append("XML/CSV/Python files not parsed")
            else:
                rows = list(csv.DictReader(io.StringIO(text)))
                module.csv_docs.append((str(path), text, rows))
    for path_str, path in sorted(files.items()):
        if path.suffix != ".py" or path.name in MANIFEST_NAMES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            module.py_docs.append((path_str, text, parse_cached(text, path_str)))
        except (SyntaxError, ValueError):
            notes.append("XML/CSV/Python files not parsed")
    return module, notes


class _Checker:
    def __init__(self, modules, core):
        self.modules = modules
        self.scanned = {m.name for m in modules}
        self.core = core
        self.enterprise = load_enterprise_modules()
        self.xids = set()
        self.named = set()
        self.model_xids = {}
        self.fields_of = defaultdict(set)
        self.parents_of = defaultdict(set)
        self.not_closed = set()
        self._closure_cache = {}
        self.findings = []
        self.undecided = Counter()

    # --- bookkeeping -------------------------------------------------------------------------
    def undecide(self, kind: str):
        self.undecided[kind] += 1

    def finding(self, kind: str, path: str, line: int, matched: str, message: str, severity: Optional[str] = None):
        rule, default_severity = RULES[kind]
        severity = severity or default_severity
        self.findings.append(Finding(rule_id=rule, path=path, line=line, severity=severity,
                                     message=message, suggestion="fix the reference or declare its module",
                                     matched=matched))

    def _owned(self, model: str) -> bool:
        return "." in model and model.split(".")[0] in self.scanned

    # --- pass 1: index ----------------------------------------------------------------------
    def index(self):
        for m in self.modules:
            for _path, _text, root in m.xml_docs:
                for el in root.iter():
                    value = el.get("id")
                    if value:
                        self.xids.add(value if "." in value else f"{m.name}.{value}")
            for _path, _text, rows in m.csv_docs:
                for row in rows:
                    value = (row.get("id") or "").strip()
                    if value:
                        self.xids.add(value if "." in value else f"{m.name}.{value}")
        classes = []
        for m in self.modules:
            for _path, _text, tree in m.py_docs:
                for node in all_nodes(tree):
                    if isinstance(node, ast.ClassDef):
                        info = _class_info(node)
                        if info is not None:
                            classes.append(info)
        for info in classes:
            if info.name_attr:
                self.named.add(info.name_attr)
                targets = [info.name_attr]
                self.parents_of[info.name_attr] |= set(info.inherit) - {info.name_attr}
            else:
                targets = list(info.inherit)
                for target in targets:
                    self.parents_of[target] |= set(info.inherit) - {target}
            for target in targets:
                self.fields_of[target] |= info.fields
                if info.has_inherits:
                    self.not_closed.add(target)
        self.model_xids = {"model_" + name.replace(".", "_"): name for name in self.named}
        self.classes = classes

    def _closure(self, model: str):
        """(fully defined by scanned modules, fields including parents)."""
        if model in self._closure_cache:
            return self._closure_cache[model]
        self._closure_cache[model] = (False, frozenset())  # cycle guard: undecided while in progress
        ok = model in self.named and model not in self.not_closed
        fields = set(self.fields_of.get(model, ()))
        for parent in self.parents_of.get(model, ()):
            parent_ok, parent_fields = self._closure(parent)
            ok = ok and parent_ok
            fields |= parent_fields
        result = (ok, frozenset(fields))
        self._closure_cache[model] = result
        return result

    # --- reference checks -------------------------------------------------------------------
    def model_ref(self, model: str, path: str, line: int):
        if not self._owned(model):
            self.undecide("model references outside scanned modules")
            return
        if model not in self.named:
            self.finding("dangling_model", path, line, model,
                         f"model {model!r} is not defined by any scanned module")

    def _model_xid_ref(self, mod: str, xid: str, path: str, line: int):
        if mod and f"{mod}.{xid}" in self.xids or xid in self.model_xids:
            return
        owner = [s for s in self.scanned if xid.startswith("model_" + s + "_")]
        if not owner:
            self.undecide("model xids outside scanned modules")
            return
        self.finding("dangling_model", path, line, xid,
                     f"model XML ID {xid!r} does not match any model defined by scanned modules")

    def xid_ref(self, kind: str, value: str, owner: str, path: str, line: int):
        value = value.strip().lstrip("!")
        if not value or "%" in value:
            return
        mod, xid = value.split(".", 1) if "." in value else (owner, value)
        qualified = f"{mod}.{xid}"
        if kind != "group" and xid.startswith("model_"):
            if qualified in self.xids:
                return
            self._model_xid_ref(mod, xid, path, line)
            return
        if mod not in self.scanned:
            self.undecide("group references into modules not scanned" if kind == "group"
                          else "xml id references into modules not scanned")
            return
        if qualified in self.xids:
            return
        if kind == "group":
            self.finding("missing_group", path, line, value,
                         f"group {value!r} is not defined by its owning scanned module")
        else:
            self.finding("dangling_xml_id", path, line, value,
                         f"XML ID {value!r} is not defined by its owning scanned module")

    def check_view_fields(self, model: str, names, path: str, text: str, report_unowned: bool):
        if not self._owned(model):
            if report_unowned:
                self.undecide("view fields of models outside scanned modules")
            return
        if model not in self.named:
            return  # reported as dangling_model
        ok, fields = self._closure(model)
        if not ok:
            self.undecide("view fields of models not fully defined by scanned modules")
            return
        allowed = fields | ORM_FIELDS
        for name, _el in names:
            if "." in name or name in allowed:
                continue
            self.finding("dangling_field", path, _line_of(text, f'"{name}"'), name,
                         f"field {name!r} is not declared on model {model!r}")

    # --- pass 2: references -------------------------------------------------------------------
    def check_module_dependencies(self, m: _Module, core_known: bool, target: str):
        for dep in m.depends:
            if dep in self.scanned:
                continue
            if dep in self.enterprise:
                self.finding("missing_module", m.manifest_path, _line_of(m.manifest_text, dep), dep,
                             f"module {m.name!r} depends on {dep!r}: an Enterprise module. odoo/enterprise is not "
                             f"accessible (D-05), so it is not indexed or runtime-validated", severity="INFO")
                continue
            if not core_known:
                self.undecide(f"dependencies without a core module list for {target}")
                continue
            if dep in self.core:
                continue
            self.finding("missing_module", m.manifest_path, _line_of(m.manifest_text, dep), dep,
                         f"module {m.name!r} depends on {dep!r}: not a scanned module nor a core module "
                         f"for {target} (it may be an Enterprise module, which is not indexed)")

    def check_python_packages(self, m: _Module):
        for path, _text, tree in m.py_docs:
            seen = set()
            for node in all_nodes(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for full in names:
                    top = full.split(".")[0]
                    norm = top.lower().replace("-", "_")
                    if not top or top in seen or top in STDLIB or top in ("odoo", "openerp"):
                        continue
                    if top in m.local_names or norm in m.declared_imports:
                        continue
                    seen.add(top)
                    self.finding("missing_python_package", path, node.lineno, top,
                                 f"module {m.name!r} imports {top!r}, which is not declared in "
                                 f"external_dependencies.python")

    def check_python_refs(self, m: _Module):
        for path, _text, tree in m.py_docs:
            for info in self.classes_of(tree):
                for parent in info.inherit:
                    if parent != info.name_attr:
                        self.model_ref(parent, path, info.inherit_line)
                for comodel, line in info.comodels:
                    self.model_ref(comodel, path, line)
            for node in all_nodes(tree):
                if isinstance(node, ast.Subscript) and _is_env(node.value):
                    key = _str_const(node.slice)
                    if key is not None:
                        self.model_ref(key, path, node.lineno)
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "ref" and _is_env(node.func.value) and node.args):
                    value = _str_const(node.args[0])
                    if value and "." in value:
                        self.xid_ref("xid", value, m.name, path, node.lineno)

    def classes_of(self, tree):
        return [info for info in (_class_info(n) for n in all_nodes(tree) if isinstance(n, ast.ClassDef))
                if info is not None]

    def check_xml(self, m: _Module):
        for path, text, root in m.xml_docs:
            for el in root.iter():
                name = el.get("name") if el.tag == "field" else None
                ref_kind = "group" if name in GROUP_FIELDS else "xid"
                if el.get("ref") is not None:
                    self.xid_ref(ref_kind, el.get("ref"), m.name, path, _line_of(text, el.get("ref")))
                if el.get("eval"):
                    for value in REF_CALL.findall(el.get("eval")):
                        self.xid_ref(ref_kind, value, m.name, path, _line_of(text, value))
                if el.get("groups"):
                    for value in el.get("groups").split(","):
                        self.xid_ref("group", value, m.name, path, _line_of(text, value))
                if el.get("inherit_id"):
                    self.xid_ref("xid", el.get("inherit_id"), m.name, path, _line_of(text, el.get("inherit_id")))
                if el.tag == "menuitem":
                    for attr in ("parent", "action"):
                        if el.get(attr):
                            self.xid_ref("xid", el.get(attr), m.name, path, _line_of(text, el.get(attr)))
            for record in root.iter("record"):
                self._check_record(record, path, text)

    def _check_record(self, record, path: str, text: str):
        model = record.get("model")
        fields = [f for f in record if f.tag == "field"]
        by_name = {f.get("name"): f for f in fields}
        if model == "ir.ui.view":
            target_el = by_name.get("model")
            target = (target_el.text or "").strip() if target_el is not None else ""
            if target and self._owned(target):
                self.model_ref(target, path, _line_of(text, target))
            arch = by_name.get("arch")
            if arch is None or not target or arch.get("type", "xml") != "xml":
                return
            if "inherit_id" in by_name or record.get("inherit_id"):
                self.undecide("inherited view architectures")
                return
            root_el = next((c for c in arch if isinstance(c.tag, str)), None)
            if root_el is not None:
                self.check_view_fields(target, _arch_fields(root_el), path, text, report_unowned=True)
            return
        if model and self._owned(model):
            self.model_ref(model, path, _line_of(text, model))
            names = [(f.get("name"), f) for f in fields if f.get("name")]
            self.check_view_fields(model, names, path, text, report_unowned=False)

    def check_csv(self, m: _Module):
        for path, text, rows in m.csv_docs:
            for row in rows:
                for col, value in row.items():
                    if not col or value is None or ":" not in col:
                        continue
                    base, _, suffix = col.partition(":")
                    if suffix != "id":
                        continue
                    kind = "group" if base in GROUP_FIELDS else "xid"
                    for part in value.split(","):
                        if part.strip():
                            self.xid_ref(kind, part, m.name, path, _line_of(text, part.strip()))


def _outcome(findings, undecided: Counter, target: str) -> ValidationResult:
    limits = "; ".join(f"{kind} ({count})" for kind, count in sorted(undecided.items()))
    blocking = [f for f in findings if f.severity != "INFO"]   # INFO never fails the layer (T019)
    info = [f for f in findings if f.severity == "INFO"]
    if blocking:
        kinds = Counter(f.rule_id.split(".", 1)[1] for f in blocking)
        reason = f"{len(blocking)} broken reference(s): " + ", ".join(f"{k} x{n}" for k, n in sorted(kinds.items()))
        if limits:
            reason += f"; undecided: {limits}"
        return ValidationResult(layer=3, outcome="FAIL", reason=reason)
    notes = []
    if info:
        notes.append(f"{len(info)} Enterprise dependency not indexed (D-05)")
    if undecided:
        notes.append(f"limits: undecided {limits}")
    if notes:
        return ValidationResult(layer=3, outcome="PASS",
                                reason="no broken reference among decided references; " + "; ".join(notes))
    return ValidationResult(layer=3, outcome="PASS")


def check_integrity(module_paths, *, target_version, core_modules=None):
    """Return (findings, ValidationResult(layer=3)) for the given module directories."""
    notes = []
    modules = []
    for raw in module_paths:
        module, module_notes = _load_module(Path(raw))
        notes += module_notes
        if module is not None:
            modules.append(module)
    if not modules:
        return [], ValidationResult(layer=3, outcome="UNAVAILABLE",
                                    reason="no module with a readable manifest in module_paths")
    core = frozenset(core_modules) if core_modules is not None else load_core_modules(target_version)
    checker = _Checker(modules, core)
    for kind in notes:
        checker.undecide(kind)
    checker.index()
    for m in modules:
        checker.check_module_dependencies(m, core is not None, target_version)
        checker.check_python_packages(m)
        checker.check_python_refs(m)
        checker.check_xml(m)
        checker.check_csv(m)
    findings = sorted(checker.findings, key=lambda f: (f.path, f.line, f.rule_id, f.matched))
    return findings, _outcome(findings, checker.undecided, target_version)
