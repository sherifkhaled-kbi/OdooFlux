"""View-type rules over XML arch and data files and Python action dicts (REQ-XML-003, REQ-PY-002).

A view type (for example ``tree``) appears in three places:

- an element named after the type (an arch root or a nested view, ``<tree>``), in XML;
- an entry of a ``view_mode`` list, as the text of ``<field name="view_mode">`` or a ``view_mode`` attribute, in XML;
- an entry of a ``view_mode`` list given as a string value of a Python dict key ``'view_mode'`` or a keyword argument
  ``view_mode=``.

Only whole list entries are rewritten, and only view_mode values are read as code: other string literals are left
alone. Python string values are rewritten inside their quotes, so the quote style is kept. Each document kind is
handled only when it parses as that kind, so the same function serves XML and Python files.
"""

import ast
import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import edit, finding
from odooflux.rules.xml import generic as xg
from odooflux.rules.xml import view_mode as vm

PY_VALIDATION = ("python-syntax",)
_TYPE = re.compile(r"[A-Za-z0-9_]+")
_VIEW_MODE = "view_mode"


def _check_type(name: str) -> None:
    if not _TYPE.fullmatch(name):
        raise ValueError(f"not a view type: {name!r}")


def _literal_inner_span(text: str, span: Span):
    """Span between the quotes of a plain, unprefixed string literal, or None for any other literal."""
    raw = text[span.start:span.end]
    if len(raw) < 2 or raw[0] not in "'\"" or raw[-1] != raw[0] or raw[1:3] == raw[0] * 2:
        return None
    return Span(span.start + 1, span.end - 1)


def _python_value_nodes(tree):
    """String-valued nodes under a ``view_mode`` dict key or keyword argument."""
    values = []
    for node in sp.all_nodes(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == _VIEW_MODE:
                    values.append(value)
        elif isinstance(node, ast.Call):
            values += [kw.value for kw in node.keywords if kw.arg == _VIEW_MODE]
    return [v for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]


def _python_entry_spans(parsed, mode: str) -> list:
    spans = []
    for value in _python_value_nodes(parsed.tree):
        inner = _literal_inner_span(parsed.text, sp.node_span(parsed, value))
        if inner is not None:
            spans += vm.entry_spans(parsed.text, [inner], mode)
    return spans


def flag_view_type(document, ctx, *, from_type):
    """Detect ``from_type`` as an element name (XML) or as an entry of a view_mode value (XML or Python)."""
    _check_type(from_type)
    xdoc = xmldoc.parse(document)
    found = []
    if xdoc.parse_error is None:
        found += [element.name_span for element in xmldoc.find(xdoc, tag=from_type)]
        found += vm.entry_spans(document.text, vm.value_spans(xdoc), from_type)
    parsed = pydoc.parse_document(document)
    if parsed.tree is not None:
        found += _python_entry_spans(parsed, from_type)
    return [finding(document, ctx, span) for span in sorted(found, key=lambda s: (s.start, s.end))]


def migrate_view_type(document, ctx, *, from_type, to_type):
    """Rename elements ``from_type`` to ``to_type`` and rewrite view_mode entries the same way. Malformed input
    yields no edits for the kind that does not parse; a second application yields no edits."""
    _check_type(from_type)
    _check_type(to_type)
    edits = list(xg.rename_tag(document, ctx, tag=from_type, new_tag=to_type))
    edits += vm.rewrite_view_mode(document, ctx, from_mode=from_type, to_mode=to_type)
    parsed = pydoc.parse_document(document)
    if parsed.tree is not None:
        edits += [edit(document, ctx, span, to_type, op="rewrite_view_mode", validation=PY_VALIDATION)
                  for span in sorted(_python_entry_spans(parsed, from_type), key=lambda s: (s.start, s.end))]
    return edits
