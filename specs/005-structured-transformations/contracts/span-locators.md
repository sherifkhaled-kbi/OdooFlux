# Contract: Span locators and edit helpers

## Python (`src/odooflux/parsers/python/`)

| Function | Returns | Obligations |
|---|---|---|
| `parse(text) -> PythonDocument` | Document with `tree`, `tokens`, or `parse_error` | Never raises on invalid code |
| `node_span(doc, node) -> Span` | Exact span of any AST node | Handles UTF-8 column offsets |
| `line_span(doc, line, include_newline=True) -> Span` | Whole physical line | |
| `decorator_removal_span(doc, decorator) -> Span` | From the start of the decorator's line through its newline, plus immediately following comment-only lines that precede the next decorator/def | Result after removal compiles (corpus) |
| `keyword_removal_span(doc, call, keyword) -> Span` | Keyword span including exactly one separating comma and the adjoining whitespace | Result compiles; no `(,` and no `,)` artefacts except when the original had a trailing comma |
| `keyword_rename_span(doc, keyword) -> Span` | Span of the keyword name only | |

Edit helpers in `src/odooflux/transformers/python.py` build `Edit` objects from these spans
(`remove_decorator`, `remove_keyword`, `rename_keyword`, `replace_call_name`, `replace_attribute`).

## XML (`src/odooflux/parsers/xml/`)

| Function | Returns | Obligations |
|---|---|---|
| `parse(text) -> XmlDocument` | Elements with spans, or `parse_error` | Never raises |
| `find(doc, tag=None, attr=None) -> list[XmlElement]` | Matching elements | Order = document order |
| `attr_span(el, name, part='whole'\|'value') -> Span` | Exact span | Value span excludes quotes |
| `insert_attr_point(el) -> int` | Offset after the last attribute | Before `/>` or `>` |

Edit helpers in `src/odooflux/transformers/xml.py`: `set_attr`, `remove_attr`, `rename_tag`
(start and end tag together), `replace_element`. Output values are escaped for the chosen
quote character.

## JavaScript (`src/odooflux/parsers/javascript/`)

| Function | Returns | Obligations |
|---|---|---|
| `available() -> bool` | Adapter importable and grammar loaded | |
| `parse(text) -> JsDocument` | Tree (adapter) or tokens (fallback) | Never raises |
| `code_spans(doc) -> list[Span]` | Spans that are code (not strings/comments/regex) | Fallback detectors only match inside these |
| `query(doc, pattern) -> list[Span]` | Adapter-only structural query; raises `AdapterUnavailable` without the adapter | |
| `has_errors(doc) -> bool \| None` | `None` when unavailable | Used by REQ-JS-004 validator |
