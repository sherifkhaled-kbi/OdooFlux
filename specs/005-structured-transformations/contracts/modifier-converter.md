# Contract: Modifier converter (`src/odooflux/transformers/modifiers.py`)

## `convert_element(doc, element, *, mode='falsy'|'literal', in_list_view: bool) -> ModifierConversion`

Inputs: an `XmlElement` carrying `attrs` and/or `states`.

Behaviour:
1. Parse the `attrs` value with `ast.literal_eval` after entity decoding. Names that are not
   literals (`parent`, `context`, `uid`, `active_id`, and dotted forms) are first replaced with
   placeholders and restored afterwards. A parse failure means the whole `attrs` is unconverted
   (`reason: unparseable-attrs`).
2. For each key in {`invisible`, `readonly`, `required`, `column_invisible`}, convert its domain
   with `domain_to_expression(domain, mode)`. For any other key (e.g. `column_invisible` outside
   a list view, or unknown keys), keep the key unconverted with a reason. If any key is
   unconverted, the original `attrs` attribute is kept, and only the converted keys are removed
   from it (rewritten dict) when at least one key converted.
3. `states="a,b"` → `state not in ['a', 'b']` for `invisible`.
4. Merge with existing attributes: `(existing) or (new)`. The existing value is preserved
   verbatim inside parentheses.
5. Emit edits:
   - remove `attrs` (or rewrite it with the remaining keys);
   - remove `states`;
   - set or replace each modifier attribute.
   No comments are inserted.

## `domain_to_expression(domain, mode) -> str | Unconvertible`

- Prefix normalisation: an implicit `&` between consecutive top-level terms.
- `&` → `(a and b)`; `|` → `(a or b)`; `!` → `not (a)`. Redundant parentheses are removed at
  the top level only.
- Leaf `(f, op, v)`:

| op | Output |
|---|---|
| `=`, `==` | `f == V` (mode `falsy`: `v is False` → `not f`) |
| `!=`, `<>` | `f != V` (mode `falsy`: `v is False` → `f`) |
| `<`, `<=`, `>`, `>=` | `f op V` |
| `in`, `not in` | `f in [..]` / `f not in [..]` (tuples become lists) |
| anything else | `Unconvertible("unsupported operator <op>")` |

- `V` is the Python repr of literals (strings with single quotes) or the restored placeholder
  text for context names. `f` may be dotted (`parent.state`) and is kept verbatim.
- Domains given as a string expression (already an expression) are returned unchanged.

## Corpus (minimum 60 cases)

Each case has: input element, mode, expected output attributes or the expected unconverted
reasons. Required groups:
- every operator;
- `&`, `|`, and `!` nesting to depth 3;
- falsy and literal modes;
- context names;
- list values;
- merge with an existing modifier;
- `states` alone and with `attrs`;
- `column_invisible` inside `<list>`/`<tree>`;
- entity-encoded values;
- multi-line `attrs`;
- unsupported operators;
- malformed dicts;
- unknown keys.
