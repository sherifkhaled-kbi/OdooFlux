"""Migration script extractor (T052; REQ-KAP-011; diff-extractor contract, Domains and facts: migration_script).

Handles `.py` files directly under a version directory of a `migrations/` folder (`<addon>/migrations/<version>/`).
One `script` fact per file, keyed `addon::version::file name`, so a new script is ADDED and an edited one is
BEHAVIOUR_CHANGED. Attrs record the stage (`pre`, `post`, `end`, or `other` from the file name), the models referenced
through `env['model.name']`, the tables named in SQL passed to `execute(...)`, and the top-level function names.
`body_digest` is the sha256 of the module's AST dump.

Scripts are parsed with `parsers/python` (stdlib `ast`) and never run. A syntax error is a ParseFailure (PARSE_ERROR),
so the file reaches the ledger as UNKNOWN, never as a silent skip.
"""

import ast
import hashlib
import re

from odooflux.knowledge.extract.driver import ParseFailure, require_toolkit
from odooflux.knowledge.extract.domains.xml_views import fact

__all__ = ["MigrationScriptExtractor", "EXTRACTORS"]

STAGES = ("pre", "post", "end")
_SQL_TABLE = re.compile(r"\b(?:UPDATE|FROM|INTO|JOIN)\s+\"?([a-z_][a-z0-9_]*)\"?", re.IGNORECASE)


def _addon_of(path: str) -> str:
    parts = path.split("/")
    if "addons" in parts:
        i = parts.index("addons")
        return parts[i + 1] if len(parts) > i + 2 else ""
    return parts[0] if len(parts) > 1 else ""


def _is_env(node) -> bool:
    return (isinstance(node, ast.Name) and node.id == "env") or (
        isinstance(node, ast.Attribute) and node.attr == "env")


def _stage(base: str) -> str:
    return next((s for s in STAGES if base.startswith(s + "-")), "other")


class MigrationScriptExtractor:
    domain = "migration_script"
    parser = "python"

    def handles(self, path: str, toolkit=None) -> bool:
        parts = path.split("/")
        return toolkit is not None and path.endswith(".py") and len(parts) >= 3 and parts[-3] == "migrations"

    def facts(self, text: str, path: str, toolkit=None) -> list:
        doc = require_toolkit(toolkit).python_document(text, path)
        if doc.parse_error or doc.tree is None:
            message = (doc.parse_error or {}).get("message", "unparsable")
            raise ParseFailure("PARSE_ERROR", str(message))
        tree = doc.tree
        models, tables = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _is_env(node.value):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    models.add(key.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        tables.update(_SQL_TABLE.findall(arg.value))
        functions = sorted(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        parts = path.split("/")
        version, base = parts[-2], parts[-1]
        dump = ast.dump(tree, annotate_fields=True, include_attributes=False)
        attrs = {"stage": _stage(base), "version": version, "models": sorted(models), "tables": sorted(tables),
                 "functions": functions}
        subject = f"{_addon_of(path)}::{version}::{base}"
        return [fact(subject, "script", attrs, hashlib.sha256(dump.encode("utf-8")).hexdigest(), 1)]


EXTRACTORS = (MigrationScriptExtractor(),)
