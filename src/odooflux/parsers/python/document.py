"""Python parser adapter (stdlib ``ast`` and ``tokenize``).

``PythonParser`` is the registry adapter used by ``builtins``. ``PythonDocument`` is the span-bearing
model used by the transformations (REQ-PY-001, REQ-PY-004; contracts/span-locators.md).
"""

import ast
import functools
import io
import tokenize
from dataclasses import dataclass

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.engine.documents import Document, Span
from odooflux.utils import astnodes, parsecount


class PythonParser:
    key = "python"
    contract_version = CONTRACT_VERSION

    def parse(self, text: str):
        try:
            ast.parse(text)
        except SyntaxError as exc:
            return f"line {exc.lineno}: {exc.msg}"
        return None


_SKIP_TOKENS = frozenset({tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT,
                          tokenize.NEWLINE, tokenize.ENDMARKER})


@dataclass(frozen=True)
class PythonDocument:
    """Source text with its AST, token list (``(type, string, Span)``) and parse error, if any.

    ``tree`` and the token list are empty when ``parse_error`` is set; span locators then find nothing.
    The token spans are built on first use of ``tokens``: most documents never need them (hot path).
    """

    document: Document
    tree: object  # ast.Module or None
    raw_tokens: tuple  # ``tokenize.TokenInfo`` values, () when unparsed
    parse_error: object  # None or {"message", "line", "column"}

    @functools.cached_property
    def tokens(self) -> tuple:
        return _spans_for(self.document, self.raw_tokens) if self.raw_tokens else ()

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def text(self) -> str:
        return self.document.text

    @functools.cached_property
    def significant_tokens(self) -> tuple:
        return tuple(tok for tok in self.tokens if tok[0] not in _SKIP_TOKENS)

    @functools.cached_property
    def significant_starts(self) -> tuple:
        return tuple(tok[2].start for tok in self.significant_tokens)


def _line_content_ends(document: Document) -> list:
    """For each line, the offset where its content ends (before the line break)."""
    starts, text = document._line_starts, document.text
    ends = []
    last = len(starts) - 1
    for i, start in enumerate(starts):
        if i == last:
            ends.append(len(text))
            continue
        end = starts[i + 1]
        if text[end - 1] == "\n":
            end -= 1
        if end > start and text[end - 1] == "\r":
            end -= 1
        ends.append(end)
    return ends


def _spans_for(document: Document, raw_tokens) -> tuple:
    starts, ends = document._line_starts, _line_content_ends(document)
    size, lines = len(document.text), len(starts)

    def offset(row: int, col: int) -> int:
        if row > lines:
            return size
        line_start = starts[row - 1]
        return line_start + min(col, ends[row - 1] - line_start)

    tokens = []
    for tok in raw_tokens:
        start = offset(*tok.start)
        end = offset(*tok.end)
        tokens.append((tok.type, tok.string, Span(start, max(start, end))))
    return tuple(tokens)


def _raw_tokens(document: Document) -> tuple:
    return tuple(tokenize.generate_tokens(io.StringIO(document.text, newline=None).readline))


def _tokenize(document: Document) -> tuple:
    return _spans_for(document, _raw_tokens(document))


_CACHE: dict = {}
_CACHE_SIZE = 16


def parse_document(document: Document) -> PythonDocument:
    """Parse an engine ``Document``. Never raises on invalid source.

    The most recent parses are kept by ``(path, text)``: the knowledge rules of a run all read the same file,
    and parsing and tokenising once per rule dominated the analysis time. Parsed documents are never mutated.
    """
    key = (document.path, document.text)
    hit = _CACHE.get(key)
    if hit is None:
        hit = _parse_document(document)
        if len(_CACHE) >= _CACHE_SIZE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = hit
    return hit


def _parse_document(document: Document) -> PythonDocument:
    parsecount.bump()
    try:
        tree = astnodes.parse(document.text, document.path or "<python>")
    except (SyntaxError, ValueError) as exc:  # ValueError covers null bytes and unencodable text
        if isinstance(exc, SyntaxError):
            message, line, column = exc.msg, exc.lineno or 1, max((exc.offset or 1) - 1, 0)
        else:
            message, line, column = str(exc), 1, 0
        return PythonDocument(document, None, (), {"message": message, "line": line, "column": column})
    try:
        tokens = _raw_tokens(document)
    except (tokenize.TokenError, SyntaxError) as exc:
        return PythonDocument(document, None, (), {"message": f"tokenize: {exc}", "line": 1, "column": 0})
    return PythonDocument(document, tree, tokens, None)


def parse(text: str, path: str = "") -> PythonDocument:
    """Parse source text. ``path`` is used for the engine ``Document`` and error messages."""
    return parse_document(Document.from_text(path, text))
