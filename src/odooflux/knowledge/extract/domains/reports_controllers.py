"""Report and controller extractor (T052; REQ-KAP-011; diff-extractor contract, Domains and facts: report_controller).

Two inputs under one domain:
- XML under a `report/` or `reports/` directory: `ir.actions.report` records (kind `report`; attrs model, report_name,
  report_type, binding_model_id) and top-level QWeb `<template id=...>` elements (kind `qweb`). `body_digest` is the
  canonical subtree digest from `xml_views`, so reformatting is not a change. Any other top-level element or record is
  `Unsupported`.
- Python under a `controllers/` directory: every `@http.route(...)` function or method (kind `route`), keyed
  `addon.Class.method` (or `addon.func` at module level). Attrs hold path, type, auth and methods, which are signature
  keys in `extract/config.json`, so a changed route path is SIGNATURE_CHANGED.

Python is parsed with `parsers/python` (stdlib `ast`); nothing is imported or executed.
"""

import ast
import hashlib

from odooflux.knowledge.extract.driver import ParseFailure, Unsupported, require_toolkit
from odooflux.knowledge.extract.domains.xml_views import (TOP_LEVEL_CONTAINERS, attr_value, digest, field_named,
                                                          fact, fragment, line_of, parse_or_fail, ref_of, text_of)

__all__ = ["ReportControllerExtractor", "EXTRACTORS"]

REPORT_DIRS = ("report", "reports")
ROUTE_KEYS = ("type", "auth", "methods")


def _addon_of(path: str) -> str:
    parts = path.split("/")
    if "addons" in parts:
        i = parts.index("addons")
        return parts[i + 1] if len(parts) > i + 2 else ""
    return parts[0] if len(parts) > 1 else ""


def _literal(node):
    try:
        return ast.literal_eval(node)
    except ValueError:
        return ast.unparse(node)


def _is_route(decorator) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    return (isinstance(func, ast.Attribute) and func.attr == "route") or (isinstance(func, ast.Name)
                                                                          and func.id == "route")


def _route_attrs(decorator) -> dict:
    attrs = {"path": _literal(decorator.args[0]) if decorator.args else None, "type": None, "auth": None,
             "methods": None}
    for keyword in decorator.keywords:
        if keyword.arg == "route":
            attrs["path"] = _literal(keyword.value)
        elif keyword.arg in ROUTE_KEYS:
            attrs[keyword.arg] = _literal(keyword.value)
    return attrs


def _ast_digest(node) -> str:
    dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=True, include_attributes=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


class ReportControllerExtractor:
    domain = "report_controller"
    parser = "xml+python"

    def handles(self, path: str, toolkit=None) -> bool:
        parts = path.split("/")[:-1]
        if toolkit is None:
            return False
        if path.endswith(".xml"):
            return any(p in REPORT_DIRS for p in parts)
        if path.endswith(".py"):
            return "controllers" in parts
        return False

    def facts(self, text: str, path: str, toolkit=None) -> list:
        if path.endswith(".xml"):
            return self._xml_facts(text, path, toolkit)
        return self._controller_facts(text, path, toolkit)

    def _xml_facts(self, text: str, path: str, toolkit=None) -> list:
        doc = parse_or_fail(text, path, toolkit)
        out = []
        for element in doc.elements:
            if element.parent_index is None:
                continue
            parent = doc.elements[element.parent_index]
            if parent.parent_index is not None or parent.tag not in TOP_LEVEL_CONTAINERS:
                continue
            line = line_of(doc, element)
            if element.tag == "record":
                if attr_value(element, "model") != "ir.actions.report":
                    raise Unsupported(f"record of model {attr_value(element, 'model')} at line {line} is not a "
                                      "report action")
                record_id = attr_value(element, "id")
                if not record_id:
                    raise ParseFailure("PARSE_ERROR", f"report record at line {line} has no id")
                attrs = {}
                for name in ("model", "report_name", "report_type"):
                    item = field_named(doc, element, name)
                    attrs[name] = text_of(doc, item) if item is not None else None
                binding = field_named(doc, element, "binding_model_id")
                attrs["binding_model_id"] = ref_of(binding) if binding is not None else None
                out.append(fact(record_id, "report", attrs, digest(fragment(doc, element)), line))
            elif element.tag == "template":
                template_id = attr_value(element, "id")
                if not template_id:
                    raise ParseFailure("PARSE_ERROR", f"QWeb template at line {line} has no id")
                out.append(fact(template_id, "qweb", {"name": attr_value(element, "name")},
                                digest(fragment(doc, element)), line))
            else:
                raise Unsupported(f"top-level element <{element.tag}> at line {line} is not modelled")
        return out

    def _controller_facts(self, text: str, path: str, toolkit=None) -> list:
        doc = require_toolkit(toolkit).python_document(text, path)
        if doc.parse_error or doc.tree is None:
            message = (doc.parse_error or {}).get("message", "unparsable")
            raise ParseFailure("PARSE_ERROR", str(message))
        addon = _addon_of(path)
        out = []
        for node in doc.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.extend(self._route_fact(node, addon, None))
            elif isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        out.extend(self._route_fact(stmt, addon, node.name))
        return out

    def _route_fact(self, node, addon: str, class_name):
        routes = [d for d in node.decorator_list if _is_route(d)]
        if not routes:
            return []
        subject = f"{addon}.{class_name}.{node.name}" if class_name else f"{addon}.{node.name}"
        attrs = _route_attrs(routes[0])
        return [fact(subject, "route", attrs, _ast_digest(node), node.lineno)]


EXTRACTORS = (ReportControllerExtractor(),)
