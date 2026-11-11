"""Experimental fixer for the ``attrs`` and ``states`` view attributes (roadmap T2, section 3: strict subset).

Experimental: the two knowledge rules stay DETECT_ONLY. The registry (``rules.experimental.registry``) binds these
functions to the existing detectors only when a run passes ``--experimental-fixes``.

Conversion is all or nothing per element. An element is converted only when it is inside a ``<form>`` and not inside a
nested list, kanban, search or other view; every ``attrs`` key is ``invisible``, ``readonly`` or ``required``; every
leaf is ``(bare_field, op, literal)`` with ``op`` in ``=``, ``!=``, ``in``, ``not in`` and a non-falsy literal (or a
non-empty list of them); the only logical operators are ``&``, ``|`` and ``!``; and the element has no existing modifier
attribute of a key it would write. ``states="a,b"`` becomes ``invisible="state not in ['a','b']"`` only when the
element has no ``invisible`` and no ``attrs``. Anything else is left untouched and reported with a reason.

Literal mode only: the falsy shortcut is never used. Output is deterministic; a second application finds nothing.
"""

import ast
import keyword
import re
from dataclasses import dataclass

from odooflux.core.engine.documents import Document
from odooflux.parsers.xml import document as xmldoc
from odooflux.transformers import xml as xh
from odooflux.transformers.modifiers import Unconvertible, domain_to_expression

ATTRS_RULE = "16-17.xml.attrs-removed"
STATES_RULE = "16-17.xml.states-attribute-removed"
XML_VALIDATION = ("xml-wellformed",)
KEYS = ("invisible", "readonly", "required")
NESTED_VIEWS = frozenset({"tree", "list", "kanban", "search", "graph", "pivot", "calendar", "gantt", "activity",
                          "map", "cohort"})
OPERATORS = ("=", "!=", "in", "not in")
# Names that an Odoo 17 modifier expression evaluates from its context, not from the record: a field with one of these
# names would silently compare the context value instead (QA D1). A Python keyword is refused for the same reason.
RESERVED = frozenset({"uid", "context", "context_today", "current_date", "today", "now", "time", "datetime",
                      "relativedelta", "parent", "active_id", "active_ids", "active_model", "allowed_company_ids"})
LOGIC = ("&", "|", "!")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STATE_NOTE = "assumes a 'state' field on the record"


@dataclass(frozen=True)
class Conversion:
    rule_id: str
    line: int
    element: str
    before: str
    after: str
    note: str = ""


@dataclass(frozen=True)
class Refusal:
    rule_id: str
    line: int
    element: str
    reason: str


@dataclass(frozen=True)
class Plan:
    edits: tuple = ()
    converted: tuple = ()
    refused: tuple = ()


class _Refuse(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---- location ----------------------------------------------------------------------------------------------------

def _location(by_index: dict, element) -> None:
    """Refuse unless the element sits in a form and in no nested list-like view."""
    if element.tag in NESTED_VIEWS:
        raise _Refuse("nested-view")
    in_form, parent = False, element.parent_index
    while parent is not None:
        ancestor = by_index[parent]
        if ancestor.tag in NESTED_VIEWS:
            raise _Refuse("nested-view")
        in_form = in_form or ancestor.tag == "form"
        parent = ancestor.parent_index
    if not in_form:
        raise _Refuse("not-in-form")


# ---- attrs domain ------------------------------------------------------------------------------------------------

def _scalar(node):
    """A non-falsy literal value; context names and anything else are refused."""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or (isinstance(value, (str, int, float)) and not value):
            raise _Refuse("falsy-literal")
        if isinstance(value, (str, int, float)):
            return value
        raise _Refuse("non-literal-value")
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)):
        value = -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
        if not value:
            raise _Refuse("falsy-literal")
        return value
    if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
        raise _Refuse("context-name")
    raise _Refuse("non-literal-value")


def _leaf(node) -> tuple:
    if len(node.elts) != 3:
        raise _Refuse("malformed-domain")
    field_node, op_node, value_node = node.elts
    if not (isinstance(field_node, ast.Constant) and isinstance(field_node.value, str)):
        raise _Refuse("malformed-domain")
    field = field_node.value
    if "." in field:
        raise _Refuse("dotted-field")
    if not _IDENTIFIER.fullmatch(field):
        raise _Refuse("malformed-domain")
    if field in RESERVED or keyword.iskeyword(field):
        raise _Refuse("reserved-name")
    if not (isinstance(op_node, ast.Constant) and isinstance(op_node.value, str)):
        raise _Refuse("malformed-domain")
    op = op_node.value
    if op not in OPERATORS:
        raise _Refuse(f"unsupported-operator:{op}")
    if op in ("in", "not in"):
        if not isinstance(value_node, (ast.List, ast.Tuple)) or not value_node.elts:
            raise _Refuse("malformed-domain")
        return (field, op, [_scalar(item) for item in value_node.elts])
    return (field, op, _scalar(value_node))


def _domain(node) -> list:
    if not isinstance(node, ast.List):
        raise _Refuse("malformed-domain")
    items = []
    for item in node.elts:
        if isinstance(item, ast.Constant) and isinstance(item.value, str) and item.value in LOGIC:
            items.append(item.value)
        elif isinstance(item, (ast.Tuple, ast.List)):
            items.append(_leaf(item))
        else:
            raise _Refuse("malformed-domain")
    if not items:
        raise _Refuse("empty-domain")
    return items


def _expression(domain: list) -> str:
    rendered = domain_to_expression(domain, "literal")
    if isinstance(rendered, Unconvertible):
        raise _Refuse(rendered.reason)
    return rendered


def _attrs_entries(raw: str) -> list:
    """``[(key, value_node)]`` of the attrs dictionary; refuses anything that is not a plain literal dict."""
    try:
        tree = ast.parse(raw.strip(), mode="eval")
    except (SyntaxError, ValueError):
        raise _Refuse("malformed-attrs")
    body = tree.body
    if not isinstance(body, ast.Dict):
        raise _Refuse("malformed-attrs")
    if not body.keys:
        raise _Refuse("empty-attrs")
    entries, seen = [], set()
    for key_node, value_node in zip(body.keys, body.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            raise _Refuse("malformed-attrs")
        if key_node.value in seen:
            raise _Refuse(f"duplicate-key:{key_node.value}")
        seen.add(key_node.value)
        entries.append((key_node.value, value_node))
    return entries


# ---- per-element conversion --------------------------------------------------------------------------------------

def _meta(ctx, element, suffix: str):
    return xh.EditMeta(id=f"{ctx.rule_id}:{element.index}:{suffix}", rule_id=ctx.rule_id, step=ctx.step,
                       severity=ctx.severity, validation=XML_VALIDATION)


def _attrs_element(xdoc, by_index, element, ctx):
    _location(by_index, element)
    attr = element.get_attr("attrs")
    if element.get_attr("states") is not None:
        raise _Refuse("states-with-attrs")
    expressions = {}
    for key, value_node in _attrs_entries(attr.value):
        if key not in KEYS:
            raise _Refuse(f"unsupported-key:{key}")
        if element.get_attr(key) is not None:
            raise _Refuse(f"same-modifier-exists:{key}")
        expressions[key] = _expression(_domain(value_node))
    edits = []
    if ctx is not None:
        for key, expression in expressions.items():
            edits.append(xh.set_attr(xdoc, element, key, expression, meta=_meta(ctx, element, key)))
        edits.append(xh.remove_attr(xdoc, element, "attrs", meta=_meta(ctx, element, "attrs")))
    after = " ".join(f'{key}="{xh.escape_attr_value(value, chr(34))}"' for key, value in expressions.items())
    return edits, (xdoc.text[attr.span.start:attr.span.end], after, "")


def _states_element(xdoc, by_index, element, ctx):
    _location(by_index, element)
    if element.get_attr("attrs") is not None:
        raise _Refuse("states-with-attrs")
    if element.get_attr("invisible") is not None:
        raise _Refuse("same-modifier-exists:invisible")
    attr = element.get_attr("states")
    raw = attr.value
    items = [part.strip() for part in raw.split(",")]
    if not raw.strip() or any(not _IDENTIFIER.fullmatch(item) for item in items):
        raise _Refuse("malformed-states")
    expression = "state not in [" + ",".join(repr(item) for item in items) + "]"
    edits = []
    if ctx is not None:
        edits.append(xh.set_attr(xdoc, element, "invisible", expression, meta=_meta(ctx, element, "invisible")))
        edits.append(xh.remove_attr(xdoc, element, "states", meta=_meta(ctx, element, "states")))
    after = f'invisible="{xh.escape_attr_value(expression, chr(34))}"'
    return edits, (xdoc.text[attr.span.start:attr.span.end], after, STATE_NOTE)


def _plan(document, rule_id: str, ctx, attr_name: str, per_element) -> Plan:
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return Plan()
    by_index = {element.index: element for element in xdoc.elements}
    edits, converted, refused = [], [], []
    for element in xdoc.elements:
        if element.get_attr(attr_name) is None:
            continue
        line = document.line_col(element.get_attr(attr_name).span.start)[0]
        try:
            element_edits, (before, after, note) = per_element(xdoc, by_index, element, ctx)
        except _Refuse as exc:
            refused.append(Refusal(rule_id=rule_id, line=line, element=element.tag, reason=exc.reason))
            continue
        edits.extend(edit for edit in element_edits if edit is not None)
        converted.append(Conversion(rule_id=rule_id, line=line, element=element.tag, before=before, after=after,
                                    note=note))
    return Plan(edits=tuple(edits), converted=tuple(converted), refused=tuple(refused))


def plan_attrs(document: Document, ctx=None) -> Plan:
    """Convertible ``attrs`` elements with their edits (edits only when ``ctx`` is given), and refusals."""
    return _plan(document, ATTRS_RULE, ctx, "attrs", _attrs_element)


def plan_states(document: Document, ctx=None) -> Plan:
    """Convertible ``states`` elements with their edits (edits only when ``ctx`` is given), and refusals."""
    return _plan(document, STATES_RULE, ctx, "states", _states_element)


def explain_attrs(document: Document) -> Plan:
    """The conversion records and refusals for ``attrs`` without edits (used by the report)."""
    return plan_attrs(document, None)


def explain_states(document: Document) -> Plan:
    return plan_states(document, None)


def convert_attrs(document, ctx) -> list:
    """Fixer for ``16-17.xml.attrs-removed`` (fixer contract ``(document, ctx) -> edits``)."""
    return list(plan_attrs(document, ctx).edits)


def convert_states(document, ctx) -> list:
    """Fixer for ``16-17.xml.states-attribute-removed``."""
    return list(plan_states(document, ctx).edits)
