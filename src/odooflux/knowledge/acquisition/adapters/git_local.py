"""Git-local adapter (REQ-KAP-007, REQ-KAP-009, REQ-KAP-001; source-adapter contract rules 1, 2, 6, 7, 8, 9).

Reads a local clone given as a `local:<path>` URL. Probe and snapshot use `git` plumbing with argument lists only
(no shell), a timeout per call, and a cleared environment. A pinned revision must be a full 40-hex commit present
in the clone; otherwise the adapter refuses (`REVISION_UNAVAILABLE`). An official local clone (`official=true`) must
also prove its identity: its `origin` remote must equal `expected_origin` (normalised) and be allow-listed, else the
probe fails with `OFFICIAL_IDENTITY_UNVERIFIED`, including when the pinned commit is absent. The verified origin is
recorded as `origin_url`. This is a declared identity, not cryptographic proof (see `sources.official_origin`). GIT_ENTERPRISE
clones follow exactly the same rules, under the enterprise prefix. It never resolves branches, tags or short
SHAs, and never substitutes another revision. Remote URLs never reach git: they are checked against the allow-list
and then refused with `NETWORK_DISABLED` (network access lives only in `acquisition/fetch.py`).
"""

import fnmatch
import os
import re
import subprocess
from datetime import datetime, timezone

from odooflux.knowledge.acquisition.blobstore import SourceError
from odooflux.knowledge.acquisition.snapshot import _excluded_by_scope, _kind, _rel_text
from odooflux.knowledge.acquisition.sources import (
    FORCED_UNOFFICIAL, GIT_KINDS, load_allow_list, require_allowed, verify_declared_origin,
)
from odooflux.knowledge.release.canonical import digest_obj

__all__ = ["GitLocalAdapter", "GIT_TIMEOUT"]

GIT_TIMEOUT = 120  # seconds per git call
_HEX40 = re.compile(r"[0-9a-f]{40}")  # used with fullmatch: `$` would accept a trailing newline
_LOCAL = "local:"
# Options placed before `-C` on every call. The clone is untrusted, so each entry neutralises a repository-controlled
# setting that could run a program or change what is read. Plumbing runs no hooks, filters, pagers or transports, so
# none of these fired in the hostile-clone tests; they are defence in depth. `--no-replace-objects` is load-bearing:
# without it a `refs/replace/<commit>` entry in the clone substitutes another tree for the pinned commit.
_GIT_OPTIONS = (
    "-c", "core.fsmonitor=false",
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "protocol.allow=never",
    "-c", "core.sshCommand=",
    "-c", "core.askPass=",
    "-c", "core.pager=",
    "-c", "core.editor=",
    "-c", "credential.helper=",
    "-c", "gpg.program=",
    "-c", "diff.external=",
    "-c", "uploadpack.packObjectsHook=",
    "-c", "core.alternateRefsCommand=",
    "-c", "core.gitProxy=",
    "--no-optional-locks",
    "--no-replace-objects",
)


class GitLocalAdapter:
    """Adapter for the git kinds that read a local clone (`GIT_KINDS`)."""

    def __init__(self, kind: str = "GIT_COMMUNITY", allow_list=None):
        if kind not in GIT_KINDS:
            raise ValueError(f"GitLocalAdapter does not handle kind {kind!r}")
        self.kind = kind
        self._allow = load_allow_list() if allow_list is None else list(allow_list)

    # ----- subprocess helpers -------------------------------------------------------------------------------

    def _git(self, repo: str, args: list, source_id, input_bytes: bytes = None) -> bytes:
        """Run one plumbing call. `repo` is a resolved directory (see `_repo_path`) and goes only after `-C`; `args`
        are fixed subcommand tokens plus revisions or object ids that were already validated as 40-hex."""
        argv = ["git", *_GIT_OPTIONS, "-C", repo, *args]
        env = {  # built from scratch: nothing from the caller's environment is inherited except PATH
            "PATH": os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": os.path.dirname(repo),
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
        try:
            proc = subprocess.run(argv, input=input_bytes, capture_output=True, env=env, shell=False,
                                  timeout=GIT_TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceError("IO_ERROR", source_id, f"git call failed: {exc}") from exc
        if proc.returncode != 0:
            raise SourceError("IO_ERROR", source_id, f"git {args[0]} exited with {proc.returncode}")
        return proc.stdout

    # ----- probe --------------------------------------------------------------------------------------------

    def probe(self, spec: dict) -> dict:
        """Read-only check. Returns `{available, reason_code, detail}`; never writes and never raises for a
        source problem."""
        return self._check(spec)[0]

    def _check(self, spec: dict):
        """(probe result, verified origin or None). The origin is set only for an official local clone whose identity
        verified; every other outcome is unavailable and returns None."""
        source_id, url, revision = spec["source_id"], spec["url"], spec["revision"]
        if not url.startswith(_LOCAL):
            try:
                require_allowed(url, self._allow, source_id)
            except SourceError as exc:
                return _probe(False, exc.code, exc.message), None
            return _probe(False, "NETWORK_DISABLED", "remote git sources are fetched only by acquisition/fetch.py"), None
        if not _is_sha(revision):
            return _probe(False, "REVISION_UNAVAILABLE", "git sources need a full 40-hex commit SHA"), None
        repo = _repo_path(url)
        if repo is None:
            return _probe(False, "IO_ERROR", "local clone path is not an existing directory"), None
        official = spec.get("official") is True and spec.get("kind") not in FORCED_UNOFFICIAL
        origin = None
        if official:
            origin = self._verified_origin(repo, spec)
            if origin is None:
                return _probe(False, "OFFICIAL_IDENTITY_UNVERIFIED",
                              "origin remote does not verify against expected_origin on the allow-list"), None
        try:
            self._git(repo, ["cat-file", "-e", f"{revision}^{{commit}}"], source_id)
        except SourceError:
            if official:
                return _probe(False, "OFFICIAL_IDENTITY_UNVERIFIED",
                              f"pinned commit {revision} is not present in the verified clone"), None
            return _probe(False, "REVISION_UNAVAILABLE", f"commit {revision} is not present in the clone"), None
        return _probe(True, "OK", f"commit {revision} present"), origin

    def _verified_origin(self, repo: str, spec: dict):
        """The normalised origin of the clone when its `origin` remote matches `expected_origin`; else None. Missing
        remote, a clone that is not the repository root, and any mismatch all give None."""
        source_id = spec["source_id"]
        try:
            top = self._git(repo, ["rev-parse", "--show-toplevel"], source_id).decode("utf-8").strip()
            remote = self._git(repo, ["remote", "get-url", "origin"], source_id).decode("utf-8").strip()
        except (SourceError, UnicodeDecodeError):
            return None
        if os.path.realpath(top) != os.path.realpath(repo):
            return None
        return verify_declared_origin(remote, spec.get("expected_origin"), spec.get("kind"), self._allow)

    # ----- snapshot -----------------------------------------------------------------------------------------

    def snapshot(self, spec: dict, store, *, created_at=None) -> dict:
        """Store every in-scope blob of the pinned commit and return a SourceSnapshot dict. Raises SourceError
        when the pin is unavailable; nothing is stored in that case."""
        source_id, revision = spec["source_id"], spec["revision"]
        probe, origin = self._check(spec)
        if not probe["available"]:
            raise SourceError(probe["reason_code"], source_id, probe["detail"])
        repo = _repo_path(spec["url"])
        if repo is None or not _is_sha(revision):  # unreachable after _check; re-checked before any argv is built
            raise SourceError("IO_ERROR", source_id, "local clone or revision failed validation")
        listing = self._git(repo, ["ls-tree", "-r", "-z", "--full-tree", revision], source_id)
        rules = list((spec.get("scope") or {}).get("exclude") or [])
        includes = list((spec.get("scope") or {}).get("include") or [])

        candidates, excluded = [], []
        for raw in listing.split(b"\0"):
            if not raw:
                continue
            meta, _, raw_path = raw.partition(b"\t")
            mode, obj_type, oid = meta.decode("ascii").split()
            if not _is_sha(oid):  # object ids are fed to `cat-file --batch`, so they must be plain 40-hex
                raise SourceError("IO_ERROR", source_id, "ls-tree returned a non-40-hex object id")
            try:
                rel = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                excluded.append({"path": _rel_text(raw_path.decode("utf-8", "backslashreplace")),
                                 "reason": "NON_UTF8_NAME"})
                continue
            if any(part in ("", ".", "..") for part in rel.split("/")):
                excluded.append({"path": rel, "reason": "PATH_ESCAPE"})
                continue
            if mode == "120000":
                excluded.append({"path": rel, "reason": "SYMLINK"})
                continue
            if obj_type != "blob":
                excluded.append({"path": rel, "reason": "SUBMODULE"})
                continue
            reason = _excluded_by_scope(rel, rules)
            if reason is None and includes and not any(_match(rel, p) for p in includes):
                reason = "NOT_IN_SCOPE"
            if reason is not None:
                excluded.append({"path": rel, "reason": reason})
                continue
            candidates.append((rel, oid))

        entries = []
        if candidates:
            request = "".join(oid + "\n" for _, oid in candidates).encode("ascii")
            blobs = _read_batch(self._git(repo, ["cat-file", "--batch"], source_id, input_bytes=request),
                                len(candidates), source_id)
            for (rel, _), data in zip(candidates, blobs):
                entries.append({"path": rel, "sha256": store.put(data), "size": len(data), "kind": _kind(rel)})

        entries.sort(key=lambda e: e["path"])
        excluded.sort(key=lambda e: e["path"])
        digest = digest_obj({"source_id": source_id, "revision": revision, "entries": entries})
        if created_at is None:
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = {
            "snapshot_id": "ss-" + digest[:12],
            "source_id": source_id,
            "revision": revision,
            "entries": entries,
            "snapshot_digest": digest,
            "created_at": created_at,
            "limits": {"excluded": excluded},
        }
        if origin is not None:
            result["origin_url"] = origin
        return result


def _probe(available: bool, reason_code: str, detail: str) -> dict:
    return {"available": available, "reason_code": reason_code, "detail": detail}


def _is_sha(value) -> bool:
    return isinstance(value, str) and _HEX40.fullmatch(value) is not None


def _repo_path(url: str):
    """The resolved absolute path of a `local:` clone, or None. A path that starts with `-` or contains a line break
    or NUL is refused outright; the resolved path is always absolute, so it can never read as an option."""
    raw = url[len(_LOCAL):]
    if not raw or raw.startswith("-") or any(ch in raw for ch in "\n\r\0"):
        return None
    resolved = os.path.realpath(raw)
    return resolved if os.path.isdir(resolved) else None


def _match(rel: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(rel, pattern)


def _read_batch(out: bytes, count: int, source_id) -> list:
    """Parse `git cat-file --batch` output: `<oid> <type> <size>\\n<bytes>\\n` per object, in request order."""
    blobs, pos = [], 0
    for _ in range(count):
        newline = out.find(b"\n", pos)
        if newline < 0:
            raise SourceError("IO_ERROR", source_id, "truncated cat-file output")
        header = out[pos:newline].split(b" ")
        if len(header) != 3 or header[1] != b"blob":
            raise SourceError("IO_ERROR", source_id, f"unexpected cat-file header {header!r}")
        size = int(header[2])
        start = newline + 1
        blobs.append(out[start:start + size])
        pos = start + size + 1  # trailing newline after content
    return blobs
