#!/usr/bin/env python3
"""Maintainer script (not shipped): list the core modules of an official Odoo clone at a pinned SHA.

Reads the git tree only (``git ls-tree``), so no checkout and no network are needed. A module is a
direct child of ``addons/`` or ``odoo/addons/`` that contains ``__manifest__.py``. Writes the sorted
core list (REQ-DEP-001) and the evidence record that pins it to the SHA.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

MANIFEST = "__manifest__.py"
ROOTS = (("addons",), ("odoo", "addons"))
VERSION = re.compile(r"^\d+\.0$")


def core_modules(repo: Path, sha: str) -> list:
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", sha],
                             check=True, capture_output=True, text=True).stdout
    found = set()
    for path in listing.splitlines():
        parts = path.split("/")
        for root in ROOTS:
            depth = len(root)
            if len(parts) == depth + 2 and tuple(parts[:depth]) == root and parts[-1] == MANIFEST:
                found.add(parts[depth])
    return sorted(found)


def core_document(version: str, repository: str, sha: str, evidence_id: str, modules: list) -> dict:
    return {"version": version, "repository": repository, "revision": sha, "evidence": evidence_id,
            "modules": modules}


def evidence_record(version: str, repository: str, sha: str, evidence_id: str, checked_on: str,
                    modules: list) -> dict:
    return {
        "id": evidence_id,
        "rule_ids": [],
        "category": "dependencies",
        "source_applicability": {"from": version, "to": version},
        "target_applicability": {"from": version, "to": version},
        "description": f"Core module directories with {MANIFEST} in Odoo {version} at {sha}",
        "url": f"https://github.com/{repository}/tree/{sha}/addons",
        "repository": repository,
        "revision": sha,
        "locations": [{"branch": version, "revision": sha, "path": "addons", "line": None,
                       "match": f"{len(modules)} module directories", "kind": "present"}],
        "detection_method": f"git ls-tree: addons/*/{MANIFEST} and odoo/addons/*/{MANIFEST}",
        "proposed_transformation": "none",
        "risk": "LOW",
        "required_validation": [],
        "status": "DOCUMENTED_NOT_TESTED",
        "checked_on": checked_on,
        "checked_by": "tools/extract_core_modules.py",
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, required=True, help="local clone of the official repository")
    parser.add_argument("--sha", required=True, help="pinned commit SHA")
    parser.add_argument("--version", required=True, help="target series, e.g. 18.0")
    parser.add_argument("--repository", default="odoo/odoo")
    parser.add_argument("--core-out", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--evidence-id", required=True, help="EV-3NN identifier for the evidence record")
    parser.add_argument("--checked-on", required=True, help="YYYY-MM-DD date of the check")
    args = parser.parse_args(argv)
    if not VERSION.match(args.version):
        parser.error("--version must look like 18.0")
    modules = core_modules(args.repo, args.sha)
    _write_json(args.core_out, core_document(args.version, args.repository, args.sha, args.evidence_id, modules))
    _write_json(args.evidence_out, evidence_record(args.version, args.repository, args.sha, args.evidence_id,
                                                   args.checked_on, modules))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
