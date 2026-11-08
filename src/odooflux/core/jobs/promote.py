"""Verified backup, staging into the workspace, and per-file promotion with restore (FR-004, FR-005, FR-015)."""

import json
import os
import shutil
from pathlib import Path

from odooflux.utils.atomic import atomic_write_bytes
from odooflux.utils.hashing import digest_tree, sha256_bytes, sha256_file


def backup_module(module_path: Path, run):
    """Copy the module into runs/<id>/backup and verify it (FR-003). Returns the manifest or None."""
    name = Path(module_path).name
    dest = run.backup_dir / name
    try:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(module_path, dest, symlinks=True)
        run.log.append("backup_created", module=name, source_path=str(module_path), backup_path=str(dest))
        source_files = digest_tree(Path(module_path))
        verified = source_files == digest_tree(dest)
        manifest = {
            "module": name, "source_path": str(module_path), "backup_path": str(dest),
            "files": [{"rel_path": rel, "sha256": sha}
                      for rel, sha in source_files],
            "verified": verified,
        }
        (run.backup_dir / f"{name}.manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        if not verified:
            raise RuntimeError("backup contents differ from the module")
        run.log.append("backup_verified", module=name, backup_path=str(dest))
        return manifest
    except Exception as exc:
        run.log.append("backup_failed", module=name, backup_path=str(dest), reason=str(exc))
        return None


def audit_staged(run, module_path: Path, edits: list) -> None:
    """Audit each file staged in the workspace: ``file_written``, hash only, never content."""
    audit = getattr(run, "audit", None)
    if audit is None:
        return
    for edit in edits:
        audit.append("file_written", f"{Path(module_path).name}/{edit.dest.relative_to(module_path).as_posix()}",
                     details={"sha256": sha256_bytes(edit.fixed.encode("utf-8")), "workspace": True})


def stage_edits(work_root: Path, module_path: Path, edits: list) -> None:
    """Write validated output into the workspace copy; a rename removes its source there."""
    module_path, work_root = Path(module_path), Path(work_root)
    for edit in edits:
        dest_rel = edit.dest.relative_to(module_path)
        target = work_root / dest_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # The workspace is disposable scratch: a plain write is enough. Durability (atomic replace,
        # fsync) applies to the promotion into the customer module, below.
        target.write_bytes(edit.fixed.encode("utf-8"))
        if edit.dest != edit.path:
            src = work_root / edit.path.relative_to(module_path)
            if src.exists():
                src.unlink()


def _restore(module_path: Path, touched: list, backup_root, run) -> bool:
    """Put touched files back from the verified backup. Returns False when no backup exists or a file could not be
    restored (F-INJ-1: a failing restore must not escape; the run log still lets ``rollback`` finish the job).
    Files that already hold the backup bytes are not rewritten."""
    if backup_root is None:
        return False
    failed = []
    for edit in reversed(touched):
        source_rel = edit.path.relative_to(module_path)
        target = module_path / source_rel
        try:
            original = (backup_root / source_rel).read_bytes()
            if not (target.exists() and target.read_bytes() == original):
                atomic_write_bytes(target, original)
            if edit.dest != edit.path and edit.dest.exists():
                edit.dest.unlink()
        except OSError as exc:
            failed.append(f"{source_rel.as_posix()}: {exc}")
    if failed:
        run.log.append("restore_failed", module=module_path.name, files=failed)
        return False
    run.log.append("file_restored", module=module_path.name, count=len(touched))
    return True


def promote_module(module_path: Path, work_root: Path, edits: list, run, *, backup_root=None):
    """
    Copy every staged file into the module. Each file: atomic replace, then a run-log entry.
    On failure the files already promoted are restored from *backup_root* (when given).
    Returns (ok, reason, written_paths).
    """
    module_path, work_root = Path(module_path), Path(work_root)
    touched, written = [], []
    try:
        for edit in edits:
            touched.append(edit)
            dest_rel = edit.dest.relative_to(module_path)
            staged = (work_root / dest_rel).read_bytes()
            renamed_from = None
            if edit.dest != edit.path:
                renamed_from = edit.path.relative_to(module_path).as_posix()
                before = sha256_file(edit.path)
            else:
                before = sha256_file(edit.dest) if edit.dest.exists() else None
            atomic_write_bytes(edit.dest, staged)
            if renamed_from:
                os.unlink(edit.path)
            written.append(str(edit.dest))
            event = "file_written" if before is not None else "file_created"
            run.log.append(event, module=module_path.name, path=str(edit.dest),
                           renamed_from=renamed_from, sha256_before=before,
                           sha256_after=sha256_bytes(staged),
                           rules=sorted({i.category for i in edit.issues}),
                           edit_ids=[f"{e.start}-{e.end}" for e in edit.edits],
                           module_path=str(module_path),
                           backup_path=str(backup_root) if backup_root else None)
        return True, "", written
    except OSError as exc:
        restored = _restore(module_path, touched, backup_root, run)
        suffix = ("restored from backup" if restored else
                  "NOT restored (no backup or restore failed; run rollback)")
        reason = f"promotion failed: {exc}; {suffix}"
        run.log.append("module_blocked", module=module_path.name, reason=reason)
        return False, reason, written
