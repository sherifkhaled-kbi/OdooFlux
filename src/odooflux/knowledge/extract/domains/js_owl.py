"""JavaScript / OWL extractor (T051; REQ-KAP-011, REQ-KAP-004; diff-extractor contract, Domains and facts: js_owl).

Structural parsing uses the optional tree-sitter adapter (`odooflux.parsers.javascript.treesitter_adapter`), injected by the composition root
(`parsers.extract_toolkit`). When the adapter or its `js` extra is missing, `handles` is False for every `.js` file, so the
driver records each one UNSUPPORTED with NO_JS_ADAPTER: never silently skipped, never a crash. There is no regex
fallback: a structural parser exists, so it is the only source of facts.

Facts (one per subject per file):
- `export`: declared names (class, function, const/let/var), `export { a as b }` clauses and `export default`;
  subject `addon.name`, so a move between files is a MOVED change;
- `import`: one per `import` statement, keyed by path and module, with the bound names in attrs;
- `registry` / `service`: `registry.category(C).add(KEY, ...)`, keyed `addon::C::KEY`;
- `template`: `static template = "name"` in a class body, keyed `addon::template::name`.
`body_digest` is the whitespace-insensitive sha256 of the statement text, so reformatting alone is not a change.
Nothing is executed: the source is read as bytes and parsed.
"""

import hashlib

from odooflux.knowledge.extract.driver import ParseFailure, Unsupported
from odooflux.knowledge.extract.domains.xml_views import fact

__all__ = ["JsOwlExtractor", "EXTRACTORS", "adapter"]

_DECLARATIONS = ("class_declaration", "function_declaration", "generator_function_declaration")
_VARIABLES = ("lexical_declaration", "variable_declaration")


def _addon_of(path: str) -> str:
    parts = path.split("/")
    if "addons" in parts:
        i = parts.index("addons")
        return parts[i + 1] if len(parts) > i + 2 else ""
    return parts[0] if len(parts) > 1 else ""


def _text(data: bytes, node) -> str:
    return data[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _digest(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _line(node) -> int:
    return node.start_point[0] + 1


def _walk(root):
    stack = [root]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _string_value(node, data: bytes):
    if node is None or node.type != "string":
        return None
    raw = _text(data, node)
    return raw[1:-1] if len(raw) >= 2 else ""


def _first_string(arguments, data: bytes):
    if arguments is None:
        return None
    for child in arguments.named_children:
        return _string_value(child, data) if child.type == "string" else None
    return None


def _prop(member, data: bytes):
    prop = member.child_by_field_name("property")
    return _text(data, prop) if prop is not None else None


def _registry_call(node, data: bytes):
    """(category, key) for `registry.category(C).add(KEY, ...)`, else None."""
    if node.type != "call_expression":
        return None
    callee = node.child_by_field_name("function")
    if callee is None or callee.type != "member_expression" or _prop(callee, data) != "add":
        return None
    inner = callee.child_by_field_name("object")
    if inner is None or inner.type != "call_expression":
        return None
    inner_callee = inner.child_by_field_name("function")
    if inner_callee is None or inner_callee.type != "member_expression" or _prop(inner_callee, data) != "category":
        return None
    base = inner_callee.child_by_field_name("object")
    if base is None or _text(data, base) != "registry":
        return None
    category = _first_string(inner.child_by_field_name("arguments"), data)
    key = _first_string(node.child_by_field_name("arguments"), data)
    if category is None or key is None:
        return None
    return category, key


def _declared_names(declaration, data: bytes) -> list:
    if declaration.type in _DECLARATIONS:
        name = declaration.child_by_field_name("name")
        return [_text(data, name)] if name is not None else []
    if declaration.type in _VARIABLES:
        names = []
        for declarator in declaration.named_children:
            name = declarator.child_by_field_name("name") if declarator.type == "variable_declarator" else None
            if name is not None and name.type == "identifier":
                names.append(_text(data, name))
        return names
    return []


def _export_facts(node, data: bytes, addon: str) -> list:
    line, digest = _line(node), _digest(_text(data, node))
    if any(child.type == "default" for child in node.children):
        return [fact(f"{addon}.default", "export", {"form": "default"}, digest, line)]
    declaration = node.child_by_field_name("declaration")
    if declaration is not None:
        return [fact(f"{addon}.{name}", "export", {"form": declaration.type}, digest, line)
                for name in _declared_names(declaration, data)]
    out = []
    for clause in node.named_children:
        if clause.type != "export_clause":
            continue
        for spec in clause.named_children:
            if spec.type != "export_specifier":
                continue
            local = spec.child_by_field_name("name")
            alias = spec.child_by_field_name("alias")
            local_name = _text(data, local) if local is not None else ""
            exported = _text(data, alias) if alias is not None else local_name
            out.append(fact(f"{addon}.{exported}", "export", {"form": "clause", "local": local_name}, digest, line))
    return out


def _import_fact(node, data: bytes, path: str):
    module = _string_value(node.child_by_field_name("source"), data)
    if module is None:
        return None
    names = sorted({_text(data, n) for n in _walk(node) if n.type == "identifier"})
    return fact(f"{path}::import::{module}", "import", {"names": names, "source": module},
                _digest(_text(data, node)), _line(node))


def _first_error_line(root) -> int:
    for node in _walk(root):
        if node.type == "ERROR" or node.is_missing:
            return _line(node)
    return _line(root)


class JsOwlExtractor:
    domain = "js_owl"
    parser = "tree-sitter-javascript"

    def handles(self, path: str, toolkit=None) -> bool:
        return path.endswith(".js") and toolkit is not None and toolkit.javascript_available()

    def facts(self, text: str, path: str, toolkit=None) -> list:
        if toolkit is None or not toolkit.javascript_available():
            raise Unsupported("NO_JS_ADAPTER: the optional tree-sitter JavaScript adapter is not available")
        ts = toolkit.javascript()
        data = text.encode("utf-8")
        root = ts.parse(text).root_node
        if root.has_error:
            raise ParseFailure("PARSE_ERROR", f"JavaScript syntax error at line {_first_error_line(root)}")
        addon = _addon_of(path)
        out = []
        for node in root.named_children:
            if node.type == "export_statement":
                out.extend(_export_facts(node, data, addon))
            elif node.type == "import_statement":
                imported = _import_fact(node, data, path)
                if imported is not None:
                    out.append(imported)
        for node in _walk(root):
            entry = _registry_call(node, data)
            if entry is not None:
                category, key = entry
                kind = "service" if category == "services" else "registry"
                out.append(fact(f"{addon}::{category}::{key}", kind, {"category": category, "key": key},
                                _digest(_text(data, node)), _line(node)))
            elif node.type == "field_definition" and _prop(node, data) == "template":
                name = _string_value(node.child_by_field_name("value"), data)
                if name is not None:
                    out.append(fact(f"{addon}::template::{name}", "template", {"name": name},
                                    _digest(_text(data, node)), _line(node)))
        return out


EXTRACTORS = (JsOwlExtractor(),)
