"""Renamed-model family, detect-only (FR-018, ADR-018 D-A4; no fixer, D-A5 is not approved).

One metadata row per step and file kind binds one of the three detectors here with ``old`` and ``new`` (the model
name before and after the step) plus optional maps of external ids that follow the rename, each backed by evidence.
A detector reports references to ``old`` and never edits.

Only whole, exact names match: ``my.payment.acquirer`` and ``payment.acquirer.custom`` are other models. A name that
only occurs in a comment, a docstring or an unrelated string is not a reference and is not reported. Field names,
unqualified external ids, tables and ``id`` columns of ACL rows are not covered (no verified mapping).
"""

import ast
import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.security import acl_csv
from odooflux.rules.shared.emit import finding
from odooflux.utils.astnodes import nodes_of

_MODEL_ATTRIBUTES = ("_name", "_inherit", "_inherits")
_RELATION_FIELDS = ("Many2one", "One2many", "Many2many")
_XML_MODEL_ATTRIBUTES = ("model", "res_model")
_XML_MODEL_FIELDS = ("model", "res_model")
_MODEL_COLUMNS = ("model_id:id", "model_id/id")
_REF_CALL = re.compile(r"""\bref\(\s*(['"])([^'"]+)\1\s*[,)]""")


def _check(old, new, maps):
    if not (isinstance(old, str) and old and isinstance(new, str) and new and old != new):
        raise ValueError("old and new must be distinct non-empty model names")
    for mapping in maps:
        if mapping is not None and not (isinstance(mapping, dict) and all(
                isinstance(k, str) and k and isinstance(v, str) and v for k, v in mapping.items())):
            raise ValueError("id maps must map old external ids to new ones")


def _is(node, value):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == value


def _is_env(node):
    return (isinstance(node, ast.Name) and node.id == "env") or (isinstance(node, ast.Attribute) and node.attr == "env")


def _class_attribute_literals(node, old):
    """Literals equal to ``old`` in ``_name``, ``_inherit`` (string, list or tuple) and ``_inherits`` (dict keys)."""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names = [stmt.target.id]
        else:
            continue
        value = getattr(stmt, "value", None)
        if value is None or not any(n in _MODEL_ATTRIBUTES for n in names):
            continue
        if isinstance(value, (ast.List, ast.Tuple)):
            candidates = value.elts
        elif isinstance(value, ast.Dict):
            candidates = [k for k in value.keys if k is not None]
        else:
            candidates = [value]
        yield from (c for c in candidates if _is(c, old))


def _python_nodes(tree, old):
    for node in nodes_of(tree, ast.ClassDef):
        yield from _class_attribute_literals(node, old)
    for node in nodes_of(tree, ast.Subscript):
        if _is_env(node.value) and _is(node.slice, old):
            yield node.slice
    for node in nodes_of(tree, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr in _RELATION_FIELDS:
            if node.args and _is(node.args[0], old):
                yield node.args[0]
            yield from (kw.value for kw in node.keywords if kw.arg == "comodel_name" and _is(kw.value, old))


def flag_python_model(document, ctx, *, old, new):
    """Detect ``old`` as a model name in ``_name``/``_inherit``/``_inherits``, ``env[...]`` and relational fields."""
    _check(old, new, ())
    parsed = pydoc.parse_document(document)
    if parsed.tree is None:
        return []
    spans = {(s.start, s.end): s for s in (sp.node_span(parsed, n) for n in _python_nodes(parsed.tree, old))}
    return [finding(document, ctx, spans[key]) for key in sorted(spans)]


def _text_span(document, element):
    """Span of the stripped text of a childless, non-self-closing element, or None."""
    if element.self_closing or element.end_tag_span is None or element.children_index:
        return None, ""
    start, end = element.start_tag_span.end, element.end_tag_span.start
    raw = document.text[start:end]
    lead = len(raw) - len(raw.lstrip())
    stripped = raw.strip()
    return (Span(start + lead, start + lead + len(stripped)), stripped) if stripped else (None, "")


def flag_xml_model(document, ctx, *, old, new, xml_ids=None):
    """Detect ``old`` in ``model``/``res_model`` attributes and fields, and the evidenced external ids ``xml_ids``
    in ``ref`` attributes and ``ref('...')`` calls of ``eval`` attributes."""
    _check(old, new, (xml_ids,))
    xml_ids = xml_ids or {}
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    found = []
    for element in xdoc.elements:
        for name in _XML_MODEL_ATTRIBUTES:
            attr = element.get_attr(name)
            if attr is not None and attr.value == old:
                found.append(attr.span)
        ref = element.get_attr("ref")
        if ref is not None and ref.value in xml_ids:
            found.append(ref.span)
        ev = element.get_attr("eval")
        if ev is not None and any(m.group(2) in xml_ids for m in _REF_CALL.finditer(ev.value)):
            found.append(ev.span)
        name_attr = element.get_attr("name")
        if element.tag == "field" and name_attr is not None and name_attr.value in _XML_MODEL_FIELDS:
            span, text = _text_span(document, element)
            if span is not None and text == old:
                found.append(span)
    return [finding(document, ctx, s) for s in sorted(set(found), key=lambda s: (s.start, s.end))]


def flag_csv_model(document, ctx, *, old, new, model_ids=None):
    """Detect the evidenced qualified model external ids ``model_ids`` in the ``model_id:id`` column of ACL CSV."""
    _check(old, new, (model_ids,))
    model_ids = model_ids or {}
    found = []
    for row in acl_csv.parse_acl(document):
        for column in _MODEL_COLUMNS:
            if row.values.get(column, "").strip() in model_ids:
                end = row.offset + len(document.text[row.offset:].split("\n", 1)[0].rstrip("\r"))
                found.append(Span(row.offset, end))
                break
    return [finding(document, ctx, s) for s in found]
