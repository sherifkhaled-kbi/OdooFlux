# Data Model: Structured Transformations

Extends the planning contracts in
[docs/planning/architecture/CONTRACTS.md](../../docs/planning/architecture/CONTRACTS.md).

## Span

`(start, end)` character offsets into the decoded document text, half-open, `0 ≤ start ≤ end ≤
len(text)`. Derived `line`, `column`, `end_line`, `end_column` are 1-based lines and 0-based
character columns. Conversions are exact for any Unicode text.

## Document (base)

| Field | Notes |
|---|---|
| `path`, `kind` | `python`, `xml_view`, `xml_data`, `qweb`, `manifest`, `js`, `css`, `csv_acl` |
| `raw` | Original bytes |
| `text` | Decoded text (encoding detected: BOM → UTF-8 → declared XML encoding → Python coding cookie → UTF-8 with replacement + finding) |
| `encoding`, `bom`, `newline` | Preserved on write (`\n`, `\r\n`, `\r`, or `mixed`) |
| `sha256` | Of `raw` |
| `parse_error` | `null` or `{message, line, column}` |

## PythonDocument

Adds `tree` (ast.Module), `tokens` (list of `(type, string, span)`), and query helpers:
`decorators(func)`, `calls(name_pattern)`, `keyword(call, name)`, `class_attrs(cls, name)`,
`imports()`, `comment_spans()`.

## XmlDocument

Adds `elements`: list of `XmlElement{ tag, span (full element), start_tag_span, attrs:
[XmlAttr], children_index, parent_index }` and `XmlAttr{ name, name_span, value_span (excluding
quotes), quote_char, raw_value, value (entity-decoded) }`. Comments and processing instructions
are recorded with spans.

## JsDocument

Adds `adapter_available: bool`, `tree` (adapter tree or `null`), and `tokens` from the fallback
lexer (`string`, `template`, `comment`, `regex`, `code`) with spans.

## EditBatchResult

`{ applied: [Edit], rejected: [Edit], text: new_text, preserved_ok: bool }`. `preserved_ok`
comes from the byte-preservation check.

## ModifierConversion

| Field | Notes |
|---|---|
| `element_span` | Start tag of the element |
| `inputs` | `attrs` raw text, `states` raw text, existing `invisible/readonly/required/column_invisible` |
| `mode` | `literal` or `falsy` |
| `outputs` | Map attribute → expression, or `null` |
| `edits` | Edits replacing/removing the attributes |
| `unconverted` | List of `{key, reason}` |
| `warnings` | e.g. `no-state-field-check` |

## Corpus fixtures

`tests/golden_fixtures/transformations/{python,xml,js,converter}/<case>/{input.*,expected.*,meta.json}`.
`meta.json` holds `{ "description", "operations", "expect": "edit|no-edit|reject", "reason" }`.
