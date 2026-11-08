"""Find modules from --module/--modules/--addons-path and walk their files (no symlink escapes)."""

import os
from pathlib import Path

from odooflux.core.contracts.records import ModuleRef
from odooflux.discovery.ignore import IgnoreRules
from odooflux.discovery.manifest import MANIFEST_NAMES, declared_version, read_manifest
from odooflux.utils.paths import is_within

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".mypy_cache", "venv", ".venv"}


def _manifest_of(path: Path):
    for name in MANIFEST_NAMES:
        candidate = path / name
        if candidate.is_file():
            return candidate
    return None


def find_modules(module_paths, addons_paths, findings: list) -> list:
    """Resolved module directories. Addons children without a manifest are skipped with an INFO finding."""
    seen, found = set(), []
    for raw in module_paths:
        p = Path(raw).resolve()
        if p not in seen:
            seen.add(p)
            found.append(p)
    for raw in addons_paths:
        root = Path(raw).resolve()
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name in SKIP_DIRS:
                continue
            child_r = child.resolve()
            if not is_within(child_r, root):
                continue  # symlink pointing outside the addons root
            if _manifest_of(child_r) is None:
                findings.append({"rule_id": "NO_MANIFEST", "path": str(child_r), "line": 0,
                                 "severity": "INFO", "message": "directory has no manifest; skipped"})
                continue
            if child_r not in seen:
                seen.add(child_r)
                found.append(child_r)
    return found


def module_ref(path: Path, order_index: int = -1) -> ModuleRef:
    manifest_file = _manifest_of(path)
    manifest, _error = (read_manifest(manifest_file) if manifest_file else (None, None))
    depends = tuple((manifest or {}).get("depends", []) or [])
    return ModuleRef(
        name=path.name, path=str(path),
        manifest_path=str(manifest_file) if manifest_file else None,
        declared_version=declared_version(manifest),
        depends=tuple(d for d in depends if isinstance(d, str)),
        order_index=order_index)


def iter_module_files(module_root: Path) -> list:
    """Files under *module_root* in sorted order. Symlinks are not followed out of the root."""
    module_root = Path(module_root)
    rules_path = module_root / ".gitignore"
    rules = IgnoreRules(rules_path.read_text(encoding="utf-8", errors="replace").splitlines()
                        if rules_path.is_file() else ())
    root_text = str(module_root)
    out = []
    for root, dirs, files in os.walk(module_root):
        rel_root = "" if root == root_text else root[len(root_text) + 1:]
        prefix = f"{rel_root}/" if rel_root else ""
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not rules.ignored(prefix + d, True))
        for name in sorted(files):
            rel = prefix + name
            if rules.ignored(rel, False):
                continue
            full = Path(root) / name
            if full.is_symlink() and not is_within(full, module_root):
                continue
            out.append(full)
    return out


def manifest_findings(ref: ModuleRef, from_version: int) -> list:
    """Findings from a module's manifest: malformed content, or a version that disagrees with the
    requested source (REQ-VER-006: the explicit flag wins; the mismatch is reported)."""
    findings = []
    if ref.manifest_path is None:
        return findings
    manifest, error = read_manifest(Path(ref.manifest_path))
    if error:
        findings.append({"rule_id": "MANIFEST_MALFORMED", "path": ref.manifest_path, "line": 0,
                         "severity": "WARNING", "message": error})
    declared = declared_version(manifest)
    if declared and declared.split(".")[0].isdigit() and int(declared.split(".")[0]) != from_version:
        findings.append({"rule_id": "VERSION_MISMATCH", "path": ref.manifest_path, "line": 0,
                         "severity": "WARNING",
                         "message": f"manifest declares {declared}; --from-version is {from_version}"})
    return findings
