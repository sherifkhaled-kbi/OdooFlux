#!/usr/bin/env python3
"""Maintainer script (not shipped): build the version-pinned view index of an official Odoo source tree (FR-021).

The index lists, for one Odoo series at one pinned commit SHA:

- the core modules that define at least one view (``modules``);
- every view external id defined by ``<record model="ir.ui.view">`` or ``<template>`` in a file named by the
  module manifest ``data`` key (so ids defined in ``data/`` files count, files outside the manifest do not),
  each mapped to the root of its inheritance tree (``views``);
- per inheritance-tree root, the sorted union of the ``name=`` and ``id=`` attribute values found anywhere in the
  arch of the tree (``anchors``). The union is deliberately generous so that an anchor reported missing is
  missing from every core view of that tree.

Two steps keep the extraction reproducible and offline-parsable:

``fetch``    downloads the ``addons/**.xml``/``__manifest__.py`` files of a pinned SHA (raw files at the pinned SHA, module list
             from compatibility/core_modules.json) into a cache directory that mirrors the repository layout. Needs network.
``extract``  parses a source (a cache directory, or a local git clone via ``git ls-tree``/``git cat-file``)
             with the standard library only. The output is deterministic: sorted keys, fixed layout, no
             timestamps; ``content_sha256`` covers ``views`` and ``anchors``.

Nothing is executed from the source tree: manifests are read with ``ast.literal_eval`` and XML with
``xml.etree`` (no entity expansion of external entities).
"""

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree

FORMAT = 1
MANIFEST = "__manifest__.py"
ROOTS = (("addons",), ("odoo", "addons"))
VERSION = re.compile(r"^\d+\.0$")
SKIP_DIRS = {"static", "tests", "i18n", "migrations"}
REF_CALL = re.compile(r"""ref\(\s*['"]([^'"]+)['"]\s*\)""")
DEFAULT_CORE_MODULES = Path(__file__).resolve().parents[1] / "src/odooflux/knowledge/compatibility/core_modules.json"
RULE_IDS = ("*.xml.inherit-id-missing-in-target", "*.xml.xpath-anchor-missing-in-target")
SCOPE = ("core modules under addons/ and odoo/addons/; xml files named by manifest 'data'; "
         "records of model ir.ui.view and <template> elements")


class DirSource:
    """Files below a directory that mirrors the repository layout (a fetch cache or a fixture)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def paths(self) -> list:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())

    def read(self, path: str) -> bytes:
        return (self.root / path).read_bytes()


class GitSource:
    """A local git clone read through ``git ls-tree`` and ``git cat-file`` (no checkout, no network)."""

    def __init__(self, repo: Path, sha: str):
        self.repo, self.sha = str(repo), sha

    def paths(self) -> list:
        out = subprocess.run(["git", "-C", self.repo, "ls-tree", "-r", "--name-only", self.sha],
                             check=True, capture_output=True, text=True).stdout
        return sorted(out.splitlines())

    def read(self, path: str) -> bytes:
        return subprocess.run(["git", "-C", self.repo, "show", f"{self.sha}:{path}"],
                              check=True, capture_output=True).stdout


def _module_of(path: str):
    """(root, module, relative path inside the module) for a file inside a core module, else None."""
    parts = path.split("/")
    for root in ROOTS:
        depth = len(root)
        if len(parts) > depth + 1 and tuple(parts[:depth]) == root:
            return root, parts[depth], "/".join(parts[depth + 1:])
    return None


def wanted(path: str) -> bool:
    """A manifest, or an xml file outside static/tests/i18n/migrations directories, of a core module."""
    hit = _module_of(path)
    if hit is None:
        return False
    rel = hit[2]
    if rel == MANIFEST:
        return True
    return rel.endswith(".xml") and not (set(rel.split("/")[:-1]) & SKIP_DIRS)


def manifest_data(source: bytes):
    """The ``data`` file list of a manifest, or None when the manifest is not a literal dict."""
    try:
        value = ast.literal_eval(source.decode("utf-8", "replace").strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        try:
            tree = ast.parse(source.decode("utf-8", "replace"))
            value = next((ast.literal_eval(n.value) for n in tree.body
                          if isinstance(n, ast.Expr) and isinstance(n.value, ast.Dict)), None)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return None
    if not isinstance(value, dict):
        return None
    files = value.get("data", [])
    return [f for f in files if isinstance(f, str)] if isinstance(files, list) else []


def _qualify(module: str, ident: str) -> str:
    return ident if "." in ident else f"{module}.{ident}"


def _anchors(element) -> set:
    names = set()
    for node in element.iter():
        if node.tag == "attribute":          # <attribute name="invisible"> is an edit, not an anchor
            continue
        for key in ("name", "id"):
            value = node.get(key)
            if value and "\n" not in value:
                names.add(value)
    return names


def _inherit_of(record) -> str:
    for field in record.findall("field"):
        if field.get("name") == "inherit_id":
            if field.get("ref"):
                return field.get("ref")
            hit = REF_CALL.search(field.get("eval") or "")
            return hit.group(1) if hit else ""
    return ""


def parse_views(module: str, xml: bytes) -> list:
    """``[(xmlid, inherit_id or '', anchor set)]`` for the views in one xml file. Raises on malformed XML."""
    parser = ElementTree.XMLParser()
    root = ElementTree.fromstring(xml, parser=parser)
    views = []
    for node in root.iter():
        if node.tag == "record" and node.get("model") == "ir.ui.view" and node.get("id"):
            arch = [f for f in node.findall("field") if f.get("name") == "arch"]
            anchors = set()
            for field in arch:
                for child in list(field):
                    anchors |= _anchors(child)
            inherit = _inherit_of(node)
            views.append((_qualify(module, node.get("id")), _qualify(module, inherit) if inherit else "", anchors))
        elif node.tag == "template" and node.get("id"):
            inherit = node.get("inherit_id") or ""
            anchors = set()
            for child in list(node):
                anchors |= _anchors(child)
            views.append((_qualify(module, node.get("id")), _qualify(module, inherit) if inherit else "", anchors))
    return views


def build_index(source, version: str, repository: str, sha: str, evidence_id: str) -> dict:
    layout = {}
    for path in (p for p in source.paths() if wanted(p)):
        _, module, rel = _module_of(path)
        layout.setdefault(module, {})[rel] = path
    views, problems = {}, []
    for module in sorted(layout):
        files = layout[module]
        if MANIFEST not in files:
            continue
        data = manifest_data(source.read(files[MANIFEST]))
        if data is None:
            problems.append(f"{module}: manifest is not a literal dict; all xml files outside excluded dirs used")
        chosen = sorted(r for r in files if r != MANIFEST) if data is None else [r for r in data if r in files]
        for rel in chosen:
            try:
                for xmlid, inherit, anchors in parse_views(module, source.read(files[rel])):
                    views.setdefault(xmlid, (inherit, set()))[1].update(anchors)
            except ElementTree.ParseError as exc:
                problems.append(f"{files[rel]}: not well-formed ({exc})")
    return _assemble(views, version, repository, sha, evidence_id, problems)


def _root_of(xmlid: str, views: dict) -> str:
    seen = set()
    while True:
        parent = views[xmlid][0]
        if not parent or parent not in views or parent in seen:
            return xmlid
        seen.add(xmlid)
        xmlid = parent


def _assemble(views: dict, version, repository, sha, evidence_id, problems) -> dict:
    roots = {xmlid: _root_of(xmlid, views) for xmlid in views}
    anchors = {}
    for xmlid, (_, names) in views.items():
        anchors.setdefault(roots[xmlid], set()).update(names)
    modules = sorted({xmlid.split(".", 1)[0] for xmlid in views})
    by_module = {m: {} for m in modules}
    for xmlid in sorted(views):
        module, local = xmlid.split(".", 1)
        by_module[module][local] = "" if roots[xmlid] == xmlid else roots[xmlid]
    anchor_lists = {root: sorted(names) for root, names in sorted(anchors.items()) if names}
    payload = json.dumps([by_module, anchor_lists], sort_keys=True, separators=(",", ":"))
    return {
        "format": FORMAT, "version": version, "repository": repository, "revision": sha,
        "evidence": evidence_id, "tool": "tools/extract_view_index.py", "scope": SCOPE,
        "counts": {"modules": len(modules), "views": len(views), "trees": len(anchors),
                   "anchors": sum(len(v) for v in anchor_lists.values())},
        "content_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "problems": sorted(problems), "modules": modules, "views": by_module, "anchors": anchor_lists,
    }


def render(index: dict) -> str:
    """Deterministic layout: one line per top-level key and one line per module / tree."""
    lines = ["{"]
    keys = sorted(index)
    for n, key in enumerate(keys):
        value = index[key]
        tail = "," if n < len(keys) - 1 else ""
        if key in ("views", "anchors") and value:
            inner = sorted(value)
            lines.append(f'"{key}":{{')
            for m, name in enumerate(inner):
                sep = "," if m < len(inner) - 1 else ""
                lines.append(f'{json.dumps(name)}:{json.dumps(value[name], sort_keys=True, separators=(",", ":"), ensure_ascii=False)}{sep}')
            lines.append(f"}}{tail}")
        else:
            lines.append(f'"{key}":{json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)}{tail}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def evidence_record(index: dict, checked_on: str) -> dict:
    version, sha, repository = index["version"], index["revision"], index["repository"]
    counts = index["counts"]
    return {
        "id": index["evidence"],
        "rule_ids": list(RULE_IDS),
        "category": "views",
        "source_applicability": {"from": version, "to": version},
        "target_applicability": {"from": version, "to": version},
        "description": (f"View external ids and named anchors of Odoo {version} core modules at {sha}: "
                        f"{counts['views']} views in {counts['modules']} modules"),
        "url": f"https://github.com/{repository}/tree/{sha}/addons",
        "repository": repository,
        "revision": sha,
        "locations": [{"branch": version, "revision": sha, "path": "addons", "line": None,
                       "match": f"{counts['views']} view ids; content_sha256 {index['content_sha256']}",
                       "kind": "present"}],
        "detection_method": ("tools/extract_view_index.py over addons/*/__manifest__.py data files and "
                             "odoo/addons/*/__manifest__.py data files at the pinned revision"),
        "proposed_transformation": "none",
        "risk": "LOW",
        "required_validation": [],
        "status": "DOCUMENTED_NOT_TESTED",
        "checked_on": checked_on,
        "checked_by": "tools/extract_view_index.py",
    }


def _raw(repository: str, sha: str, path: str):
    """Bytes of ``path`` at ``sha`` from raw.githubusercontent.com, or None on HTTP 404."""
    url = f"https://raw.githubusercontent.com/{repository}/{sha}/{urllib.parse.quote(path)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == 3:
                raise
        except OSError:
            if attempt == 3:
                raise


def core_module_list(core_modules: Path, version: str, sha: str) -> list:
    """Core modules pinned for ``version`` (compatibility/core_modules.json); the pinned SHA must agree."""
    for record in json.loads(Path(core_modules).read_text(encoding="utf-8"))["versions"]:
        if record["id"] == version:
            if record["revision"] != sha:
                raise SystemExit(f"core module list for {version} is pinned at {record['revision']}, not {sha}")
            return sorted(record["modules"])
    raise SystemExit(f"no core module list for {version}")


def fetch(repository: str, sha: str, modules: list, cache: Path, workers: int = 16) -> int:
    """Download each module manifest and the xml files its ``data`` key names into ``cache`` (raw files at the
    pinned SHA; the module list is the pinned core list, so no tree listing is needed). Returns file count."""
    cache = Path(cache)

    def store(path, data):
        target = cache / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def module(name):
        count = 0
        for root in ("addons", "odoo/addons"):
            manifest = f"{root}/{name}/{MANIFEST}"
            data = _raw(repository, sha, manifest)
            if data is None:
                continue
            store(manifest, data)
            count += 1
            for rel in manifest_data(data) or []:
                path = f"{root}/{name}/{rel}"
                if rel.endswith(".xml") and wanted(path) and not (cache / path).exists():
                    xml = _raw(repository, sha, path)
                    if xml is not None:
                        store(path, xml)
                        count += 1
            break
        return count

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sum(pool.map(module, modules))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download the needed files of a pinned SHA into a cache directory")
    f.add_argument("--sha", required=True)
    f.add_argument("--repository", default="odoo/odoo")
    f.add_argument("--version", required=True)
    f.add_argument("--cache", type=Path, required=True)
    f.add_argument("--core-modules", type=Path, default=DEFAULT_CORE_MODULES)
    e = sub.add_parser("extract", help="build the index from a cache directory or a local clone")
    group = e.add_mutually_exclusive_group(required=True)
    group.add_argument("--cache", type=Path, help="directory mirroring the repository layout")
    group.add_argument("--repo", type=Path, help="local clone (git ls-tree / git show at --sha)")
    e.add_argument("--sha", required=True)
    e.add_argument("--version", required=True)
    e.add_argument("--repository", default="odoo/odoo")
    e.add_argument("--evidence-id", required=True, help="EV-5NN identifier")
    e.add_argument("--index-out", type=Path, required=True)
    e.add_argument("--evidence-out", type=Path)
    e.add_argument("--checked-on", help="YYYY-MM-DD; required with --evidence-out")
    args = parser.parse_args(argv)
    if args.command == "fetch":
        count = fetch(args.repository, args.sha, core_module_list(args.core_modules, args.version, args.sha),
                      args.cache)
        print(f"fetched {count} files")
        return 0
    if not VERSION.match(args.version):
        parser.error("--version must look like 16.0")
    if args.evidence_out and not args.checked_on:
        parser.error("--checked-on is required with --evidence-out")
    source = DirSource(args.cache) if args.cache else GitSource(args.repo, args.sha)
    index = build_index(source, args.version, args.repository, args.sha, args.evidence_id)
    args.index_out.parent.mkdir(parents=True, exist_ok=True)
    args.index_out.write_text(render(index), encoding="utf-8")
    if args.evidence_out:
        args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_out.write_text(json.dumps(evidence_record(index, args.checked_on), indent=2, sort_keys=True,
                                                ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{index['version']}: {index['counts']} problems={len(index['problems'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
