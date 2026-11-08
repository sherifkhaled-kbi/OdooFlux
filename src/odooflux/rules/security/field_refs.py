"""Field references for a renamed model field, detect-only (REQ-PY-003, REQ-XML-003, REQ-ACL-001).

``flag_field_reference`` reports where a field name is referenced in the three file kinds that carry model fields:

- Python: attribute access (``user.groups_id``) and string values equal to the field name (domain tuples, dict keys);
- XML: ``<field name="...">`` elements, and the domain/eval text of attributes and ``domain_force`` fields;
- CSV data: a header column named ``<field>`` or ``<field>:<type>``.

Only whole identifiers match, so ``group_ids`` and ``groups_idx`` are not reported. The function never edits.
"""

import ast
import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.python import document as pydoc
from odooflux.parsers.python import spans as sp
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import finding

_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
_EVAL_ATTRIBUTES = ("domain", "eval", "context")
_DOMAIN_FIELDS = ("domain", "domain_force")


def _token(field: str):
    return re.compile(r"(?<!\w)" + re.escape(field) + r"(?!\w)")


def _python_spans(document, field: str) -> list:
    parsed = pydoc.parse_document(document)
    if parsed.tree is None:
        return []
    spans = []
    for node in sp.all_nodes(parsed.tree):
        if isinstance(node, ast.Attribute) and node.attr == field:
            spans.append(sp.node_span(parsed, node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == field:
            spans.append(sp.node_span(parsed, node))
    return spans


def _xml_spans(document, field: str) -> list:
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    token = _token(field)
    spans = []

    def matches(text: str, offset: int):
        return [Span(m.start() + offset, m.end() + offset) for m in token.finditer(text)]

    for element in xdoc.elements:
        name = element.get_attr("name") if element.tag == "field" else None
        if name is not None and name.value == field:
            spans.append(name.span)
        if name is not None and name.value in _DOMAIN_FIELDS and element.end_tag_span is not None:
            content = Span(element.start_tag_span.end, element.end_tag_span.start)
            spans += matches(document.text[content.start:content.end], content.start)
        for attr in element.attrs:
            if attr.name in _EVAL_ATTRIBUTES:
                spans += matches(attr.raw_value, attr.value_span.start)
    return spans


def _csv_spans(document, field: str) -> list:
    text = document.text
    newline = text.find("\n")
    header = text if newline < 0 else text[:newline]
    spans, offset = [], 0
    for column in header.rstrip("\r").split(","):
        lead = len(column) - len(column.lstrip())
        bare = column.strip().strip('"').split(":")[0]
        if bare == field:
            spans.append(Span(offset + lead, offset + lead + len(column.strip())))
        offset += len(column) + 1
    return spans


def flag_field_reference(document, ctx, *, field):
    """Detect references to the model field ``field`` in Python, XML and CSV data files. Detect-only."""
    if not _IDENTIFIER.fullmatch(field):
        raise ValueError(f"not a field name: {field!r}")
    if document.path.lower().endswith(".csv"):
        spans = _csv_spans(document, field)
    else:
        spans = _python_spans(document, field) + _xml_spans(document, field)
    return [finding(document, ctx, span) for span in sorted(spans, key=lambda s: (s.start, s.end))]
