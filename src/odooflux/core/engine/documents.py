"""Document model: decoding, newline/BOM detection, byte-exact encoding, span and line/column conversion.

Text is kept exactly as stored in the file (newlines are not normalised), so span offsets index the
file's own characters. Bytes that do not decode in the detected encoding are kept as lone surrogates
(``surrogateescape``) so that encoding the unchanged text reproduces the input byte for byte.
Contract: specs/005-structured-transformations/data-model.md (Document, Span), REQ-TRF-004.
"""

import bisect
import codecs
import dataclasses
import functools
import hashlib
import re
from dataclasses import dataclass

BOM = b"\xef\xbb\xbf"

_XML_DECLARATION = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")
_PY_CODING_COOKIE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
_ESCAPED_BYTE = re.compile("[\udc80-\udcff]")
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class Span:
    """Half-open character range ``[start, end)`` in a document's text."""

    start: int
    end: int

    def __post_init__(self):
        if not (isinstance(self.start, int) and isinstance(self.end, int)):
            raise ValueError("span bounds must be integers")
        if not 0 <= self.start <= self.end:
            raise ValueError(f"invalid span [{self.start}, {self.end})")


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    kinds = [kind for kind, count in (("\r\n", crlf), ("\n", lf), ("\r", cr)) if count]
    if not kinds:
        return ""
    return kinds[0] if len(kinds) == 1 else "mixed"


def _declared_encoding(path: str, body: bytes):
    match = _XML_DECLARATION.match(body[:512])
    if match:
        return match.group(1).decode("ascii")
    if path.endswith(".py"):
        for line in body.split(b"\n", 2)[:2]:
            match = _PY_CODING_COOKIE.match(line)
            if match:
                return match.group(1).decode("ascii")
    return None


def _resolve_codec(name: str):
    try:
        codec = codecs.lookup(name).name
    except LookupError:
        return "utf-8", f"unknown-encoding:{name}"
    if codec.startswith(("utf-16", "utf-32")):
        # Not ASCII-compatible: a declared UTF-16 file is not decoded that way (no round-trip guarantee).
        return "utf-8", f"unsupported-encoding:{codec}"
    return codec, None


@dataclass(frozen=True)
class Document:
    """One file as text plus everything needed to write it back byte for byte."""

    path: str
    raw: bytes
    text: str
    encoding: str
    bom: bool
    newline: str  # "\n", "\r\n", "\r", "mixed", or "" when the text has no line break
    issues: tuple = ()

    @classmethod
    def from_bytes(cls, path: str, raw: bytes) -> "Document":
        issues = []
        bom = raw.startswith(BOM)
        body = raw[len(BOM):] if bom else raw
        encoding = "utf-8"
        if not bom:
            declared = _declared_encoding(path, body)
            if declared is not None:
                encoding, issue = _resolve_codec(declared)
                if issue:
                    issues.append(issue)
        text = body.decode(encoding, errors="surrogateescape")
        if _ESCAPED_BYTE.search(text):
            issues.append("undecodable-bytes")
        return cls(path=path, raw=raw, text=text, encoding=encoding, bom=bom,
                   newline=_newline_style(text), issues=tuple(issues))

    @classmethod
    def from_text(cls, path: str, text: str, *, encoding: str = "utf-8", bom: bool = False) -> "Document":
        prefix = BOM if bom else b""
        raw = prefix + text.encode(encoding, errors="surrogateescape")
        return cls(path=path, raw=raw, text=text, encoding=encoding, bom=bom,
                   newline=_newline_style(text))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def encode(self) -> bytes:
        """Bytes for the current text, with the original BOM and encoding."""
        return (BOM if self.bom else b"") + self.text.encode(self.encoding, errors="surrogateescape")

    def with_text(self, text: str) -> "Document":
        """Same path, encoding and BOM, new text. ``raw`` becomes the encoding of the new text."""
        return dataclasses.replace(self, raw=(BOM if self.bom else b"") + text.encode(
            self.encoding, errors="surrogateescape"), text=text, newline=_newline_style(text))

    @functools.cached_property
    def _line_starts(self) -> list:
        return [0] + [m.end() for m in _LINE_BREAK.finditer(self.text)]

    def line_col(self, offset: int) -> tuple:
        """1-based line and 0-based character column of a character offset."""
        if not 0 <= offset <= len(self.text):
            raise ValueError(f"offset {offset} outside document of length {len(self.text)}")
        starts = self._line_starts
        index = bisect.bisect_right(starts, offset) - 1
        return index + 1, offset - starts[index]

    def offset(self, line: int, column: int) -> int:
        """Inverse of ``line_col``. Columns may reach the end of the line content."""
        starts = self._line_starts
        if not 1 <= line <= len(starts) or column < 0:
            raise ValueError(f"no position line {line}, column {column}")
        limit = starts[line] if line < len(starts) else len(self.text)
        if starts[line - 1] + column > limit:
            raise ValueError(f"column {column} is past line {line}")
        return starts[line - 1] + column

    def locate(self, span: Span) -> tuple:
        """``(line, column, end_line, end_column)`` for a span."""
        line, column = self.line_col(span.start)
        end_line, end_column = self.line_col(span.end)
        return line, column, end_line, end_column
