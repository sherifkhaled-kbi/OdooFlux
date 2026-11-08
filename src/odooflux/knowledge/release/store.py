"""kb-home store: layout, single-writer lock with PID check, atomic `active.json`, installed releases (REQ-KAP-025,
REQ-KAP-026; contracts/release-lifecycle.md; research.md kb-home layout).

kb-home layout: `active.json`, `releases/<release-id>/` (complete tree, `release.json`, `state.json`), `snapshots/`,
`staging/`, `audit.jsonl` (written by `release/audit.py`), `.lock`. Absent `active.json` means the built-in release.
Only the lock holder writes `active.json`. Readers do not lock: installed releases are immutable.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from odooflux.knowledge.release.manifest import MANIFEST_NAME, STATE_NAME
from odooflux.knowledge.release.model import LOADABLE_STATES, KnowledgeReleaseError, ReleaseState, \
    release_id_from_digest
from odooflux.utils.atomic import atomic_write_text

ACTIVE_FORMAT = "odooflux.active/1"
ACTIVE_NAME = "active.json"
LOCK_NAME = ".lock"
LAYOUT_DIRS = ("releases", "snapshots", "staging")
_RELEASE_ID = re.compile(r"^kr-[0-9a-f]{12}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class KbLockedError(KnowledgeReleaseError):
    """The kb-home lock is held by a live process (or cannot be read, so it is treated as held)."""


@dataclass(frozen=True)
class InstalledRelease:
    release_id: str
    digest: str
    state: ReleaseState
    active: bool


def ensure_layout(home) -> Path:
    """Create the kb-home directories if missing. Never touches `active.json`."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    for name in LAYOUT_DIRS:
        (home / name).mkdir(exist_ok=True)
    return home


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":  # signal 0 is not a liveness probe on Windows; fail closed
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # PermissionError: the process exists
        return True
    return True


def lock_owner(home):
    """PID written in the lock file, or None when there is no lock or it cannot be parsed."""
    try:
        return int((Path(home) / LOCK_NAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


class KbLock:
    """Exclusive kb-home lock: `.lock` created with O_EXCL and holding the owner PID.

    A lock whose PID is no longer alive is stale and is taken over once. A lock with a live or unreadable owner
    raises `KbLockedError`."""

    def __init__(self, home):
        self.home = Path(home)
        self._held = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    def acquire(self) -> None:
        path = self.home / LOCK_NAME
        self.home.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                owner = lock_owner(self.home)
                if owner is None or _pid_alive(owner):
                    raise KbLockedError(f"kb-home {self.home} is locked (owner {owner})") from None
                try:  # stale: owner is gone
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()}\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._held = True
            return
        raise KbLockedError(f"kb-home {self.home} is locked; could not take over the stale lock")

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        if lock_owner(self.home) == os.getpid():
            try:
                os.unlink(self.home / LOCK_NAME)
            except FileNotFoundError:
                pass


def _check_pointer(data, where: str) -> dict:
    if not isinstance(data, dict) or data.get("format") != ACTIVE_FORMAT:
        raise KnowledgeReleaseError(f"{where}: not an {ACTIVE_FORMAT} pointer")
    if not isinstance(data.get("release_id"), str) or not _RELEASE_ID.match(data["release_id"]):
        raise KnowledgeReleaseError(f"{where}: invalid release_id")
    if not isinstance(data.get("digest"), str) or not _DIGEST.match(data["digest"]):
        raise KnowledgeReleaseError(f"{where}: invalid digest")
    if not isinstance(data.get("previous"), list):
        raise KnowledgeReleaseError(f"{where}: previous must be a list")
    return data


def read_active(home):
    """The active pointer dict, or None when `active.json` is absent (built-in release). Writes nothing."""
    path = Path(home) / ACTIVE_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KnowledgeReleaseError(f"{path}: unreadable active pointer ({type(exc).__name__})") from None
    return _check_pointer(data, str(path))


def write_active(home, pointer: dict) -> None:
    """Atomically replace `active.json`. The caller must hold the kb-home lock."""
    home = Path(home)
    if lock_owner(home) != os.getpid():
        raise KbLockedError("write_active requires the kb-home lock to be held by this process")
    _check_pointer(pointer, "pointer to write")
    text = json.dumps(pointer, indent=2, sort_keys=True) + "\n"
    atomic_write_text(home / ACTIVE_NAME, text)


def build_pointer(current, release_id: str, digest: str, now: str) -> dict:
    """New active pointer. The release that was active moves to the front of `previous` with `deactivated_at=now`."""
    previous = []
    if current is not None:
        previous.append({"release_id": current["release_id"], "digest": current["digest"], "deactivated_at": now})
        previous.extend(current["previous"])
    return {"format": ACTIVE_FORMAT, "release_id": release_id, "digest": digest, "activated_at": now,
            "previous": previous}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_release_state(home, release_id: str, state: ReleaseState) -> None:
    """Record the lifecycle state in `releases/<id>/state.json` (outside the release digest)."""
    path = Path(home) / "releases" / release_id / STATE_NAME
    atomic_write_text(path, json.dumps({"state": state.value}, sort_keys=True) + "\n")


def read_release_state(release_dir: Path) -> ReleaseState:
    """Recorded state; a directory without `state.json` is STAGED (not loadable)."""
    path = Path(release_dir) / STATE_NAME
    if not path.exists():
        return ReleaseState.STAGED
    try:
        return ReleaseState(json.loads(path.read_text(encoding="utf-8"))["state"])
    except (OSError, ValueError, KeyError, TypeError):
        raise KnowledgeReleaseError(f"{path}: unreadable release state") from None


def _release_digest(release_dir: Path) -> str:
    path = release_dir / MANIFEST_NAME
    try:
        digest = json.loads(path.read_text(encoding="utf-8"))["release_digest"]
    except (OSError, ValueError, KeyError, TypeError):
        raise KnowledgeReleaseError(f"{path}: unreadable release manifest") from None
    if release_id_from_digest(digest) != release_dir.name:
        raise KnowledgeReleaseError(f"{release_dir}: directory name does not match the release digest")
    return digest


def list_installed(home) -> list:
    """Loadable releases (INSTALLED or ACTIVE) sorted by release id. The active one reports ACTIVE."""
    root = Path(home) / "releases"
    if not root.is_dir():
        return []
    active = read_active(home)
    active_id = active["release_id"] if active else None
    result = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        state = read_release_state(entry)
        digest = _release_digest(entry)
        if entry.name == active_id:
            state = ReleaseState.ACTIVE
        if state not in LOADABLE_STATES:
            continue
        result.append(InstalledRelease(release_id=entry.name, digest=digest, state=state,
                                       active=entry.name == active_id))
    return result
