"""Generic JavaScript detectors (REQ-JS-002). Detect-only; nothing here edits a file.

Detection runs on the stdlib lexer (``parsers.javascript.lexer``), so text inside comments, strings (other than the
service name itself), template literals and regexes never matches. The result does not depend on whether the
optional tree-sitter adapter is installed.
"""

import re

from odooflux.core.engine.documents import Span
from odooflux.parsers.javascript import lexer
from odooflux.rules.shared.emit import finding

_SERVICES_PROPERTY = re.compile(r"\bservices\s*\.\s*rpc(?![\w$])")
_SERVICE_NAME_CONTEXT = re.compile(
    r"(useService\s*\(|\bservices\s*\[|category\s*\(\s*(['\"])services\2\s*\)\s*\.\s*get\s*\()\s*$")


def flag_rpc_service(document, ctx):
    """Report uses of the ``rpc`` service, which the target series no longer registers (EV-120): ``useService("rpc")``,
    ``env.services.rpc``, ``services["rpc"]`` and ``registry.category("services").get("rpc")``."""
    text = document.text
    spans = []
    for token in lexer.tokenize(text):
        if token.kind == "code":
            spans += [Span(token.start + m.start(), token.start + m.end())
                      for m in _SERVICES_PROPERTY.finditer(text[token.start:token.end])]
        elif token.kind == "string" and text[token.start + 1:token.end - 1] == "rpc":
            if _SERVICE_NAME_CONTEXT.search(text[:token.start]):
                spans.append(Span(token.start, token.end))
    return [finding(document, ctx, span) for span in sorted(spans, key=lambda s: (s.start, s.end))]


_DEFINE_CONTEXT = re.compile(r"\bodoo\s*\.\s*define\s*\(\s*$")
_FUNCTION_SECOND_ARG = re.compile(r"^\s*,\s*(?:async\s+)?(?:function\b|\(?[\w\s,]*\)?\s*=>)")
_REGISTRY_ON = re.compile(r"\bserviceRegistry\s*\.\s*on\s*\(")


def flag_odoo_define_legacy_form(document, ctx):
    """Report ``odoo.define(name, function (require) {...})``: the two-argument form without a dependency array,
    which the newer module loader rejects (EV-390 accepts it in the older series; EV-391)."""
    text = document.text
    tokens = lexer.tokenize(text)
    spans = []
    for index, token in enumerate(tokens[:-1]):
        if token.kind != "string" or not _DEFINE_CONTEXT.search(text[:token.start]):
            continue
        following = tokens[index + 1]
        if following.kind == "code" and _FUNCTION_SECOND_ARG.match(text[following.start:following.end]):
            spans.append(Span(token.start, token.end))
    return [finding(document, ctx, span) for span in spans]


def flag_service_registry_on(document, ctx):
    """Report ``serviceRegistry.on(...)``: the older listener API; the newer series uses ``addEventListener`` (EV-393)."""
    text = document.text
    return [finding(document, ctx, Span(token.start + m.start(), token.start + m.end() - 1))
            for token in lexer.tokenize(text) if token.kind == "code"
            for m in _REGISTRY_ON.finditer(text[token.start:token.end])]


_LEGACY_WIDGET_CONTEXT = re.compile(r"(?:\bfrom|\bimport|\brequire\s*\()\s*$")
_LEGACY_WIDGET_PATH = re.compile(r"@web/legacy/js/core/widget(?:\.js)?")


def flag_legacy_widget_import(document, ctx):
    """Report imports of ``@web/legacy/js/core/widget``: the file is absent in the newer series (EV-392)."""
    text = document.text
    return [finding(document, ctx, Span(token.start, token.end))
            for token in lexer.tokenize(text)
            if token.kind == "string" and _LEGACY_WIDGET_PATH.fullmatch(text[token.start + 1:token.end - 1])
            and _LEGACY_WIDGET_CONTEXT.search(text[:token.start])]
