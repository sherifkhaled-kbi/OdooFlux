"""Manifest extractor (T050; REQ-KAP-011; diff-extractor contract, Domains and facts: manifest).

Handles `__manifest__.py`. The manifest must be exactly one dict literal, read with `ast.literal_eval`; anything else
(a call, a name, a statement, an open call) is a ParseFailure, and nothing is imported or executed. Facts:
- `version`, `license`, `installable` (kind `manifest`, value in attrs, so a change is SIGNATURE_CHANGED with from/to);
- one `depends.<module>` fact per dependency (kind `dependency`, so an added dependency is ADDED);
- one `data.<file>` fact per data file (kind `data_file`).
`read_manifest` is shared with the assets extractor.
"""

import ast
import os

from odooflux.knowledge.extract.driver import ParseFailure
from odooflux.knowledge.extract.domains.xml_views import fact

__all__ = ["ManifestExtractor", "EXTRACTORS", "read_manifest"]

SCALAR_KEYS = ("version", "license", "installable")


def read_manifest(text: str, path: str):
    """(value, dict node) of a manifest. Raises ParseFailure unless the module is one dict literal."""
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as exc:
        raise ParseFailure("PARSE_ERROR", f"manifest does not parse: {exc}") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr) or not isinstance(tree.body[0].value, ast.Dict):
        raise ParseFailure("PARSE_ERROR", "manifest must be a single dict literal")
    node = tree.body[0].value
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise ParseFailure("PARSE_ERROR", f"manifest is not a literal: {exc}") from exc
    return value, node


def key_lines(node: ast.Dict) -> dict:
    return {k.value: k.lineno for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


class ManifestExtractor:
    domain = "manifest"
    parser = "manifest-literal"

    def handles(self, path: str, toolkit=None) -> bool:
        return os.path.basename(path) == "__manifest__.py"

    def facts(self, text: str, path: str, toolkit=None) -> list:
        value, node = read_manifest(text, path)
        lines = key_lines(node)
        out = []
        for key in SCALAR_KEYS:
            if key in value:
                out.append(fact(key, "manifest", {"value": value[key]}, "", lines.get(key, 1)))
        for key, kind, prefix in (("depends", "dependency", "depends."), ("data", "data_file", "data.")):
            entries = value.get(key, [])
            if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
                raise ParseFailure("PARSE_ERROR", f"{key} must be a list of strings")
            for entry in entries:
                out.append(fact(prefix + entry, kind, {}, "", lines.get(key, 1)))
        return out


EXTRACTORS = (ManifestExtractor(),)
