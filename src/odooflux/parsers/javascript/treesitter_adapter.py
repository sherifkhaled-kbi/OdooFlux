"""Optional tree-sitter adapter with lazy import (REQ-JS-001, REQ-ARC-001).

``tree_sitter`` and ``tree_sitter_javascript`` come from the ``js`` extra (D-02) and are imported only inside
functions, never at module import. ``available()`` reports whether they can be loaded. The adapter satisfies the
validator protocol: ``available()`` and ``has_errors(text)`` (``None`` when it cannot decide).
"""

import os

_parser = None


def _load_parser():
    global _parser
    if _parser is None:
        import tree_sitter
        import tree_sitter_javascript
        language = tree_sitter.Language(tree_sitter_javascript.language())
        _parser = (tree_sitter.Parser(language), language)
    return _parser


def available() -> bool:
    if os.environ.get("ODOOFLUX_DISABLE_JS_ADAPTER", "") not in ("", "0"):
        return False  # masked (quickstart.md): behave as if the js extra is not installed
    try:
        _load_parser()
    except Exception:  # missing extra or incompatible binding
        return False
    return True


def parse(text: str):
    """Parse JavaScript source and return the tree-sitter Tree. Raises ImportError without the extra."""
    parser, _ = _load_parser()
    return parser.parse(text.encode("utf-8"))


def query(text: str, pattern: str) -> dict:
    """Run a tree-sitter query; returns {capture_name: [nodes]} (empty dict when nothing matches)."""
    import tree_sitter
    tree = parse(text)
    _, language = _load_parser()
    q = tree_sitter.Query(language, pattern)
    return tree_sitter.QueryCursor(q).captures(tree.root_node)


def has_errors(text: str):
    """True when the source has syntax errors, False when clean, None when the adapter is unavailable."""
    if not available():
        return None
    return bool(parse(text).root_node.has_error)
