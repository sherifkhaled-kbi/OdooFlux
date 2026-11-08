"""Supplementary adapters for OCA and OpenUpgrade (REQ-KAP-007, REQ-KAP-008; source-adapter contract rule 5).

These are git-local sources labelled supplementary and non-official. The adapter forces `official=false` on every
spec it receives (`sources.normalize`), whatever the spec file says, and reports the label through `label`. Data
read through these adapters is never treated as official Odoo evidence.
"""

from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.sources import normalize

__all__ = ["SupplementaryAdapter", "SUPPLEMENTARY_KINDS"]

SUPPLEMENTARY_KINDS = ("OCA", "OPENUPGRADE")


class SupplementaryAdapter:
    def __init__(self, kind: str, allow_list=None):
        if kind not in SUPPLEMENTARY_KINDS:
            raise ValueError(f"SupplementaryAdapter does not handle kind {kind!r}")
        self.kind = kind
        self._git = GitLocalAdapter(kind, allow_list=allow_list)

    def probe(self, spec: dict) -> dict:
        return self._git.probe(normalize(spec))

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        return self._git.snapshot(normalize(spec), store, created_at=created_at)

    def label(self, spec: dict) -> dict:
        return {
            "source_id": spec["source_id"],
            "kind": self.kind,
            "official": False,
            "label": "SUPPLEMENTARY_NON_OFFICIAL",
        }
