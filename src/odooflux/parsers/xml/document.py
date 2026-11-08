"""XML document with element and attribute spans (REQ-XML-001).

``parse`` never raises: malformed input yields an ``XmlDocument`` with ``parse_error`` set and no
elements. Spans are character offsets into ``document.text``.
"""

import bisect
from dataclasses import dataclass

from odooflux.core.engine.documents import Document, Span
from odooflux.parsers.xml import attr_lexer, expat_locator
from odooflux.utils import parsecount


@dataclass(frozen=True)
class XmlAttr:
    name: str
    span: Span        # name through closing quote
    name_span: Span
    value_span: Span  # between the quotes
    quote_char: str
    raw_value: str    # as written in the file
    value: str        # entity-decoded (expat)


@dataclass(frozen=True)
class XmlElement:
    index: int
    tag: str
    span: Span              # whole element, start tag through end tag
    start_tag_span: Span
    name_span: Span         # element name inside the start tag
    end_tag_span: Span | None  # None for self-closing elements
    self_closing: bool
    attrs: tuple
    parent_index: int | None
    children_index: tuple
    depth: int

    def get_attr(self, name: str):
        for attr in self.attrs:
            if attr.name == name:
                return attr
        return None


@dataclass(frozen=True)
class XmlDocument:
    document: Document
    elements: tuple
    comments: tuple = ()
    processing_instructions: tuple = ()
    cdata_sections: tuple = ()
    doctype: Span | None = None
    parse_error: str | None = None

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def text(self) -> str:
        return self.document.text


def _char_width(ch: str) -> int:
    code = ord(ch)
    if code < 0x80:
        return 1
    if code < 0x800:
        return 2
    if 0xDC80 <= code <= 0xDCFF:  # surrogateescape: one raw byte
        return 1
    if code < 0x10000:
        return 3
    return 4


def _byte_offsets(text: str):
    """Sorted UTF-8 byte offset of every character boundary (plus the end). None when ASCII."""
    if text.isascii():
        return None
    offsets, pos = [], 0
    for ch in text:
        offsets.append(pos)
        pos += _char_width(ch)
    offsets.append(pos)
    return offsets


def _to_char(offsets, byte_offset: int) -> int:
    if offsets is None:
        return byte_offset
    return bisect.bisect_left(offsets, byte_offset)


_CACHE: dict = {}
_CACHE_SIZE = 16


def parse(source, *, path: str = "<memory>") -> XmlDocument:
    """Parse an engine ``Document`` (or plain text, wrapped with ``path``) into an ``XmlDocument``.
    The most recent parses are kept by ``(path, text)`` (many rules read one file); they are never mutated."""
    document = source if isinstance(source, Document) else Document.from_text(path, source)
    key = (document.path, document.text)
    hit = _CACHE.get(key)
    if hit is None:
        hit = _parse(document)
        if len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = hit
    return hit


def _parse(document: Document) -> XmlDocument:
    parsecount.bump()
    text = document.text
    try:
        data = text.encode("utf-8", errors="surrogateescape")
    except UnicodeEncodeError:
        return XmlDocument(document=document, elements=(), parse_error="unencodable-text")

    scanned = expat_locator.scan(data)
    if scanned.error is not None:
        return XmlDocument(document=document, elements=(), parse_error=scanned.error)

    offsets = _byte_offsets(text)

    def char(byte_offset):
        return _to_char(offsets, byte_offset)

    children: dict = {}
    elements = []
    for raw in scanned.elements:
        start = char(raw.start_byte)
        tag = attr_lexer.lex_start_tag(text, start)
        if tag.self_closing:
            end_tag_span = None
            span = tag.span
        else:
            end_char = char(raw.end_byte)
            close = text.index(">", end_char) + 1
            end_tag_span = Span(end_char, close)
            span = Span(start, close)
        attrs = []
        for lexed in tag.attrs:
            attrs.append(XmlAttr(
                name=lexed.name,
                span=lexed.span,
                name_span=lexed.name_span,
                value_span=lexed.value_span,
                quote_char=lexed.quote_char,
                raw_value=lexed.raw_value,
                value=raw.attrs[lexed.name],
            ))
        if raw.parent is not None:
            children.setdefault(raw.parent, []).append(raw.index)
        elements.append(XmlElement(
            index=raw.index,
            tag=raw.tag,
            span=span,
            start_tag_span=tag.span,
            name_span=tag.name_span,
            end_tag_span=end_tag_span,
            self_closing=tag.self_closing,
            attrs=tuple(attrs),
            parent_index=raw.parent,
            children_index=(),
            depth=raw.depth,
        ))
    elements = [
        XmlElement(**{**element.__dict__, "children_index": tuple(children.get(element.index, ()))})
        for element in elements
    ]

    def span_of(byte_start, closer):
        start = char(byte_start)
        return Span(start, text.index(closer, start) + len(closer))

    comments = tuple(span_of(b, "-->") for b in scanned.comments)
    pis = tuple(span_of(b, "?>") for b in scanned.processing_instructions)
    cdata = tuple(span_of(b, "]]>") for b in scanned.cdata_sections)
    doctype = None
    if scanned.doctype_start is not None:
        doctype_start = char(scanned.doctype_start)
        doctype_end = text.index(">", char(scanned.doctype_end)) + 1
        doctype = Span(doctype_start, doctype_end)

    return XmlDocument(document=document, elements=tuple(elements), comments=comments,
                       processing_instructions=pis, cdata_sections=cdata, doctype=doctype)


def find(doc: XmlDocument, tag=None, attr=None) -> list:
    """Elements in document order matching ``tag`` (qualified name) and/or having attribute ``attr``."""
    hits = []
    for element in doc.elements:
        if tag is not None and element.tag != tag:
            continue
        if attr is not None and element.get_attr(attr) is None:
            continue
        hits.append(element)
    return hits


def attr_span(element: XmlElement, name: str, part: str = "whole") -> Span:
    """Span of attribute ``name``; ``part`` is ``whole`` (name through closing quote) or ``value``."""
    attr = element.get_attr(name)
    if attr is None:
        raise KeyError(name)
    if part == "whole":
        return attr.span
    if part == "value":
        return attr.value_span
    raise ValueError(f"unknown part {part!r}")


def insert_attr_point(element: XmlElement) -> int:
    """Offset where a new attribute can be inserted: after the last attribute, else after the name."""
    if element.attrs:
        return element.attrs[-1].span.end
    return element.name_span.end
