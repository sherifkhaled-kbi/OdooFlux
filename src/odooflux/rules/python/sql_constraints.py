"""Bespoke detector for 18-19.python.sql-constraints-unsupported (REQ-PY-003; EV-006, EV-116).

In the target major version the class attribute ``_sql_constraints`` is not applied; it only logs a warning, and
constraints are declared as ``models.Constraint`` table objects (odoo/orm/table_objects.py, EV-116). The detector
reports each constraint tuple of a class-body ``_sql_constraints`` with the suggested declaration as text. A value
that cannot be read statically, or an empty list, is reported once on the statement. The detector never edits: the
SQL definition and the message need a person to check them.
"""

import ast

from odooflux.core.contracts.records import Finding
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp

ATTRIBUTE = "_sql_constraints"


def _class_assignments(tree):
    """``(statement, value)`` for every class-body assignment to ``_sql_constraints`` (plain or annotated)."""
    found = []
    for cls in sp.all_nodes(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for stmt in cls.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == ATTRIBUTE for t in stmt.targets):
                found.append((stmt, stmt.value))
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == ATTRIBUTE:
                found.append((stmt, stmt.value))
    return found


def _str_constant(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _constraint(item):
    """``(name, definition, message-or-None)`` for a readable constraint tuple, else None."""
    if not isinstance(item, ast.Tuple) or not 2 <= len(item.elts) <= 3:
        return None
    name, definition = _str_constant(item.elts[0]), _str_constant(item.elts[1])
    if name is None or definition is None:
        return None
    message = _str_constant(item.elts[2]) if len(item.elts) == 3 else None
    if len(item.elts) == 3 and message is None:
        return None
    return name, definition, message


def _suggestion(name, definition, message):
    call = f"models.Constraint({definition!r}, {message!r})" if message is not None else f"models.Constraint({definition!r})"
    return f"{name} = {call}  (text only; review before use)"


def _finding(document, ctx, span, message, suggestion):
    return Finding(rule_id=ctx.rule_id, path=document.path, line=document.line_col(span.start)[0],
                   severity=ctx.severity, message=message, suggestion=suggestion,
                   matched=document.text[span.start:span.end])


def flag_sql_constraints(document, ctx):
    """Report each readable constraint tuple, and the statement once when its list is empty or unreadable."""
    parsed = pydoc.parse_document(document)
    if parsed.tree is None:
        return []
    findings = []
    for stmt, value in _class_assignments(parsed.tree):
        if not isinstance(value, (ast.List, ast.Tuple)):
            reason = "the constraint list cannot be read statically"
            parts = []
        else:
            parts = [_constraint(item) for item in value.elts]
            for item, constraint in zip(value.elts, parts):
                if constraint is None:
                    continue
                name, definition, message = constraint
                findings.append(_finding(document, ctx, sp.node_span(parsed, item),
                                         f"{ctx.message}; constraint '{name}' is declared here.",
                                         _suggestion(name, definition, message)))
            if not value.elts:
                reason = "no constraints are declared, but the attribute is still unsupported"
            elif any(constraint is None for constraint in parts):
                reason = "some constraints cannot be read statically"
            else:
                continue
        findings.append(_finding(document, ctx, sp.node_span(parsed, stmt),
                                 f"{ctx.message}; {reason}.", ctx.suggestion))
    return sorted(findings, key=lambda f: (f.line, f.matched))
