"""Region selection and request construction (REQ-AI-004, FR-004, FR-011).

The smallest enclosing function, class body or XML element is sent, never a whole file. Line numbers in the
request refer to the text actually sent. Customer text goes only into the delimited <code> block.
"""

import ast
import bisect
import re
from dataclasses import dataclass
from xml.parsers import expat

from odooflux.ai.prompts.templates import v1
from odooflux.ai.providers.types import AIRequest, RESPONSE_SCHEMA

TEMPLATES = {v1.VERSION: v1}
DEFAULT_TEMPLATE = v1.VERSION
_NEWLINE = re.compile(r"\r\n|\r|\n")
DELIMITERS = ("<code>", "</code>")


@dataclass(frozen=True)
class Region:
    path: str
    start: int
    end: int
    kind: str  # function | class | statement | xml_element
    text: str
    first_line: int  # 1-based line of the region's first character in the file
    last_line: int


def _line_starts(text: str) -> list:
    return [0] + [m.end() for m in _NEWLINE.finditer(text)]


def _make(path, text, starts, start_line, end_line, kind) -> Region:
    """Whole lines ``start_line..end_line`` (1-based, inclusive), including the last line's newline."""
    start = starts[start_line - 1]
    end = starts[end_line] if end_line < len(starts) else len(text)
    return Region(path, start, end, kind, text[start:end], start_line, end_line)


def _python_region(path, text, line):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    starts = _line_starts(text)
    best = {"function": None, "class": None, "statement": None}

    def span(node):
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        return first, node.end_lineno

    def consider(kind, node):
        first, last = span(node)
        if first <= line <= last and (best[kind] is None or last - first < best[kind][1] - best[kind][0]):
            best[kind] = (first, last)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            consider("function", node)
        elif isinstance(node, ast.ClassDef):
            consider("class", node)
    for node in tree.body:
        consider("statement", node)
    for kind in ("function", "class", "statement"):
        if best[kind]:
            return _make(path, text, starts, best[kind][0], best[kind][1], kind)
    return None


def _tag_end(data: bytes, index: int) -> int:
    """Offset just past the '>' that closes the tag starting at ``index`` (quotes in attributes respected)."""
    quote = None
    i = index
    while i < len(data):
        c = data[i:i + 1]
        if quote:
            if c == quote:
                quote = None
        elif c in (b'"', b"'"):
            quote = c
        elif c == b">":
            return i + 1
        i += 1
    return len(data)


def _xml_region(path, text, line):
    data = text.encode("utf-8", errors="surrogateescape")
    stack, spans = [], []
    parser = expat.ParserCreate("utf-8")

    def start(_name, _attrs):
        stack.append(parser.CurrentByteIndex)

    def end(_name):
        begin = stack.pop()
        open_end = _tag_end(data, begin)
        if data[open_end - 2:open_end] == b"/>":  # empty-element tag: it closes where it opens
            spans.append((begin, open_end))
        else:
            spans.append((begin, _tag_end(data, parser.CurrentByteIndex)))

    parser.StartElementHandler, parser.EndElementHandler = start, end
    try:
        parser.Parse(data, True)
    except (expat.ExpatError, ValueError):
        return None
    byte_starts = [0] + [m.end() for m in re.finditer(rb"\r\n|\r|\n", data)]

    def line_of(offset):
        return bisect.bisect_right(byte_starts, offset)

    containing = [(b, e) for b, e in spans if line_of(b) <= line <= line_of(max(b, e - 1))]
    if not containing:
        return None
    begin, end_ = max(containing, key=lambda s: (s[0], -s[1]))  # innermost: latest start, then shortest
    first_line, last_line = line_of(begin), line_of(max(begin, end_ - 1))
    starts = _line_starts(text)
    # extend to whole lines when only whitespace shares them with the element
    char_begin = len(data[:begin].decode("utf-8", errors="surrogateescape"))
    char_end = len(data[:end_].decode("utf-8", errors="surrogateescape"))
    line_begin = starts[first_line - 1]
    line_end = starts[last_line] if last_line < len(starts) else len(text)
    if text[line_begin:char_begin].strip() == "" and text[char_end:line_end].strip() == "":
        return Region(path, line_begin, line_end, "xml_element", text[line_begin:line_end], first_line, last_line)
    return Region(path, char_begin, char_end, "xml_element", text[char_begin:char_end], first_line, last_line)


def select_region(path: str, text: str, line: int):
    """Smallest enclosing region for a finding at ``line`` (1-based), or None when the file cannot be parsed."""
    if path.endswith(".py"):
        return _python_region(path, text, line)
    if path.endswith(".xml"):
        return _xml_region(path, text, line)
    return None


@dataclass(frozen=True)
class PromptInfo:
    line_in_region: int
    template_version: str
    evidence_ids: tuple


def build_request(*, finding_line, rule_id, rule_message, meta, region, relpath, provider, model, target_step,
                  request_id, budget_ref, max_output_tokens, cache_key="",
                  template_version=DEFAULT_TEMPLATE):
    """Return ``(AIRequest, PromptInfo)``. Raises ``ValueError`` (reason code in the message) when the region cannot be
    sent safely: a delimiter inside the code, or a file kind that is not an allowed data category."""
    template = TEMPLATES[template_version]
    if any(d in region.text for d in DELIMITERS):
        raise ValueError("delimiter_in_region")
    if region.kind == "xml_element":
        category = "source_xml"
    elif region.path.endswith(".py"):
        category = "source_python"
    else:
        raise ValueError("unsupported_file_kind")
    evidence = tuple(getattr(meta, "evidence", ()) or ())
    line_in_region = finding_line - region.first_line + 1
    docs = (getattr(meta, "docs", "") or "")
    user = template.USER.format(
        rule_id=rule_id, rule_message=rule_message, rule_docs=(docs + "\n") if docs else "",
        evidence="".join(template.EVIDENCE.format(id=e["id"], excerpt=e["excerpt"]) for e in evidence),
        path=relpath, kind=region.kind, line_in_region=line_in_region, step=target_step, code=region.text)
    categories = (category,) + (("evidence_excerpt",) if evidence else ())
    request = AIRequest(
        request_id=request_id, model=model, system=template.SYSTEM,
        messages=[{"role": "user", "content": user}], response_schema=RESPONSE_SCHEMA,
        max_output_tokens=max_output_tokens, budget_ref=budget_ref, cache_key=cache_key,
        region={"path": relpath, "span": [region.start, region.end], "kind": region.kind},
        provider=provider, data_categories=categories, rule_id=rule_id,
        meta={"template_version": template_version, "evidence_ids": [e["id"] for e in evidence],
              "line_in_region": line_in_region})
    return request, PromptInfo(line_in_region, template_version, tuple(e["id"] for e in evidence))
