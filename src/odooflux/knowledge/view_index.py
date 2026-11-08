"""Version-pinned index of core view external ids and named anchors (FR-021, ADR-018 D-A7).

The data is built by ``tools/extract_view_index.py`` from official sources at the pinned revisions and shipped as
``compatibility/view_index/<version>.json``. An absent index is never proof of compatibility: ``load_view_index``
returns None and callers must report 'unverifiable'.
"""

import json
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT

VIEW_INDEX_DIR = KNOWLEDGE_ROOT / "compatibility" / "view_index"
_REQUIRED = ("format", "version", "revision", "modules", "views", "anchors")


class ViewIndex:
    """Lookup over one version's index. Build with ``from_dict``."""

    def __init__(self, data: dict):
        self.data = data
        self.version = data["version"]
        self.revision = data["revision"]
        self._modules = frozenset(data["modules"])
        self._views = data["views"]
        self._anchors = data["anchors"]

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("view index must be a mapping")
        missing = [key for key in _REQUIRED if key not in data]
        if missing:
            raise ValueError(f"view index is missing: {', '.join(missing)}")
        if data["format"] != 1:
            raise ValueError(f"unsupported view index format {data['format']!r}")
        if not isinstance(data["views"], dict) or not isinstance(data["anchors"], dict):
            raise ValueError("view index views and anchors must be mappings")
        return cls(data)

    def has_module(self, module: str) -> bool:
        """True when the module is a core module that defines views in this version."""
        return module in self._modules

    def has_view(self, xmlid: str) -> bool:
        module, _, local = xmlid.partition(".")
        return local in self._views.get(module, {})

    def root_of(self, xmlid: str):
        module, _, local = xmlid.partition(".")
        views = self._views.get(module, {})
        return None if local not in views else (views[local] or xmlid)

    def anchors_for(self, xmlid: str):
        """Named anchors (name/id attribute values) of the whole inheritance tree of the view, or None when the
        view is unknown. An empty frozenset means a known view without named anchors."""
        root = self.root_of(xmlid)
        return None if root is None else frozenset(self._anchors.get(root, ()))


def load_view_index(version, root: Path = None):
    """The shipped index for ``version``, or None when none exists (never an error)."""
    if not isinstance(version, str) or not version.replace(".", "").isdigit():
        return None
    path = (Path(root) if root else VIEW_INDEX_DIR) / f"{version}.json"
    if not path.is_file():
        return None
    return ViewIndex.from_dict(json.loads(path.read_text(encoding="utf-8")))
