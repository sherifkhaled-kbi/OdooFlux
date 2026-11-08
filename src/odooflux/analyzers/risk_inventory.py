"""Business-logic risk inventory (REQ-BIZ-001, research R-7).

Reports, per module, where code touches the ten risk classes below. It reads Python with ``ast`` and XML with
``xml.etree``; it never changes code and never executes it. The inventory is a list of places to review after a
migration, not a list of defects.
"""

import ast
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from odooflux.discovery.manifest import MANIFEST_NAMES
from odooflux.discovery.modules import iter_module_files
from odooflux.utils import astnodes

RISK_CLASSES = ("orm-override", "computed-field", "onchange", "constraint", "multi-company", "transaction",
                "cron", "controller", "security-sensitive", "integration")
ORM_METHODS = frozenset({"create", "write", "unlink", "copy", "read", "search", "_search", "name_get",
                         "_compute_display_name", "default_get", "fields_get", "_read_group", "read_group",
                         "get_view", "fields_view_get"})
TRANSACTION_METHODS = frozenset({"commit", "rollback", "execute", "savepoint"})
INTEGRATION_MODULES = frozenset({"requests", "urllib", "xmlrpc", "smtplib"})
PUBLIC_AUTH = frozenset({"none", "public"})


@dataclass(frozen=True)
class RiskItem:
    risk_class: str
    path: str
    line: int
    detail: str

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "detail": self.detail}


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append(_dotted(node.func) + "()")
    return ".".join(reversed(parts))


def _decorator_name(node) -> str:
    return _dotted(node.func if isinstance(node, ast.Call) else node)


def _assigned_names(stmt) -> list:
    if isinstance(stmt, ast.Assign):
        return [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    return []


def _is_model_class(node: ast.ClassDef) -> bool:
    return any("_name" in _assigned_names(s) or "_inherit" in _assigned_names(s) for s in node.body)


def _keyword(call: ast.Call, name: str):
    return next((k.value for k in call.keywords if k.arg == name), None)


def inventory_python(path: str, text: str) -> list:
    try:
        tree = astnodes.parse(text)
    except (SyntaxError, ValueError):
        return []
    items = []

    def add(cls, node, detail):
        items.append(RiskItem(cls, path, node.lineno, detail))

    for node in astnodes.all_nodes(tree):
        if isinstance(node, ast.ClassDef) and _is_model_class(node):
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in ORM_METHODS:
                    add("orm-override", stmt, f"override of {stmt.name}")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                name = _decorator_name(deco)
                if name == "api.depends":
                    add("computed-field", deco, f"@api.depends on {node.name}")
                elif name == "api.onchange":
                    add("onchange", deco, f"@api.onchange on {node.name}")
                elif name == "api.constrains":
                    add("constraint", deco, f"@api.constrains on {node.name}")
                elif name in ("http.route", "route"):
                    add("controller", deco, f"route on {node.name}")
                    if isinstance(deco, ast.Call):
                        auth = _keyword(deco, "auth")
                        csrf = _keyword(deco, "csrf")
                        if isinstance(auth, ast.Constant) and auth.value in PUBLIC_AUTH:
                            add("security-sensitive", deco, f"route auth={auth.value!r} on {node.name}")
                        if isinstance(csrf, ast.Constant) and csrf.value is False:
                            add("security-sensitive", deco, f"route csrf=False on {node.name}")
            if node.name.startswith("_cron_"):
                add("cron", node, f"cron method {node.name}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = _assigned_names(node)
            value = node.value
            if "_sql_constraints" in names:
                add("constraint", node, "_sql_constraints")
            if "_check_company_auto" in names:
                add("multi-company", node, "_check_company_auto")
            if isinstance(value, ast.Call):
                func = _dotted(value.func)
                if func.endswith("Constraint") and func.split(".")[0] in ("models", "Constraint"):
                    add("constraint", node, "Constraint attribute")
                if "company_id" in names and func.startswith("fields."):
                    add("multi-company", node, "company_id field")
        elif isinstance(node, ast.Call):
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else ""
            if isinstance(func, ast.Attribute) and attr in TRANSACTION_METHODS:
                owner = _dotted(func.value)
                if owner.split(".")[-1] in ("cr", "_cr") or attr == "savepoint":
                    add("transaction", node, f"{owner}.{attr}()")
            if attr == "sudo":
                add("security-sensitive", node, "sudo()")
            elif attr == "with_user":
                add("security-sensitive", node, "with_user()")
            elif attr == "with_company":
                add("multi-company", node, "with_company()")
            if _keyword(node, "check_company") is not None:
                add("multi-company", node, "check_company")
            if _keyword(node, "compute") is not None and _dotted(node.func).startswith("fields."):
                add("computed-field", node, f"{_dotted(node.func)}(compute=...)")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if node.module and node.level == 0 else [])
            for name in names:
                if name.split(".")[0] in INTEGRATION_MODULES:
                    add("integration", node, f"import {name}")
    return sorted(items, key=lambda i: (i.line, i.risk_class, i.detail))


def inventory_xml(path: str, text: str) -> list:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for record in root.iter("record"):
        if record.get("model") == "ir.cron":
            index = text.find(f'id="{record.get("id")}"') if record.get("id") else -1
            line = text.count("\n", 0, index) + 1 if index >= 0 else 1
            items.append(RiskItem("cron", path, line, f"ir.cron record {record.get('id') or ''}".strip()))
    return items


def inventory_module(root) -> dict:
    """``{"classes": {class: [item, ...]}, "counts": {class: n}, "total": n}`` for a module directory."""
    root = Path(root)
    found = []
    for file in sorted(iter_module_files(root), key=str):
        path = Path(file)
        rel = path.relative_to(root).as_posix() if path.is_absolute() else str(path)
        if path.suffix == ".py" and path.name not in MANIFEST_NAMES:
            found += inventory_python(rel, path.read_text(encoding="utf-8", errors="replace"))
        elif path.suffix == ".xml":
            found += inventory_xml(rel, path.read_text(encoding="utf-8", errors="replace"))
    classes = {c: [i.as_dict() for i in found if i.risk_class == c] for c in RISK_CLASSES}
    return {"classes": classes, "counts": {c: len(v) for c, v in classes.items()}, "total": len(found)}
