"""Rollback: restore every file a run wrote to its pre-run bytes (REQ-SAF-008, contracts/recovery.md)."""

from pathlib import Path

from odooflux.core.jobs.state_dir import RunDir
from odooflux.core.recovery.runlog import read_runlog
from odooflux.utils.atomic import atomic_write_bytes
from odooflux.utils.hashing import sha256_bytes, sha256_file

WRITE_EVENTS = ("file_written", "file_created")


def _already_restored(path: Path, source: Path, renamed: bool, before) -> bool:
    """True when the file already holds its pre-run state, i.e. an earlier rollback restored it (AR-R3-3)."""
    if before is None:  # created by the run: pre-run state is "absent"
        return not path.exists()
    if renamed:  # pre-run state: source holds the original bytes and the renamed-to path is gone
        return not path.exists() and source.exists() and sha256_file(source) == before
    return path.exists() and sha256_file(path) == before


def _collapse_rewrites(entries: list) -> list:
    """One entry per path written more than once by plain (non-rename) writes: the first ``sha256_before`` (the
    backed-up original) with the last ``sha256_after``. Without this a second write (for example an AI edit after the
    deterministic promote) logs an intermediate hash that matches no backup and rollback would fail."""
    first, last = {}, {}
    for entry in entries:
        key = entry["path"]
        if entry.get("renamed_from") or key in first and first[key].get("renamed_from"):
            continue
        first.setdefault(key, entry)
        last[key] = entry
    merged = []
    for entry in entries:
        key = entry["path"]
        if key in first and not entry.get("renamed_from") and not first[key].get("renamed_from"):
            if entry is not last[key]:
                continue
            entry = dict(entry, sha256_before=first[key].get("sha256_before"))
        merged.append(entry)
    return merged


def rollback(state_dir, run_id: str) -> list:
    """Return one (path, action, detail) tuple per logged write, in reverse order.

    Actions: ``restored``, ``deleted``, ``already`` (already at pre-run state, nothing written) or ``conflict``
    (changed after the run; left as the user left it)."""
    run = RunDir.open(Path(state_dir), run_id)
    entries, _warnings = read_runlog(run.log_dir / "run_log.jsonl")
    results = []
    write_entries = [e for e in entries if e["event"] in WRITE_EVENTS]
    run.audit.append("rollback_started", run_id, details={"files": len(write_entries)})
    for entry in reversed(_collapse_rewrites(write_entries)):
        path = Path(entry["path"])
        module_root = Path(entry["module_path"])
        backup_root = run.backup_dir / module_root.name
        renamed = bool(entry.get("renamed_from"))
        source = module_root / entry["renamed_from"] if renamed else path
        before, after = entry.get("sha256_before"), entry["sha256_after"]
        if _already_restored(path, source, renamed, before):
            results.append((str(source), "already", "already at pre-run bytes"))
            continue
        if not path.exists() or sha256_file(path) != after:
            run.log.append("rollback_conflict", module=module_root.name, path=str(path))
            results.append((str(path), "conflict", "changed after the run; skipped"))
            continue
        if before is None:
            path.unlink()
            results.append((str(path), "deleted", "file created by the run"))
            continue
        original = (backup_root / source.relative_to(module_root)).read_bytes()
        if sha256_bytes(original) != before:
            raise RuntimeError(f"backup of {source} does not match the logged pre-run hash")
        if entry.get("renamed_from") and path != source:
            path.unlink()
        atomic_write_bytes(source, original)
        run.log.append("file_restored", module=module_root.name, path=str(source), sha256_after=before)
        results.append((str(source), "restored", "pre-run bytes"))
    state = run.read_state()
    state["status"] = "ROLLED_BACK"
    run.write_state(state)
    conflicts = sum(1 for r in results if r[1] == "conflict")
    run.audit.append("rollback_completed", run_id, "failed" if conflicts else "ok", {
        "restored": sum(1 for r in results if r[1] == "restored"),
        "deleted": sum(1 for r in results if r[1] == "deleted"), "conflicts": conflicts})
    return results
