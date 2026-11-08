"""Python/ORM domain extractor (T048; REQ-KAP-011; diff-extractor contract, Domains and facts: python_orm).

Structural facts come from `odooflux.parsers.python` (stdlib `ast`); nothing is imported or executed. Facts:
- `model`: one per class, keyed by `model::path` (the `_name`, else the first `_inherit`, else the class name);
- `field`: `Name = fields.X(...)` in a class body; `attrs` hold the field type and the keyword and positional
  arguments as source text; `deprecated` when a `deprecated=` keyword is present;
- `method`: a `def` in a class body; `attrs` hold args, defaults and decorators, plus `deprecated` when a decorator
  or a `warnings.warn(..., DeprecationWarning)` call marks it; `body_digest` is the sha256 of the body's AST dump;
- `function`: a module-level `def`, keyed `addon.name`, so a move between files is a MOVED change;
- `import`: `from odoo... import name`, keyed by path, so the same import in two files never collides.

Hints (`source: docs`): a docstring line `Replaces ``old``` on a method pairs the method with its predecessor.
Parse errors and a token count over `parse_token_cap` are `ParseFailure` (PARSE_ERROR, TIMEOUT).
"""

import ast
import hashlib
import os
import re

from odooflux.knowledge.extract import classify as c
from odooflux.knowledge.extract.driver import ParseFailure, require_toolkit

__all__ = ["PythonOrmExtractor", "EXTRACTORS", "TOKEN_CAP"]

TOKEN_CAP = c.load_config()["parse_token_cap"]

FIELD_TYPES = frozenset({
    "Binary", "Boolean", "Char", "Date", "Datetime", "Float", "Html", "Image", "Integer", "Json", "Many2many",
    "Many2one", "Many2oneReference", "Monetary", "One2many", "Properties", "PropertiesDefinition", "Reference",
    "Selection", "Text",
})
REPLACES_RE = re.compile(r"[Rr]eplaces ``([A-Za-z_][\w.]*)``")


def _addon_of(path: str) -> str:
    parts = path.split("/")
    if "addons" in parts:
        i = parts.index("addons")
        return parts[i + 1] if len(parts) > i + 2 else ""
    return parts[0] if len(parts) > 1 else ""


def _fact(subject, kind, attrs, body_digest, line):
    return {"subject_key": subject, "kind": kind, "attrs": attrs, "body_digest": body_digest, "line": line}


def _str_list(node) -> list:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _single_target(stmt):
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        return stmt.targets[0].id
    return None


def _model_name(node: ast.ClassDef):
    name, inherit = None, []
    for stmt in node.body:
        key = _single_target(stmt)
        if key == "_name" and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            name = stmt.value.value
        elif key == "_inherit":
            inherit = _str_list(stmt.value)
    return name or (inherit[0] if inherit else node.name), name, sorted(inherit)


def _field_type(call):
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "fields":
        return func.attr if func.attr in FIELD_TYPES else None
    if isinstance(func, ast.Name) and func.id in FIELD_TYPES:
        return func.id
    return None


def _deprecation(node):
    for decorator in node.decorator_list:
        text = ast.unparse(decorator)
        if "deprecated" in text:
            return text
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            is_warn = (isinstance(func, ast.Attribute) and func.attr == "warn") or (
                isinstance(func, ast.Name) and func.id == "warn")
            if is_warn and any(isinstance(a, ast.Name) and a.id == "DeprecationWarning" for a in sub.args):
                return "warnings.warn(DeprecationWarning)"
    return None


def _func_attrs(node) -> dict:
    a = node.args
    args = [x.arg for x in a.posonlyargs + a.args] + [x.arg for x in a.kwonlyargs]
    if a.vararg:
        args.append("*" + a.vararg.arg)
    if a.kwarg:
        args.append("**" + a.kwarg.arg)
    defaults = [ast.unparse(x) for x in a.defaults] + [ast.unparse(x) for x in a.kw_defaults if x is not None]
    attrs = {"args": args, "defaults": defaults, "decorators": [ast.unparse(x) for x in node.decorator_list]}
    deprecated = _deprecation(node)
    if deprecated:
        attrs["deprecated"] = deprecated
    return attrs


def _body_digest(node) -> str:
    dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def _class_facts(node: ast.ClassDef, path: str) -> list:
    model, name, inherit = _model_name(node)
    out = [_fact(f"{model}::{path}", "model", {"name": name, "inherit": inherit}, "", node.lineno)]
    for stmt in node.body:
        key = _single_target(stmt)
        if key is not None and _field_type(stmt.value):
            call = stmt.value
            keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
            if call.args:
                keywords["*args"] = [ast.unparse(x) for x in call.args]
            attrs = {"type": _field_type(call), "keywords": keywords}
            if "deprecated" in keywords:
                attrs["deprecated"] = keywords["deprecated"]
            out.append(_fact(f"{model}.{key}", "field", attrs, "", stmt.lineno))
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_fact(f"{model}.{stmt.name}", "method", _func_attrs(stmt), _body_digest(stmt), stmt.lineno))
    return out


class PythonOrmExtractor:
    domain = "python_orm"
    parser = "python"

    def handles(self, path: str, toolkit=None) -> bool:
        if toolkit is None or not path.endswith(".py") or os.path.basename(path) == "__manifest__.py":
            return False
        return "migrations" not in path.split("/")[:-1]

    def _tree(self, text: str, path: str, toolkit):
        doc = require_toolkit(toolkit).python_document(text, path)
        if doc.parse_error or doc.tree is None:
            message = (doc.parse_error or {}).get("message", "unparsable")
            raise ParseFailure("PARSE_ERROR", str(message))
        if len(doc.raw_tokens) > TOKEN_CAP:
            raise ParseFailure("TIMEOUT", f"{len(doc.raw_tokens)} tokens over the cap {TOKEN_CAP}")
        return doc.tree

    def facts(self, text: str, path: str, toolkit=None) -> list:
        tree = self._tree(text, path, toolkit)
        addon = _addon_of(path)
        out = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "odoo":
                for alias in node.names:
                    out.append(_fact(f"{path}::import::{node.module}.{alias.name}", "import", {}, "", node.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                subject = f"{addon}.{node.name}" if addon else node.name
                out.append(_fact(subject, "function", _func_attrs(node), _body_digest(node), node.lineno))
            elif isinstance(node, ast.ClassDef):
                out.extend(_class_facts(node, path))
        return out

    def hints(self, text: str, path: str, toolkit=None) -> list:
        doc = require_toolkit(toolkit).python_document(text, path)
        if doc.tree is None:
            return []
        found = []
        for node in doc.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            model, _, _ = _model_name(node)
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for old in REPLACES_RE.findall(ast.get_docstring(stmt) or ""):
                        found.append({"from": f"{model}.{old}", "to": f"{model}.{stmt.name}", "source": "docs"})
        return found


EXTRACTORS = (PythonOrmExtractor(),)
