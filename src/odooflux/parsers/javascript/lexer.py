"""Stdlib JavaScript lexer for code, string, template, comment, and regex spans (REQ-JS-001).

Detectors that run without the tree-sitter adapter match only inside ``code`` tokens, so a pattern
never fires on text in a string, comment, template part, or regex literal. This is a lexer, not a
parser. Regex-versus-division is decided by the previous significant token, so a regex directly
after ``)`` (for example ``if (x) /re/.test(s)``) is read as division. Tokens tile the input:
their concatenation equals the text, and line breaks are kept inside the tokens they belong to.
"""

from dataclasses import dataclass

from odooflux.core.engine.documents import Span
from odooflux.utils import parsecount

KINDS = ("code", "string", "template", "comment", "regex")

# After these keywords a "/" starts a regex literal rather than a division.
_REGEX_AFTER_KEYWORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
    "case", "do", "else", "yield", "await",
})
_LINE_BREAKS = frozenset("\r\n  ")


@dataclass(frozen=True)
class JsToken:
    kind: str
    start: int
    end: int


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in "_$"


def _scan_string(text: str, i: int) -> int:
    """End offset of the quoted string starting at *i*. An unterminated string ends at a line break."""
    quote, n, j = text[i], len(text), i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 3 if text[j + 1:j + 3] == "\r\n" else 2  # escaped char, or a line continuation
            continue
        if ch == quote:
            return j + 1
        if ch in _LINE_BREAKS:
            return j
        j += 1
    return n


def _scan_template(text: str, i: int):
    """Scan template characters from *i* (just after a backtick or a closing ``}``).

    Returns ``(end, opens_substitution)``: the end offset, and whether the scan stopped at ``${``.
    """
    n, j = len(text), i
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "`":
            return j + 1, False
        if ch == "$" and j + 1 < n and text[j + 1] == "{":
            return j + 2, True
        j += 1
    return n, False


def _scan_regex(text: str, i: int):
    """End offset of a regex literal starting at *i* (a ``/``), flags included; None if not one."""
    n, j, in_class = len(text), i + 1, False
    while j < n:
        ch = text[j]
        if ch in _LINE_BREAKS:
            return None
        if ch == "\\":
            if j + 1 < n and text[j + 1] in _LINE_BREAKS:
                return None
            j += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "/":
            j += 1
            while j < n and _is_word_char(text[j]):
                j += 1
            return j
        j += 1
    return None


_MEMO: dict = {}
_MEMO_SIZE = 16


def tokenize(text: str) -> list:
    """Split *text* into contiguous ``JsToken`` objects covering the whole input.

    The most recent results are kept by text: every JavaScript rule of a run lexes the same file in turn
    (hot path). Callers must not modify the returned list."""
    hit = _MEMO.get(text)
    if hit is None:
        hit = _tokenize_uncached(text)
        if len(_MEMO) >= _MEMO_SIZE:
            _MEMO.pop(next(iter(_MEMO)))
        _MEMO[text] = hit
    return hit


def _tokenize_uncached(text: str) -> list:
    """The lexer itself."""
    parsecount.bump()
    tokens = []
    n = len(text)
    code_start = 0
    regex_allowed = True
    substitutions = []  # one brace counter per open template substitution ``${ ... }``

    def emit_literal(kind: str, start: int, end: int) -> None:
        nonlocal code_start
        if start > code_start:
            tokens.append(JsToken("code", code_start, start))
        tokens.append(JsToken(kind, start, end))
        code_start = end

    def emit_template(start: int) -> int:
        """Emit the template part that begins at *start* (a backtick or a closing brace)."""
        nonlocal regex_allowed
        end, opens = _scan_template(text, start + 1)
        emit_literal("template", start, end)
        if opens:
            substitutions.append(0)
        regex_allowed = opens
        return end

    i = 0
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = i + 2
            while end < n and text[end] not in _LINE_BREAKS:
                end += 1
            emit_literal("comment", i, end)
            i = end
            continue
        if ch == "/" and nxt == "*":
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            emit_literal("comment", i, end)
            i = end
            continue
        if ch in "'\"":
            end = _scan_string(text, i)
            emit_literal("string", i, end)
            regex_allowed = False
            i = end
            continue
        if ch == "`":
            i = emit_template(i)
            continue
        if ch == "/" and regex_allowed:
            end = _scan_regex(text, i)
            if end is not None:
                emit_literal("regex", i, end)
                regex_allowed = False
                i = end
                continue
        if ch == "}" and substitutions:
            if substitutions[-1] == 0:
                substitutions.pop()
                i = emit_template(i)
                continue
            substitutions[-1] -= 1
            regex_allowed = False
            i += 1
            continue
        if ch == "{" and substitutions:
            substitutions[-1] += 1
        if _is_word_char(ch):
            end = i + 1
            while end < n and _is_word_char(text[end]):
                end += 1
            regex_allowed = text[i:end] in _REGEX_AFTER_KEYWORDS
            i = end
            continue
        regex_allowed = ch not in ")]}"
        i += 1

    if code_start < n:
        tokens.append(JsToken("code", code_start, n))
    return tokens


def code_spans(text: str) -> list:
    """Spans of the code tokens of *text* (everything that is not a string, template, comment, or regex)."""
    return [Span(t.start, t.end) for t in tokenize(text) if t.kind == "code"]
