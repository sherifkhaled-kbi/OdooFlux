"""Docs adapter (REQ-KAP-007, REQ-KAP-011; source-adapter contract, diff-extractor contract).

`DocsAdapter` snapshots a local clone of odoo/documentation through the git-local adapter, restricted to `.rst`
files. `extract_rst` is a line-oriented reader (no HTML, no rst parser): it records section headings (a title line
over an underline), the `versionadded`, `versionchanged` and `deprecated` directives with their version argument
and body text, and every other directive as `unknown`. Nothing is dropped silently. `extract_snapshot` applies the
reader to the `.rst` entries of a snapshot and reports undecodable files.
"""

import copy
import re

from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter

__all__ = ["DocsAdapter", "extract_rst", "extract_snapshot", "KNOWN_DIRECTIVES"]

KNOWN_DIRECTIVES = ("versionadded", "versionchanged", "deprecated")
_UNDERLINE = re.compile(r"^([=\-~^\"'`:#*+<>_])\1*$")
_DIRECTIVE = re.compile(r"^(\s*)\.\. ([A-Za-z][\w-]*)::(.*)$")


class DocsAdapter:
    kind = "DOCS"

    def __init__(self, allow_list=None):
        self._git = GitLocalAdapter("DOCS", allow_list=allow_list)

    def probe(self, spec: dict) -> dict:
        return self._git.probe(spec)

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        rst_only = copy.deepcopy(spec)
        scope = dict(rst_only.get("scope") or {})
        scope["include"] = ["*.rst"]  # `.rst` files only, whatever the spec says
        rst_only["scope"] = scope
        return self._git.snapshot(rst_only, store, created_at=created_at)


def extract_rst(text: str) -> dict:
    """Headings, known directives and unknown directives of one `.rst` document. Line numbers are 1-based."""
    lines = text.splitlines()
    headings, directives, unknown = [], [], []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        match = _DIRECTIVE.match(line)
        if match:
            indent, name, arg = len(match.group(1)), match.group(2), match.group(3).strip()
            body, j = [], i + 1
            while j < n and (not lines[j].strip() or _indent(lines[j]) > indent):
                if lines[j].strip():
                    body.append(lines[j].strip())
                j += 1
            if name in KNOWN_DIRECTIVES:
                directives.append({"line": i + 1, "name": name, "version": arg, "text": " ".join(body)})
            else:
                unknown.append({"line": i + 1, "name": name})
            i = j
            continue
        if (i + 1 < n and line.strip() and not _UNDERLINE.match(line.strip())
                and _UNDERLINE.match(lines[i + 1].strip()) and len(lines[i + 1].rstrip()) >= len(line.rstrip())):
            headings.append({"line": i + 1, "title": line.strip(), "underline": lines[i + 1].strip()[0]})
            i += 2
            continue
        i += 1
    return {"headings": headings, "directives": directives, "unknown": unknown}


def extract_snapshot(snapshot: dict, store) -> dict:
    """Apply `extract_rst` to every `.rst` entry of *snapshot*, read through the verifying blob store."""
    files, undecodable = [], []
    for entry in sorted(snapshot["entries"], key=lambda e: e["path"]):
        if not entry["path"].endswith(".rst"):
            continue
        data = store.get(entry["sha256"])
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            undecodable.append({"path": entry["path"], "reason": "NON_UTF8"})
            continue
        files.append({"path": entry["path"], **extract_rst(text)})
    return {"files": files, "undecodable": undecodable}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())
