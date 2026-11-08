"""view_mode rules (REQ-XML-003).

A ``view_mode`` is a comma-separated list of view types. It is written either as the text of a
``<field name="view_mode">`` element or as a ``view_mode`` attribute (legacy ``act_window`` tags). Only whole
list entries are matched: ``treeview`` is not ``tree``. Whitespace around entries is kept as written.
"""

import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import edit, finding

XML_VALIDATION = ("xml-wellformed",)
_ENTRY = re.compile(r"[^,\s]+")
_MODE = re.compile(r"[A-Za-z0-9_]+")


def value_spans(xdoc):
    """Spans of raw text that holds a view_mode list."""
    spans = []
    for element in xdoc.elements:
        attr = element.get_attr("view_mode")
        if attr is not None:
            spans.append(attr.value_span)
        if element.tag == "field" and element.end_tag_span is not None and not element.children_index:
            name = element.get_attr("name")
            if name is not None and name.value == "view_mode":
                spans.append(Span(element.start_tag_span.end, element.end_tag_span.start))
    return spans


def entry_spans(text, spans, mode):
    hits = []
    for span in spans:
        for match in _ENTRY.finditer(text, span.start, span.end):
            if match.group() == mode:
                hits.append(Span(match.start(), match.end()))
    return hits


def _check_mode(mode: str) -> None:
    if not _MODE.fullmatch(mode):
        raise ValueError(f"not a view type: {mode!r}")


def flag_view_mode(document, ctx, *, from_mode):
    """Detect ``from_mode`` as an entry of any view_mode list."""
    _check_mode(from_mode)
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    return [finding(document, ctx, span) for span in entry_spans(document.text, value_spans(xdoc), from_mode)]


def rewrite_view_mode(document, ctx, *, from_mode, to_mode):
    """Replace the entry ``from_mode`` with ``to_mode`` in every view_mode list."""
    _check_mode(from_mode)
    _check_mode(to_mode)
    xdoc = xmldoc.parse(document)
    if xdoc.parse_error is not None:
        return []
    return [edit(document, ctx, span, to_mode, op="rewrite_view_mode", validation=XML_VALIDATION)
            for span in entry_spans(document.text, value_spans(xdoc), from_mode)]
