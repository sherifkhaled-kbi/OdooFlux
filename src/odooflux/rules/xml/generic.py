"""Generic XML detectors and fixers bound by rule metadata (REQ-XML-003, REQ-TRF-003).

Detectors take ``(document, ctx, **params)`` and return ``Finding`` values. Fixers return ``Edit`` values built
by the feature 005 helpers in ``transformers.xml``. Malformed XML yields no findings and no edits.
"""

from odooflux.parsers.xml import document as xmldoc
from odooflux.rules.shared.emit import finding
from odooflux.transformers import xml as xh

XML_VALIDATION = ("xml-wellformed",)


def _parse(document):
    xdoc = xmldoc.parse(document)
    return None if xdoc.parse_error is not None else xdoc


def _meta(ctx, op, element):
    return xh.EditMeta(id=f"{ctx.rule_id}:{op}:{element.index}", rule_id=ctx.rule_id, step=ctx.step,
                       severity=ctx.severity, validation=XML_VALIDATION)


def rename_tag(document, ctx, *, tag, new_tag):
    """Rename every element ``tag`` (start and end tag) to ``new_tag``."""
    xdoc = _parse(document)
    if xdoc is None:
        return []
    edits = []
    for element in xmldoc.find(xdoc, tag=tag):
        edits.extend(xh.rename_tag(xdoc, element, new_tag, meta=_meta(ctx, "rename_tag", element)))
    return edits


def remove_attribute(document, ctx, *, attribute, tag=None):
    """Remove ``attribute`` from every element (or only elements ``tag``) that carries it."""
    xdoc = _parse(document)
    if xdoc is None:
        return []
    edits = []
    for element in xmldoc.find(xdoc, tag=tag, attr=attribute):
        edit = xh.remove_attr(xdoc, element, attribute, meta=_meta(ctx, "remove_attribute", element))
        if edit is not None:
            edits.append(edit)
    return edits


def flag_element(document, ctx, *, tag):
    """Detect every element ``tag``. The finding sits on the start tag."""
    xdoc = _parse(document)
    if xdoc is None:
        return []
    return [finding(document, ctx, element.start_tag_span) for element in xmldoc.find(xdoc, tag=tag)]


def flag_attribute(document, ctx, *, attribute, tag=None):
    """Detect ``attribute`` on every element (or only elements ``tag``)."""
    xdoc = _parse(document)
    if xdoc is None:
        return []
    return [finding(document, ctx, element.get_attr(attribute).span)
            for element in xmldoc.find(xdoc, tag=tag, attr=attribute)]


def flag_attribute_value(document, ctx, *, attribute, value, tag=None):
    """Detect ``attribute`` whose decoded value is exactly ``value`` (on every element, or only elements ``tag``)."""
    xdoc = _parse(document)
    if xdoc is None:
        return []
    return [finding(document, ctx, element.get_attr(attribute).span)
            for element in xmldoc.find(xdoc, tag=tag, attr=attribute)
            if element.get_attr(attribute).value == value]
