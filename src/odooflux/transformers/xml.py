"""XML edit helpers (REQ-XML-001, REQ-TRF-003).

Each helper locates a span with ``parsers.xml`` and returns ``Edit`` values for
``core.engine.edits.apply_edits``. Helpers return ``None`` (or ``()``) when the document already has
the requested state, which makes a second application produce no edits. Output values are escaped
for the quote character of the attribute they are written into, so the result stays well-formed.
"""

import re
from dataclasses import dataclass

from odooflux.core.engine.edits import Edit
from odooflux.parsers.xml import document as xmldoc

_NAME = re.compile(r"^[A-Za-z_][\w.\-]*(:[A-Za-z_][\w.\-]*)?$")


@dataclass(frozen=True)
class EditMeta:
    """Identity and policy for the edits a helper creates (fields required by ``apply_edits``)."""

    id: str
    rule_id: str
    step: str
    severity: str
    validation: tuple = ()
    finding_ids: tuple = ()


def escape_attr_value(value: str, quote: str) -> str:
    """Escape ``value`` for an attribute delimited by ``quote``.

    ``&``, ``<``, ``>`` and the delimiter are escaped; newline, carriage return and tab are written as
    character references so that attribute-value normalisation does not change them.
    """
    if quote not in ('"', "'"):
        raise ValueError(f"unsupported quote character {quote!r}")
    out = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = out.replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;")
    return out.replace(quote, "&quot;" if quote == '"' else "&apos;")


def _check_name(name: str) -> None:
    if not _NAME.match(name):
        raise ValueError(f"invalid XML name {name!r}")


def _edit(xdoc, meta: EditMeta, start: int, end: int, after: str, suffix: str = "") -> Edit:
    return Edit(
        id=meta.id + suffix,
        rule_id=meta.rule_id,
        path=xdoc.path,
        start=start,
        end=end,
        before=xdoc.text[start:end],
        after=after,
        severity=meta.severity,
        step=meta.step,
        validation=tuple(meta.validation),
        finding_ids=tuple(meta.finding_ids),
    )


def set_attr(xdoc, element, name: str, value: str, *, meta: EditMeta, quote: str | None = None):
    """Set attribute ``name`` to ``value``: replace the value of an existing attribute (keeping its quote
    style), or insert a new one after the last attribute. ``None`` when nothing would change."""
    _check_name(name)
    attr = element.get_attr(name)
    if attr is not None:
        escaped = escape_attr_value(value, attr.quote_char)
        if escaped == attr.raw_value:
            return None
        return _edit(xdoc, meta, attr.value_span.start, attr.value_span.end, escaped)
    delimiter = quote or '"'
    point = xmldoc.insert_attr_point(element)
    return _edit(xdoc, meta, point, point, f" {name}={delimiter}{escape_attr_value(value, delimiter)}{delimiter}")


def remove_attr(xdoc, element, name: str, *, meta: EditMeta):
    """Remove attribute ``name`` together with the whitespace that separates it from the previous token.
    ``None`` when the attribute is absent."""
    _check_name(name)
    attr = element.get_attr(name)
    if attr is None:
        return None
    position = element.attrs.index(attr)
    previous_end = element.attrs[position - 1].span.end if position else element.name_span.end
    return _edit(xdoc, meta, previous_end, attr.span.end, "")


def rename_tag(xdoc, element, new_name: str, *, meta: EditMeta) -> tuple:
    """Rename the element in its start tag and, when it has one, its end tag. Returns a tuple of edits
    (empty when the name is unchanged)."""
    _check_name(new_name)
    if new_name == element.tag:
        return ()
    edits = [_edit(xdoc, meta, element.name_span.start, element.name_span.end, new_name)]
    if element.end_tag_span is not None:
        start = element.end_tag_span.start + len("</")
        end = start + len(element.tag)
        edits.append(_edit(xdoc, meta, start, end, new_name, suffix=":end"))
    return tuple(edits)


def replace_element(xdoc, element, new_xml: str, *, meta: EditMeta) -> Edit:
    """Replace the whole element with ``new_xml``, which must be exactly one well-formed element."""
    probe = xmldoc.parse(f"<_wrap>{new_xml}</_wrap>", path=xdoc.path)
    if probe.parse_error is not None:
        raise ValueError(f"replacement is not well-formed: {probe.parse_error}")
    top = [e for e in probe.elements if e.depth == 1]
    if len(top) != 1 or top[0].span.start != len("<_wrap>") or top[0].span.end != len("<_wrap>") + len(new_xml):
        raise ValueError("replacement must be exactly one element")
    return _edit(xdoc, meta, element.span.start, element.span.end, new_xml)
