"""Assets extractor (T050; REQ-KAP-011; diff-extractor contract, Domains and facts: assets).

Handles `__manifest__.py` and reports bundle membership from the `assets` mapping, one `member` fact per entry keyed
`bundle::file`. A plain entry is the file path; a directive tuple `(directive, target, file)` is keyed by its file
and keeps the directive and target in attrs. Anything else in the mapping is a ParseFailure.
"""

import os

from odooflux.knowledge.extract.driver import ParseFailure
from odooflux.knowledge.extract.domains.manifest import key_lines, read_manifest
from odooflux.knowledge.extract.domains.xml_views import fact

__all__ = ["AssetsExtractor", "EXTRACTORS"]


class AssetsExtractor:
    domain = "assets"
    parser = "manifest-literal"

    def handles(self, path: str, toolkit=None) -> bool:
        return os.path.basename(path) == "__manifest__.py"

    def facts(self, text: str, path: str, toolkit=None) -> list:
        value, node = read_manifest(text, path)
        bundles = value.get("assets", {})
        if not isinstance(bundles, dict):
            raise ParseFailure("PARSE_ERROR", "assets must be a mapping of bundle to list")
        line = key_lines(node).get("assets", 1)
        out = []
        for bundle in sorted(bundles):
            entries = bundles[bundle]
            if not isinstance(entries, list):
                raise ParseFailure("PARSE_ERROR", f"assets bundle {bundle} must be a list")
            for entry in entries:
                if isinstance(entry, str):
                    attrs, target = {"directive": None, "target": None}, entry
                elif isinstance(entry, (tuple, list)) and len(entry) == 3 and all(isinstance(x, str) for x in entry):
                    attrs, target = {"directive": entry[0], "target": entry[1]}, entry[2]
                else:
                    raise ParseFailure("PARSE_ERROR", f"assets bundle {bundle} has an unknown entry {entry!r}")
                out.append(fact(f"{bundle}::{target}", "member", attrs, "", line))
        return out


EXTRACTORS = (AssetsExtractor(),)
