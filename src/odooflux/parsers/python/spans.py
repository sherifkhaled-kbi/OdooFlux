"""Python span locators (REQ-PY-001). Contract: specs/005-structured-transformations/contracts/span-locators.md.

All offsets are character offsets into ``doc.text``. AST columns are UTF-8 byte offsets and are
converted per line. Decorator spans are whole lines; keyword spans are token-aware.
"""

import ast
import bisect
import tokenize
import unicodedata

from odooflux.core.engine.documents import Span
from odooflux.parsers.python.document import PythonDocument
from odooflux.utils import astnodes

all_nodes = astnodes.all_nodes  # every node of a tree, cached per tree object


_HSPACE = " \t\f"
_DEF_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def dotted_name(node):
    """``a.b.c`` for a Name/Attribute chain, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _in_order(nodes):
    return sorted(nodes, key=lambda n: (n.lineno, n.col_offset))


def decorators_named(doc: PythonDocument, name: str) -> list:
    """Decorator expressions (``Call`` or plain) whose callee dotted name is ``name``, in document order."""
    if doc.tree is None:
        return []
    found = []
    for node in ast.walk(doc.tree):
        if isinstance(node, _DEF_NODES):
            for dec in node.decorator_list:
                callee = dec.func if isinstance(dec, ast.Call) else dec
                if dotted_name(callee) == name:
                    found.append(dec)
    return _in_order(found)


def calls_named(doc: PythonDocument, name: str) -> list:
    if doc.tree is None:
        return []
    return _in_order(n for n in ast.walk(doc.tree) if isinstance(n, ast.Call) and dotted_name(n.func) == name)


def attributes_named(doc: PythonDocument, name: str) -> list:
    if doc.tree is None:
        return []
    return _in_order(n for n in ast.walk(doc.tree) if isinstance(n, ast.Attribute) and dotted_name(n) == name)


def keywords_named(call: ast.Call, keyword: str) -> list:
    return [kw for kw in call.keywords if kw.arg == keyword]


def _line_bounds(doc: PythonDocument, line: int):
    """``(start, content_end, next_start)`` for a 1-based line; content excludes the line break."""
    text = doc.text
    start = doc.document.offset(line, 0)
    end = start
    while end < len(text) and text[end] not in "\r\n":
        end += 1
    if text.startswith("\r\n", end):
        nxt = end + 2
    elif end < len(text):
        nxt = end + 1
    else:
        nxt = end
    return start, end, nxt


def _line_of(doc: PythonDocument, offset: int) -> int:
    return doc.document.line_col(offset)[0]


def _char_offset(doc: PythonDocument, lineno: int, byte_col: int) -> int:
    start, end, _ = _line_bounds(doc, lineno)
    line_text = doc.text[start:end]
    if line_text.isascii():
        col = byte_col
    else:
        col = len(line_text.encode("utf-8")[:byte_col].decode("utf-8"))
    return start + col


def node_span(doc: PythonDocument, node) -> Span:
    """Exact span of an AST node that has source positions."""
    fields = (getattr(node, name, None) for name in ("lineno", "col_offset", "end_lineno", "end_col_offset"))
    if any(value is None for value in fields):
        raise ValueError(f"{type(node).__name__} has no source position")
    return Span(_char_offset(doc, node.lineno, node.col_offset),
                _char_offset(doc, node.end_lineno, node.end_col_offset))


def line_span(doc: PythonDocument, line: int, include_newline: bool = True) -> Span:
    start, end, nxt = _line_bounds(doc, line)
    return Span(start, nxt if include_newline else end)


def _sig_index_at(doc: PythonDocument, offset: int) -> int:
    return bisect.bisect_left(doc.significant_starts, offset)


def _decorator_at_token(doc: PythonDocument, decorator):
    target = node_span(doc, decorator).start
    index = _sig_index_at(doc, target) - 1
    sig = doc.significant_tokens
    if index < 0 or sig[index][0] != tokenize.OP or sig[index][1] != "@":
        raise ValueError("decorator is not preceded by '@'")
    return sig[index][2]


def decorator_removal_span(doc: PythonDocument, decorator) -> Span:
    """Whole lines of the decorator: from the start of its ``@`` line through the line break after its
    last line. Comment lines that follow are not part of the span (comments are never removed)."""
    at = _decorator_at_token(doc, decorator)
    at_line = _line_of(doc, at.start)
    line_start, _, _ = _line_bounds(doc, at_line)
    if doc.text[line_start:at.start].strip(_HSPACE):
        raise ValueError("decorator does not start its own line")
    _, _, next_start = _line_bounds(doc, decorator.end_lineno)
    return Span(line_start, next_start)


def _only_whitespace_on_lines(doc, start, end):
    """True when the text before ``start`` on its line and after ``end`` on its line is blank."""
    first_line = _line_of(doc, start)
    last_line = _line_of(doc, end)
    line_start, _, _ = _line_bounds(doc, first_line)
    _, last_end, _ = _line_bounds(doc, last_line)
    return (not doc.text[line_start:start].strip(_HSPACE)
            and not doc.text[end:last_end].strip(_HSPACE)), line_start, last_end


def keyword_removal_span(doc: PythonDocument, call: ast.Call, keyword) -> Span:
    """Span removing one keyword argument with exactly one separating comma.

    - followed by a comma: the keyword, the comma and the blanks after it (or the blank before it when
      nothing follows, so ``,)`` keeps its shape);
    - last with a preceding comma: the preceding comma through the keyword end;
    - sole argument: the keyword alone.
    When the keyword occupies whole lines, those lines are removed.
    """
    k = node_span(doc, keyword)
    text = doc.text
    sig = doc.significant_tokens
    j = _sig_index_at(doc, k.end)
    nxt = sig[j] if j < len(sig) else None
    prev = sig[_sig_index_at(doc, k.start) - 1] if _sig_index_at(doc, k.start) > 0 else None

    if nxt is not None and nxt[1] == ",":
        comma = nxt[2]
        end = comma.end
        while end < len(text) and text[end] in _HSPACE:
            end += 1
        start = k.start
        if end == comma.end:
            while start > 0 and text[start - 1] in _HSPACE:
                start -= 1
    elif prev is not None and prev[1] == ",":
        return Span(prev[2].start, k.end)
    else:
        start, end = k.start, k.end

    whole, line_start, line_end = _only_whitespace_on_lines(doc, start, end)
    if whole:
        return Span(line_start, _line_bounds(doc, _line_of(doc, end))[2])
    return Span(start, end)


def keyword_rename_span(doc: PythonDocument, keyword) -> Span:
    """Span of the keyword name token only (``**kwargs`` has no name and raises ValueError)."""
    if keyword.arg is None:
        raise ValueError("keyword has no name (**mapping)")
    k = node_span(doc, keyword)
    sig = doc.significant_tokens
    index = _sig_index_at(doc, k.start)
    if index >= len(sig):
        raise ValueError("keyword name token not found")
    tok_type, tok_text, tok_span = sig[index]
    if tok_type != tokenize.NAME or tok_span.start != k.start \
            or unicodedata.normalize("NFKC", tok_text) != keyword.arg:
        raise ValueError("keyword name token not found")
    return tok_span
