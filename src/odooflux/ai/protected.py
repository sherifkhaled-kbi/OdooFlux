"""Protected-identifier and region-shape checks for AI replacements (REQ-AI-003, FR-006; legacy F-AI-7).

Protected: model fields, ``_name``/``_inherit``/``_inherits`` values, imported names (the module path may be
rewritten, the names may not go), XML ids, XML field references, ``ref`` targets and QWeb template names.
"""

import ast
import textwrap
import xml.etree.ElementTree as ET

_FIELD_ATTRS = ("_name", "_inherit", "_inherits")


def _top_nodes(text: str):
    """Top-level statements of a region (indented regions are wrapped), or None when it does not parse."""
    for candidate in (text, textwrap.dedent(text)):
        try:
            return ast.parse(candidate).body
        except (SyntaxError, ValueError):
            pass
    try:
        return ast.parse("if 1:\n" + text).body[0].body
    except (SyntaxError, ValueError, IndexError):
        return None


def _py_tree(text: str):
    nodes = _top_nodes(text)
    return None if nodes is None else ast.Module(body=nodes, type_ignores=[])


def _xml_root(text: str):
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        return None  # no DTD or entity declaration is ever accepted in a region
    try:
        return ET.fromstring(text.strip())
    except (ET.ParseError, ValueError):
        return None


def syntax_ok(path: str, text: str) -> bool:
    if path.endswith(".py"):
        return _top_nodes(text) is not None
    if path.endswith(".xml"):
        return _xml_root(text) is not None
    return True


def shape_ok(kind: str, path: str, before: str, after: str) -> bool:
    """The replacement must be the same construct as the region: same kind, same name or tag, nothing extra."""
    if kind in ("function", "class"):
        want = (ast.FunctionDef, ast.AsyncFunctionDef) if kind == "function" else (ast.ClassDef,)
        b, a = _top_nodes(before), _top_nodes(after)
        if not b or a is None or len(b) != 1 or len(a) != 1:
            return False
        return isinstance(a[0], want) and isinstance(b[0], want) and a[0].name == b[0].name
    if kind == "statement":
        b, a = _top_nodes(before), _top_nodes(after)
        if b is None or not a:
            return False
        defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        return sum(isinstance(n, defs) for n in a) <= sum(isinstance(n, defs) for n in b)
    if kind == "xml_element":
        b, a = _xml_root(before), _xml_root(after)
        return b is not None and a is not None and a.tag == b.tag
    return True


def _py_facts(tree) -> dict:
    facts = {"field": set(), "model": {}, "import": set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                targets, value = [], None
                if isinstance(stmt, ast.Assign):
                    targets, value = [t for t in stmt.targets if isinstance(t, ast.Name)], stmt.value
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    targets, value = [stmt.target], stmt.value
                for target in targets:
                    if target.id in _FIELD_ATTRS:
                        try:
                            facts["model"][f"{node.name}.{target.id}"] = repr(ast.literal_eval(value))
                        except (ValueError, SyntaxError):
                            facts["model"][f"{node.name}.{target.id}"] = ast.dump(value)
                    elif (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                          and isinstance(value.func.value, ast.Name) and value.func.value.id == "fields"):
                        facts["field"].add(f"{node.name}.{target.id}")
        elif isinstance(node, ast.Import):
            facts["import"].update((a.asname or a.name.split(".")[0]) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            facts["import"].update((a.asname or a.name) for a in node.names)
    return facts


def _xml_facts(root) -> set:
    facts = set()
    for el in root.iter():
        if el.get("id"):
            facts.add(("id", el.get("id")))
        if el.tag == "field" and el.get("name"):
            facts.add(("field", el.get("name")))
        if el.get("ref"):
            facts.add(("ref", el.get("ref")))
        if el.tag == "record" and el.get("model"):
            facts.add(("model", el.get("model")))
        if el.get("t-name"):
            facts.add(("t-name", el.get("t-name")))
    return facts


def protected_changes(path: str, before: str, after: str) -> list:
    """Human-readable reasons the replacement touches protected identifiers; an empty list means none changed.

    An original that cannot be parsed is itself reported: the check cannot vouch for the edit.
    """
    if path.endswith(".py"):
        tb, ta = _py_tree(before), _py_tree(after)
        if tb is None:
            return ["original region cannot be parsed; protected identifiers cannot be compared"]
        if ta is None:
            return ["replacement cannot be parsed"]
        fb, fa = _py_facts(tb), _py_facts(ta)
        out = [f"field removed or renamed: {n}" for n in sorted(fb["field"] - fa["field"])]
        out += [f"{k} changed: {fb['model'][k]} -> {fa['model'].get(k)}" for k in sorted(fb["model"])
                if fa["model"].get(k) != fb["model"][k]]
        out += [f"import removed: {n}" for n in sorted(fb["import"] - fa["import"])]
        return out
    if path.endswith(".xml"):
        rb, ra = _xml_root(before), _xml_root(after)
        if rb is None:
            return ["original region cannot be parsed; protected identifiers cannot be compared"]
        if ra is None:
            return ["replacement cannot be parsed"]
        return [f"xml {kind} removed or changed: {value}" for kind, value in sorted(_xml_facts(rb) - _xml_facts(ra))]
    return []
