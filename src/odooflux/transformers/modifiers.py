"""attrs/states to modifier-expression converter (REQ-XML-002).

Target semantics (Odoo 17+): ``invisible``, ``readonly``, ``required`` and list-column
``column_invisible`` hold Python expressions. Normative mapping: specs/005-structured-transformations/
research.md R-5 and contracts/modifier-converter.md. Deterministic; unconvertible input is left
unchanged and reported with a reason (never guessed).

Documented assumptions pending gap G-R-20: the ``falsy`` mode shortcut, and combining an existing
modifier with converted ones as ``(existing) or (new)``.
"""

import ast
import re
from dataclasses import dataclass

from odooflux.core.engine.documents import Span
from odooflux.transformers import xml as xh

MODIFIER_KEYS = ("invisible", "readonly", "required", "column_invisible")
MODES = ("falsy", "literal")
SUPPORTED_OPERATORS = ("=", "==", "!=", "<>", "<", "<=", ">", ">=", "in", "not in")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class Expr(str):
    """Source text of a context expression (``parent.x``, ``uid``, ``context.get(...)``). Rendered verbatim."""

    def __repr__(self):
        return str(self)


@dataclass(frozen=True)
class Unconvertible:
    reason: str


@dataclass(frozen=True)
class Unconverted:
    key: str
    reason: str


@dataclass(frozen=True)
class ModifierConversion:
    element_span: Span
    mode: str
    inputs: dict
    outputs: dict | None
    edits: tuple
    unconverted: tuple = ()
    warnings: tuple = ()


class _Reject(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _check_mode(mode):
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")


# ---- attrs value -> Python values -------------------------------------------------------------

def _is_chain(node) -> bool:
    if isinstance(node, ast.Name):
        return True
    if isinstance(node, ast.Attribute):
        return _is_chain(node.value)
    return False


def _is_context_get(func) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "get"
            and isinstance(func.value, ast.Name) and func.value.id == "context")


def _eval(node):
    """Literal value of an AST node; context names become ``Expr``. Raises ``_Reject`` otherwise."""
    if isinstance(node, ast.Constant):
        if node.value is None or isinstance(node.value, (str, int, float, bool)):
            return node.value
        raise _Reject("unsupported-value")
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float)):
        return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(item) for item in node.elts]
    if isinstance(node, (ast.Name, ast.Attribute)) and _is_chain(node):
        return Expr(ast.unparse(node))
    if isinstance(node, ast.Call):
        if _is_context_get(node.func):
            return Expr(ast.unparse(node))
        raise _Reject("unsupported-call")
    raise _Reject("unsupported-value")


def _parse_attrs(raw: str):
    """(entries, None) with entries = [(key, value_node)], or (None, reason)."""
    try:
        tree = ast.parse(raw.strip(), mode="eval")
    except (SyntaxError, ValueError):
        return None, "unparseable-attrs"
    body = tree.body
    if not isinstance(body, ast.Dict):
        return None, "malformed-attrs"
    entries = []
    for key_node, value_node in zip(body.keys, body.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            return None, "malformed-attrs"
        entries.append((key_node.value, value_node))
    return entries, None


# ---- domain -> expression ---------------------------------------------------------------------

def _render_value(value) -> str:
    if isinstance(value, Expr):
        return str(value)
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(str(value))
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render_value(item) for item in value) + "]"
    raise _Reject("malformed-value")


def _normalise(items):
    """Insert the implicit '&' between top-level terms (Odoo normalize_domain rule)."""
    expected, result = 1, []
    for item in items:
        if expected == 0:
            result.insert(0, "&")
            expected = 1
        result.append(item)
        if isinstance(item, (list, tuple)):
            expected -= 1
        elif isinstance(item, str) and item in ("&", "|"):
            expected += 1
        elif isinstance(item, str) and item == "!":
            pass
        else:
            raise _Reject("malformed-domain")
    if expected != 0:
        raise _Reject("malformed-domain")
    return result


def _build(items):
    """Prefix list -> tree. Nodes: ("leaf", leaf), ("&", a, b), ("|", a, b), ("!", a)."""
    stack = []
    for item in reversed(items):
        if isinstance(item, str) and item in ("&", "|"):
            if len(stack) < 2:
                raise _Reject("malformed-domain")
            first, second = stack.pop(), stack.pop()
            stack.append((item, first, second))
        elif isinstance(item, str) and item == "!":
            if not stack:
                raise _Reject("malformed-domain")
            stack.append(("!", stack.pop()))
        else:
            stack.append(("leaf", item))
    if len(stack) != 1:
        raise _Reject("malformed-domain")
    return stack[0]


def _render_leaf(leaf, mode: str) -> str:
    if len(leaf) != 3:
        raise _Reject("malformed-domain")
    field_name, op, value = leaf
    if not isinstance(field_name, str) or not _FIELD.match(field_name):
        raise _Reject("malformed-domain")
    if not isinstance(op, str):
        raise _Reject("malformed-domain")
    if op not in SUPPORTED_OPERATORS:
        raise _Reject(f"unsupported operator {op}")
    if op in ("=", "=="):
        if mode == "falsy" and value is False:
            return f"not {field_name}"
        return f"{field_name} == {_render_value(value)}"
    if op in ("!=", "<>"):
        if mode == "falsy" and value is False:
            return field_name
        return f"{field_name} != {_render_value(value)}"
    if op in ("in", "not in"):
        if not isinstance(value, (list, tuple)):
            raise _Reject("malformed-domain")
        return f"{field_name} {op} {_render_value(value)}"
    return f"{field_name} {op} {_render_value(value)}"


def _render(node, mode: str, top: bool) -> str:
    kind = node[0]
    if kind == "leaf":
        return _render_leaf(node[1], mode)
    if kind == "!":
        return f"not ({_render(node[1], mode, top=True)})"
    text = f"{_render(node[1], mode, top=False)} {'and' if kind == '&' else 'or'} " \
           f"{_render(node[2], mode, top=False)}"
    return text if top else f"({text})"


def domain_to_expression(domain, mode: str = "falsy"):
    """Python expression equivalent to an Odoo domain, or ``Unconvertible(reason)``.

    A string is already an expression and is returned unchanged. The outermost parentheses are not
    written; inner compound terms are parenthesised.
    """
    _check_mode(mode)
    if isinstance(domain, str):
        return domain
    if not isinstance(domain, (list, tuple)):
        return Unconvertible("malformed-domain")
    items = list(domain)
    if not items:
        return "True"
    try:
        return _render(_build(_normalise(items)), mode, top=True)
    except _Reject as exc:
        return Unconvertible(exc.reason)


# ---- element conversion -----------------------------------------------------------------------

def _states_expression(raw: str):
    items = [part.strip() for part in raw.split(",")]
    if not raw.strip() or any(not item for item in items):
        return None
    return "state not in [" + ", ".join(repr(item) for item in items) + "]"


def convert_element(doc, element, *, mode: str, in_list_view: bool, meta=None) -> ModifierConversion:
    """Convert the ``attrs`` and ``states`` attributes of ``element`` into modifier expressions.

    Edits are built only when ``meta`` (an ``EditMeta``) is given; without it the result describes the
    conversion but carries no edits. Converted keys are merged with existing modifiers as
    ``(existing) or (new)``. Nothing is commented out and no attribute is duplicated.
    """
    _check_mode(mode)
    attrs_attr = element.get_attr("attrs")
    states_attr = element.get_attr("states")
    inputs = {
        "attrs": attrs_attr.raw_value if attrs_attr is not None else None,
        "states": states_attr.raw_value if states_attr is not None else None,
        "existing": {key: element.get_attr(key).value for key in MODIFIER_KEYS
                     if element.get_attr(key) is not None},
    }
    unconverted, warnings = [], []
    new_parts = {key: [] for key in MODIFIER_KEYS}
    remove_attrs, rewrite_attrs, remove_states = False, None, False

    if attrs_attr is not None:
        entries, reason = _parse_attrs(attrs_attr.value)
        if reason is not None:
            unconverted.append(Unconverted("attrs", reason))
        else:
            converted, kept = [], []
            for key, value_node in entries:
                if key not in MODIFIER_KEYS:
                    kept.append((key, value_node))
                    unconverted.append(Unconverted(key, "unknown-key"))
                    continue
                if key == "column_invisible" and not in_list_view:
                    kept.append((key, value_node))
                    unconverted.append(Unconverted(key, "column-invisible-outside-list"))
                    continue
                try:
                    value = _eval(value_node)
                except _Reject as exc:
                    kept.append((key, value_node))
                    unconverted.append(Unconverted(key, exc.reason))
                    continue
                expression = domain_to_expression(value, mode)
                if isinstance(expression, Unconvertible):
                    kept.append((key, value_node))
                    unconverted.append(Unconverted(key, expression.reason))
                    continue
                new_parts[key].append(expression)
                converted.append(key)
            if converted:
                if kept:
                    rewrite_attrs = "{" + ", ".join(
                        f"{key!r}: {ast.unparse(node)}" for key, node in kept) + "}"
                else:
                    remove_attrs = True

    if states_attr is not None:
        expression = _states_expression(states_attr.value)
        if expression is None:
            unconverted.append(Unconverted("states", "malformed-states"))
        else:
            new_parts["invisible"].append(expression)
            remove_states = True
            warnings.append("no-state-field-check")

    outputs, edits = {}, []

    def sub_meta(suffix):
        return xh.EditMeta(id=f"{meta.id}:{suffix}", rule_id=meta.rule_id, step=meta.step,
                           severity=meta.severity, validation=meta.validation,
                           finding_ids=meta.finding_ids)

    for key in MODIFIER_KEYS:
        parts = list(new_parts[key])
        if not parts:
            continue
        existing = element.get_attr(key)
        if existing is not None and existing.value.strip():
            parts = [existing.value] + parts
        value = parts[0] if len(parts) == 1 else " or ".join(f"({part})" for part in parts)
        outputs[key] = value
        if meta is not None:
            edit = xh.set_attr(doc, element, key, value, meta=sub_meta(key))
            if edit is not None:
                edits.append(edit)

    if meta is not None:
        if remove_attrs:
            edits.append(xh.remove_attr(doc, element, "attrs", meta=sub_meta("attrs")))
        elif rewrite_attrs is not None:
            edits.append(xh.set_attr(doc, element, "attrs", rewrite_attrs, meta=sub_meta("attrs")))
        if remove_states:
            edits.append(xh.remove_attr(doc, element, "states", meta=sub_meta("states")))

    return ModifierConversion(
        element_span=element.start_tag_span,
        mode=mode,
        inputs=inputs,
        outputs=outputs or None,
        edits=tuple(edit for edit in edits if edit is not None),
        unconverted=tuple(unconverted),
        warnings=tuple(dict.fromkeys(warnings)),
    )
