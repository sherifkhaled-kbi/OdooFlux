"""Expat-based event scanner: element, comment, PI, CDATA and DOCTYPE start offsets (REQ-XML-001).

Expat is the well-formedness authority. Offsets are UTF-8 byte offsets into the data passed in;
``document.py`` converts them to character offsets. Stdlib only.
"""

import xml.parsers.expat as expat
from dataclasses import dataclass, field


@dataclass
class RawElement:
    index: int
    tag: str
    start_byte: int
    depth: int
    parent: int | None
    attrs: dict = field(default_factory=dict)
    end_byte: int | None = None  # offset of "</" for non-empty elements; set on the end event


@dataclass
class RawScan:
    elements: list
    comments: list          # start byte offsets of "<!--"
    processing_instructions: list  # start byte offsets of "<?"
    cdata_sections: list    # start byte offsets of "<![CDATA["
    doctype_start: int | None
    doctype_end: int | None  # byte offset reported by the end-of-DOCTYPE event
    error: str | None = None


def scan(data: bytes, *, encoding: str = "utf-8") -> RawScan:
    """Scan ``data`` (already in ``encoding``). Never raises for malformed input; sets ``error``."""
    result = RawScan(elements=[], comments=[], processing_instructions=[], cdata_sections=[],
                     doctype_start=None, doctype_end=None)
    parser = expat.ParserCreate(encoding=encoding)
    stack: list = []

    def on_start(name, attrs):
        parent = stack[-1] if stack else None
        depth = len(stack)
        element = RawElement(index=len(result.elements), tag=name, start_byte=parser.CurrentByteIndex,
                             depth=depth, parent=parent.index if parent else None, attrs=dict(attrs))
        result.elements.append(element)
        stack.append(element)

    def on_end(name):
        element = stack.pop()
        element.end_byte = parser.CurrentByteIndex

    parser.StartElementHandler = on_start
    parser.EndElementHandler = on_end
    parser.CommentHandler = lambda data_: result.comments.append(parser.CurrentByteIndex)
    parser.ProcessingInstructionHandler = lambda target, data_: result.processing_instructions.append(
        parser.CurrentByteIndex)
    parser.StartCdataSectionHandler = lambda: result.cdata_sections.append(parser.CurrentByteIndex)

    def on_doctype_start(*args):
        result.doctype_start = parser.CurrentByteIndex

    def on_doctype_end():
        result.doctype_end = parser.CurrentByteIndex

    parser.StartDoctypeDeclHandler = on_doctype_start
    parser.EndDoctypeDeclHandler = on_doctype_end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        result.error = f"{expat.ErrorString(exc.code)} (line {exc.lineno})"
    return result
