"""Generic OWL detectors (REQ-JS-002). Detect-only. Lexer based: comments, strings and templates never match."""

import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.javascript import lexer
from odooflux.rules.shared.emit import finding

_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_CLASS = re.compile(r"\bclass\s+[\w$]+\s+extends\s+(?:[\w$.]+\.)?Component\s*\{")


def flag_component_method(document, ctx, *, method):
    """Report a method definition named ``method`` in a class that extends ``Component``. OWL 1.x components define
    ``mounted()``; OWL 2.x has the ``onMounted`` hook and no such method (EV-395)."""
    if not _IDENTIFIER.fullmatch(method):
        raise ValueError(f"not a method name: {method!r}")
    text = document.text
    code = "".join(text[t.start:t.end] if t.kind == "code" else re.sub(r"[^\n]", " ", text[t.start:t.end])
                   for t in lexer.tokenize(text))
    definition = re.compile(r"^[ \t]*(?:async\s+)?(" + re.escape(method) + r")\s*\([^)]*\)\s*\{", re.M)
    spans = []
    for cls in _CLASS.finditer(code):
        depth, end = 1, cls.end()
        while end < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[end], 0)
            end += 1
        for m in definition.finditer(code, cls.end(), end):
            spans.append(Span(m.start(1), m.end(1)))
    return [finding(document, ctx, span) for span in spans]
