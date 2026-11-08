"""Start-tag attribute lexer (REQ-XML-001).

Expat does not expose attribute spans, so this lexer walks the start tag that expat has already
validated. It works on character offsets of the decoded text. Attribute values may contain ``>``,
newlines and quotes of the other kind, so values are scanned by their closing quote, not by ``>``.
"""

import re
from dataclasses import dataclass

from odooflux.core.engine.documents import Span

_NAME = re.compile(r"[^\s/>=<\"']+")
_WS = re.compile(r"\s*")


@dataclass(frozen=True)
class LexedAttr:
    name: str
    span: Span        # name through closing quote
    name_span: Span
    value_span: Span  # between the quotes
    quote_char: str
    raw_value: str    # exactly as written, entities not decoded


@dataclass(frozen=True)
class StartTag:
    name: str
    span: Span        # "<" through ">" or "/>"
    name_span: Span
    attrs: tuple
    self_closing: bool

    @property
    def end(self) -> int:
        return self.span.end


def lex_start_tag(text: str, start: int) -> StartTag:
    """Lex the start tag beginning at ``text[start] == "<"``. Raises ValueError if it is not one."""
    if not text.startswith("<", start):
        raise ValueError(f"no start tag at offset {start}")
    name_match = _NAME.match(text, start + 1)
    if name_match is None:
        raise ValueError(f"no element name at offset {start}")
    name = name_match.group()
    name_span = Span(name_match.start(), name_match.end())
    pos = name_match.end()
    attrs = []
    while True:
        pos = _WS.match(text, pos).end()
        if text.startswith("/>", pos):
            return StartTag(name, Span(start, pos + 2), name_span, tuple(attrs), True)
        if text.startswith(">", pos):
            return StartTag(name, Span(start, pos + 1), name_span, tuple(attrs), False)
        attr_name = _NAME.match(text, pos)
        if attr_name is None:
            raise ValueError(f"malformed start tag at offset {pos}")
        pos = attr_name.end()
        pos = _WS.match(text, pos).end()
        if not text.startswith("=", pos):
            raise ValueError(f"attribute {attr_name.group()!r} has no value")
        pos = _WS.match(text, pos + 1).end()
        quote = text[pos:pos + 1]
        if quote not in ("'", '"'):
            raise ValueError(f"attribute {attr_name.group()!r} value is not quoted")
        close = text.find(quote, pos + 1)
        if close < 0:
            raise ValueError(f"unterminated value for {attr_name.group()!r}")
        attrs.append(LexedAttr(
            name=attr_name.group(),
            span=Span(attr_name.start(), close + 1),
            name_span=Span(attr_name.start(), attr_name.end()),
            value_span=Span(pos + 1, close),
            quote_char=quote,
            raw_value=text[pos + 1:close],
        ))
        pos = close + 1
