# Size-guard limitation (feature 012, Addendum A3): the in-flight guard in `fetch_commit` polls the temporary directory
# every `poll_interval` seconds and kills the git process group once the size is above `max_bytes`. Overshoot is
# therefore bounded by one poll interval plus one pack write. This is NOT a strict byte guarantee. The post-fetch size
# check is a second line of defence, not a substitute.
"""Remote git discovery and acquisition for the knowledge-base update flow (feature 012, T02).

Two operations, both hardened:

- `ls_remote_heads` runs `git ls-remote --heads --refs` (ref advertisement only, no object download) and returns
  `{branch: sha}`.
- `fetch_commit` runs a shallow fetch BY SHA into a managed cache repository, verifies the commit, and records the
  validated https identity as its `origin` remote so that `acquisition/adapters/git_local.py` can check identity.

Hardening for every git call: fixed argv (no shell), an environment built from scratch (no global or system git
config, no credential helpers, no prompts, no SSH command, no proxies except HTTPS_PROXY/https_proxy/NO_PROXY), hooks
disabled, a protocol whitelist, bounded output, and a timeout. Fetched content is never checked out and never executed:
the cache repository is created by this module with an empty template (no hooks) and is never a working tree.

Enterprise credentials (Addendum A2): the `credentials` keyword (a `credentials.Token`) is attached ONLY when the
validated identity is the Enterprise origin. Attached calls get `GIT_ASKPASS` (an OdooFlux stub that holds no secret),
the secret in the child-only variable `ODOOFLUX_GIT_SECRET`, and `GIT_TERMINAL_PROMPT=0`. The token never appears in
argv, a URL, git configuration, a cache file, or an exception message. Enterprise identity without a token raises
`AUTH_REQUIRED` before any process starts. Community identities never receive the token.

Concurrency and cleanup (Addendum A3): a per-identity `flock` on `<cache>/<id16>.lock` serialises writers. A fetch
writes into `<cache>/<id16>/tmp-<random>`, is verified, and is then atomically renamed to `<cache>/<id16>/<sha>`. A
failing fetch removes only its own temporary directory. Stale `tmp-*` directories are removed under the lock.

Network access is gated first by `network_allowed` (ODOOFLUX_OFFLINE and the `offline` argument). The gate runs before
any credential or CA-bundle handling, so offline calls never read the token or the CA setting. Remote identities must
be https URLs under an allow-listed prefix (`sources.load_allow_list`).

`transport_url` is an INTERNAL test seam, never exposed from any CLI. It is used for the connection only (a local bare
repository path); the identity URL is still validated against the allow-list.
"""

import atexit
import errno
import fcntl
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import SOURCE_ERROR_CODES, SourceError
from odooflux.knowledge.acquisition.sources import (
    has_url_credentials, load_allow_list, normalize_origin, origin_allowed,
)
from odooflux.knowledge.update import credentials as _cred
from odooflux.knowledge.update.credentials import CredentialError, Token

__all__ = [
    "NetworkDisabled", "RemoteGitError", "REMOTE_ERROR_CODES", "ENTERPRISE_IDENTITY", "network_allowed",
    "validate_remote", "classify_git_stderr", "ls_remote_heads", "fetch_commit",
    "LS_REMOTE_TIMEOUT", "FETCH_TIMEOUT", "MAX_FETCH_BYTES", "MAX_LS_REMOTE_BYTES", "MAX_LS_REMOTE_LINES",
    "POLL_INTERVAL", "LOCK_WAIT", "STALE_TMP_SECONDS",
]

LS_REMOTE_TIMEOUT = 30  # seconds
FETCH_TIMEOUT_ENV = "ODOOFLUX_FETCH_TIMEOUT"


def _fetch_timeout(default: int = 300, low: int = 60, high: int = 7200) -> int:
    """Wall-clock bound of one source fetch in seconds. `ODOOFLUX_FETCH_TIMEOUT` raises it for slow links (a shallow
    odoo/odoo fetch is a few hundred MB); a stalled transfer still fails early through the low-speed limit. Invalid or
    out-of-range values are ignored, never trusted."""
    raw = os.environ.get(FETCH_TIMEOUT_ENV, "")
    return int(raw) if raw.isdigit() and low <= int(raw) <= high else default


FETCH_TIMEOUT = _fetch_timeout()  # seconds
MAX_FETCH_BYTES = 1 << 30  # size bound on the managed cache repository after a fetch
MAX_LS_REMOTE_BYTES = 1 << 20  # 1 MiB of advertisement
MAX_LS_REMOTE_LINES = 5000
POLL_INTERVAL = 0.5  # seconds between in-flight size checks of a fetch
LOCK_WAIT = 60.0  # seconds to wait for the per-identity cache lock before "cache busy"
LOCK_RETRY = 0.05  # seconds between non-blocking lock attempts
STALE_TMP_SECONDS = 3600  # temporary cache directories older than this (by mtime) are removed under the lock
_OUTPUT_READ_CHUNK = 1 << 16
_STDERR_KEEP = 1 << 16  # stderr is kept only to classify the failure, then discarded

ENTERPRISE_IDENTITY = normalize_origin("https://github.com/odoo/enterprise")
REMOTE_ERROR_CODES = tuple(SOURCE_ERROR_CODES) + ("AUTH_FAILED", "UNAVAILABLE")

_HEX40 = re.compile(r"[0-9a-f]{40}")  # used with fullmatch: `$` would accept a trailing newline
_BRANCH = re.compile(r"[0-9]+\.0")  # informational only; validated, never used as a revision
_LS_LINE = re.compile(rb"([0-9a-f]{40})\trefs/heads/([A-Za-z0-9][A-Za-z0-9._/-]*)")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")  # control characters and whitespace (space included)
_OFFLINE_VALUES = ("1", "true", "yes")
_KEEP_FROM_CALLER = ("HTTPS_PROXY", "https_proxy", "NO_PROXY")

# Stderr classification (applied, then the text is discarded). Patterns are matched case-insensitively.
_AUTH_REQUIRED_RE = re.compile(r"could not read username", re.IGNORECASE)
_PASSWORD_UNREADABLE_RE = re.compile(r"could not read password", re.IGNORECASE)
_AUTH_FAILED_RE = re.compile(
    r"authentication failed|invalid username or password|\bhttp[ /]40[13]\b|returned error: 40[13]\b", re.IGNORECASE)
_NOT_FOUND_RE = re.compile(r"repository not found", re.IGNORECASE)
# The server does not have the requested commit (fetch by SHA). Reported as REVISION_UNAVAILABLE, not IO_ERROR.
_COMMIT_MISSING_RE = re.compile(r"not our ref|unadvertised object|couldn't find remote ref", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(
    r"could not resolve host|failed to connect|connection refused|connection timed out|operation timed out"
    r"|network is unreachable|couldn't connect to server|empty reply from server"
    r"|\bhttp[ /]5\d\d\b|returned error: 5\d\d\b", re.IGNORECASE)
_CLASS_MESSAGES = {
    "AUTH_REQUIRED": "the remote requires credentials that were not supplied",
    "AUTH_FAILED": "the remote rejected the supplied credentials",
    "UNAVAILABLE": "the remote is unreachable or failed on the server side",
    "REVISION_UNAVAILABLE": "the remote does not have the requested commit",
}

# Options placed before the subcommand on every call. Each entry neutralises a setting that could run a program, change
# the transport, or read credentials. Like `_GIT_OPTIONS` in git_local.py; `protocol.version=2` lets the server answer
# a fetch by SHA. `gc.auto` and `maintenance.auto` stop git from detaching background work into the cache.
# `http.sslVerify=true` is stated explicitly: TLS verification is never disabled.
_GIT_OPTIONS = (
    "-c", "core.fsmonitor=false",
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "protocol.version=2",
    "-c", "credential.helper=",
    "-c", "core.askPass=",
    "-c", "core.sshCommand=",
    "-c", "core.pager=",
    "-c", "core.editor=",
    "-c", "core.alternateRefsCommand=",
    "-c", "core.gitProxy=",
    "-c", "gpg.program=",
    "-c", "diff.external=",
    "-c", "uploadpack.packObjectsHook=",
    "-c", "http.sslVerify=true",
    "-c", "gc.auto=0",
    "-c", "maintenance.auto=false",
    "--no-optional-locks",
    "--no-replace-objects",
)
# Added only for calls that carry Enterprise credentials: a redirect must not carry them to another host.
_ATTACHED_OPTIONS = ("-c", "credential.helper=", "-c", "http.followRedirects=false")
# Added to the fetch: a stalled transfer fails instead of hanging until the wall-clock timeout.
_FETCH_OPTIONS = ("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60")

_home_lock = threading.Lock()
_home_dir = None


class NetworkDisabled(Exception):
    """Network access is disabled (offline argument or ODOOFLUX_OFFLINE). No subprocess was started."""


class RemoteGitError(SourceError):
    """`SourceError` with this module's codes: REMOTE_ERROR_CODES adds AUTH_FAILED and UNAVAILABLE to
    SOURCE_ERROR_CODES. Those two are not in `blobstore.SOURCE_ERROR_CODES`, so callers that validate codes against that
    tuple must handle them explicitly."""

    def __init__(self, code: str, source_id, message: str):
        if code not in REMOTE_ERROR_CODES:
            raise ValueError(f"unknown remote git error code {code!r}")
        Exception.__init__(self, f"{code}: {message}")
        self.code = code
        self.source_id = source_id
        self.message = message


def network_allowed(offline: bool) -> bool:
    """False when `offline` is set (any truthy value fails closed) or ODOOFLUX_OFFLINE is 1/true/yes (case-insensitive)."""
    if offline:
        return False
    return os.environ.get("ODOOFLUX_OFFLINE", "").strip().lower() not in _OFFLINE_VALUES


def _refuse(code: str, message: str, token=None) -> RemoteGitError:
    """A RemoteGitError whose message has the token (when one was attached to the call) removed."""
    if token is not None:
        message = token.redact(message)
    return RemoteGitError(code, None, message)


def validate_remote(url, allow_list=None) -> str:
    """Return the canonical identity URL of a remote, or raise SourceError.

    Refused: control characters or whitespace (IO_ERROR), a leading '-' (IO_ERROR), URL credentials (AUTH_REQUIRED,
    the message never repeats the URL), query, fragment, backslash or dot segments (IO_ERROR), non-https schemes
    (NOT_ALLOWLISTED), and any URL outside the allow-list (NOT_ALLOWLISTED). This check is pure: it starts no process.
    """
    if not isinstance(url, str) or not url:
        raise _refuse("IO_ERROR", "remote URL is empty or not text")
    if _CONTROL.search(url):
        raise _refuse("IO_ERROR", "remote URL contains control characters or whitespace")
    if url.startswith("-"):
        raise _refuse("IO_ERROR", "remote URL must not start with '-'")
    if has_url_credentials(url):
        raise _refuse("AUTH_REQUIRED", "remote URL carries credentials; credentials are refused and never stored")
    if any(ch in url for ch in "?#\\"):
        raise _refuse("IO_ERROR", "remote URL must not contain a query, fragment or backslash")
    if any(_is_dot_segment(part) for part in url.split("/")):
        raise _refuse("IO_ERROR", "remote URL must not contain '.' or '..' path segments")
    if not url.lower().startswith("https://"):
        raise _refuse("NOT_ALLOWLISTED", "only https remotes are allowed")
    canonical = normalize_origin(url)
    allowed = load_allow_list() if allow_list is None else list(allow_list)
    if not origin_allowed(canonical, allowed):
        raise _refuse("NOT_ALLOWLISTED", f"{canonical!r} is not under an allow-listed prefix")
    return canonical


def classify_git_stderr(stderr: bytes, attached: bool):
    """The failure code for a git stderr text (AUTH_REQUIRED, AUTH_FAILED, UNAVAILABLE, REVISION_UNAVAILABLE) or None. The text is not kept."""
    text = (stderr or b"").decode("utf-8", "replace")
    if _AUTH_REQUIRED_RE.search(text):
        return "AUTH_REQUIRED"
    if _PASSWORD_UNREADABLE_RE.search(text):
        return "AUTH_FAILED" if attached else "AUTH_REQUIRED"
    if _AUTH_FAILED_RE.search(text):
        return "AUTH_FAILED"
    if attached and _NOT_FOUND_RE.search(text):
        return "AUTH_FAILED"
    if _COMMIT_MISSING_RE.search(text):
        return "REVISION_UNAVAILABLE"
    if _UNAVAILABLE_RE.search(text):
        return "UNAVAILABLE"
    return None


def _authorise(identity: str, credentials):
    """The token to attach to calls for `identity`, or None. Enterprise without a token is refused before any process."""
    if credentials is not None and not isinstance(credentials, Token):
        raise TypeError("credentials must be a credentials.Token or None")
    if identity != ENTERPRISE_IDENTITY:
        return None  # community identities never receive credentials, even when some were passed
    if credentials is None:
        raise _refuse("AUTH_REQUIRED", "the Enterprise repository needs an Enterprise token; none was supplied")
    return credentials


def _ca_env() -> dict:
    """`GIT_SSL_CAINFO` for one call when ODOOFLUX_CA_BUNDLE is set; never a global git setting."""
    try:
        bundle = _cred.resolve_ca_bundle()
    except CredentialError:
        raise _refuse("IO_ERROR", "ODOOFLUX_CA_BUNDLE is not a usable regular file") from None
    return {"GIT_SSL_CAINFO": bundle} if bundle else {}


def _auth_env(token, stub) -> dict:
    """The child-only credential environment. The only place a token value is read for a child process."""
    return {"GIT_ASKPASS": str(stub), _cred.ENV_SECRET: token.reveal(), "GIT_TERMINAL_PROMPT": "0"}


def ls_remote_heads(identity_url, *, offline=False, transport_url=None, timeout=LS_REMOTE_TIMEOUT, runner=None,
                    credentials=None) -> dict:
    """`{branch_name: 40-hex sha}` for the heads a remote advertises. Downloads no objects.

    `credentials` is an optional `credentials.Token`; it is attached only for the Enterprise identity. Enterprise without
    a token raises SourceError("AUTH_REQUIRED") before any process starts.
    `transport_url` is an INTERNAL test seam (a local bare repository path). When None, the validated identity URL is
    used. `runner` is an internal test seam with the signature `runner(argv, *, env, cwd, timeout)` returning an object
    with `returncode`, `stdout` (bytes) and optionally `stderr` (bytes); the default is a bounded subprocess call.
    """
    if not network_allowed(offline):
        raise NetworkDisabled("network access is disabled; no remote was contacted")
    identity = validate_remote(identity_url)
    token = _authorise(identity, credentials)
    transport, protocols = _transport(identity, transport_url)
    extra = _ca_env()
    opts = _ATTACHED_OPTIONS if token is not None else ()
    argv = ["git", *_GIT_OPTIONS, *opts, "ls-remote", "--heads", "--refs", "--", transport]
    if token is None:
        out = _run(argv, protocols=protocols, cwd=_scratch_home(), timeout=timeout, runner=runner, extra_env=extra)
    else:
        with _cred.askpass_session() as stub:
            out = _run(argv, protocols=protocols, cwd=_scratch_home(), timeout=timeout, runner=runner,
                       extra_env={**extra, **_auth_env(token, stub)}, token=token)
    return _parse_heads(out)


def fetch_commit(identity_url, branch, expected_sha, cache_dir, *, offline=False, transport_url=None,
                 timeout=FETCH_TIMEOUT, max_bytes=MAX_FETCH_BYTES, credentials=None, lock_wait=LOCK_WAIT,
                 poll_interval=POLL_INTERVAL, clock=None) -> Path:
    """Fetch one commit BY SHA into the managed cache and return the final repository path `<cache>/<id16>/<sha>`.

    `<id16>` is `sha256(identity)[:16]`. The repository is non-bare, has no checkout and no hooks, so `git rev-parse`
    works and `acquisition/adapters/git_local.py` can verify its origin. Its `origin` remote is the validated identity
    URL (a declared identity, not proof of authenticity).

    Concurrency: the identity's lock file `<cache>/<id16>.lock` is taken with a bounded wait (`lock_wait` seconds, then
    IO_ERROR "cache busy"). Stale `tmp-*` directories older than STALE_TMP_SECONDS by mtime (per `clock()`, default
    time.time) are removed under the lock. A verified final directory is reused. A failing fetch removes only its own
    temporary directory and never the shared final directory.

    Size: `poll_interval` sets how often the temporary directory is measured while git runs. Growth above `max_bytes`
    stops the git process group. Overshoot is bounded (one poll interval plus one pack write), not strictly limited.
    The post-fetch check is a second line.

    `credentials` is an optional `credentials.Token`, attached only for the Enterprise identity (see `ls_remote_heads`).
    `transport_url` is the same internal test seam as in `ls_remote_heads`.
    """
    if not network_allowed(offline):
        raise NetworkDisabled("network access is disabled; no remote was contacted")
    identity = validate_remote(identity_url)
    if not isinstance(branch, str) or _BRANCH.fullmatch(branch) is None:
        raise _refuse("IO_ERROR", "branch must be a numeric release such as NN.0")
    if not isinstance(expected_sha, str) or _HEX40.fullmatch(expected_sha) is None:
        raise _refuse("REVISION_UNAVAILABLE", "fetch needs a full 40-hex commit SHA")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    token = _authorise(identity, credentials)
    transport, protocols = _transport(identity, transport_url)
    extra = _ca_env()

    cache_root = Path(cache_dir)
    if cache_root.is_symlink():
        raise _refuse("IO_ERROR", "cache location is a symbolic link")
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    base = cache_root / key
    try:
        cache_root.mkdir(parents=True, exist_ok=True)
        base.mkdir(exist_ok=True)
    except OSError as exc:
        raise _refuse("IO_ERROR", f"cache directory is not usable: {type(exc).__name__}") from None
    if base.is_symlink():
        raise _refuse("IO_ERROR", "cache location is a symbolic link")

    lock_fd = _open_lock(cache_root / f"{key}.lock")
    try:
        _lock_bounded(lock_fd, lock_wait)
        try:
            return _fetch_locked(identity, expected_sha, transport, protocols, extra, token, base, max_bytes,
                                 timeout, poll_interval, clock or time.time)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _fetch_locked(identity, sha, transport, protocols, extra, token, base: Path, max_bytes, timeout, poll_interval,
                  clock) -> Path:
    """The body of `fetch_commit`, run while the identity lock is held."""
    _sweep_stale(base, clock())
    final = base / sha
    if final.exists() or final.is_symlink():
        if _verifies(final, sha, identity, protocols, timeout):
            return final
        # Not a valid entry: move it aside (still under the lock) and remove it. This is not a fetch failure.
        aside = base / f"tmp-aside-{os.urandom(8).hex()}"
        os.replace(final, aside)
        _remove_entry(aside)

    tmp = Path(tempfile.mkdtemp(prefix="tmp-", dir=str(base)))
    try:
        _run(["git", *_GIT_OPTIONS, "init", "--quiet", "--template=", str(tmp)],
             protocols=protocols, cwd=_scratch_home(), timeout=timeout)
        opts = _ATTACHED_OPTIONS if token is not None else ()
        argv = ["git", *_GIT_OPTIONS, *_FETCH_OPTIONS, *opts, "-C", str(tmp), "fetch", "--quiet", "--no-tags",
                "--no-recurse-submodules", "--depth", "1", "--", transport, sha]
        watch = (tmp, max_bytes, poll_interval)
        if token is None:
            _run(argv, protocols=protocols, cwd=_scratch_home(), timeout=timeout, extra_env=extra, watch=watch)
        else:
            with _cred.askpass_session() as stub:
                _run(argv, protocols=protocols, cwd=_scratch_home(), timeout=timeout,
                     extra_env={**extra, **_auth_env(token, stub)}, token=token, watch=watch)
        resolved = _git_in(tmp, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], protocols,
                           timeout).decode("ascii", "replace").strip()
        if resolved != sha:
            raise _refuse("REVISION_UNAVAILABLE", "fetched object does not match the expected commit", token)
        _set_origin(tmp, identity, protocols, timeout)
        size = _tree_size(tmp)
        if size > max_bytes:
            raise _refuse("IO_ERROR", f"cache repository is {size} bytes, above the {max_bytes} byte bound", token)
        try:
            os.replace(tmp, final)
        except OSError:
            if _verifies(final, sha, identity, protocols, timeout):
                shutil.rmtree(tmp, ignore_errors=True)  # another writer published a valid entry: reuse it
                return final
            raise _refuse("IO_ERROR", "could not publish the cache entry", token) from None
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)  # only this call's own temporary directory
        raise
    return final


# ----- helpers --------------------------------------------------------------------------------------------------------


def _transport(identity: str, transport_url):
    """(transport argument, GIT_ALLOW_PROTOCOL value). The identity itself is used unless the test seam is given."""
    if transport_url is None:
        return identity, "https"
    return _local_transport(transport_url), "https:file"


def _local_transport(path) -> str:
    """The resolved absolute path of an existing local directory, for the test seam only. Anything else is refused."""
    if not isinstance(path, str) or not path or _CONTROL.search(path) or path.startswith("-") or "://" in path:
        raise _refuse("IO_ERROR", "transport must be a local directory path")
    if not os.path.isabs(path):
        raise _refuse("IO_ERROR", "transport path must be absolute")
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        raise _refuse("IO_ERROR", "transport path is not an existing directory")
    return resolved


def _is_dot_segment(part: str) -> bool:
    return urllib.parse.unquote(part) in (".", "..")


def _scratch_home() -> str:
    """An empty per-process directory used as HOME and as the working directory of every git call."""
    global _home_dir
    with _home_lock:
        if _home_dir is None:
            _home_dir = tempfile.mkdtemp(prefix="odooflux-git-home-")
            os.chmod(_home_dir, 0o700)
            atexit.register(shutil.rmtree, _home_dir, True)
        return _home_dir


def _git_env(protocols: str) -> dict:
    """Environment built from scratch. Nothing from the caller's environment is inherited except PATH and the proxy
    variables listed in `_KEEP_FROM_CALLER`."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": _scratch_home(),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": protocols,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LC_ALL": "C",
    }
    for key in _KEEP_FROM_CALLER:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _git_in(repo: Path, args: list, protocols: str, timeout) -> bytes:
    argv = ["git", *_GIT_OPTIONS, "-C", str(repo), *args]
    return _run(argv, protocols=protocols, cwd=_scratch_home(), timeout=timeout)


def _verifies(path: Path, sha: str, identity: str, protocols: str, timeout) -> bool:
    """True when *path* is a real repository (its own `.git`) holding *sha* and the expected origin. Never raises."""
    if path.is_symlink() or not path.is_dir() or not (path / ".git").is_dir():
        return False
    try:
        resolved = _git_in(path, ["rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"], protocols,
                           timeout).decode("ascii", "replace").strip()
        origin = _git_in(path, ["remote", "get-url", "origin"], protocols, timeout).decode("utf-8", "replace").strip()
    except (SourceError, UnicodeDecodeError):
        return False
    return resolved == sha and origin == identity


def _set_origin(repo: Path, identity: str, protocols: str, timeout) -> None:
    remotes = _git_in(repo, ["remote"], protocols, timeout).decode("utf-8", "replace").split()
    if "origin" in remotes:
        _git_in(repo, ["remote", "set-url", "origin", identity], protocols, timeout)
    else:
        _git_in(repo, ["remote", "add", "origin", identity], protocols, timeout)


def _open_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        return os.open(path, flags, 0o600)
    except OSError:
        raise _refuse("IO_ERROR", "cache lock cannot be opened") from None


def _lock_bounded(fd: int, wait) -> None:
    """Take an exclusive flock on *fd*, retrying until *wait* seconds have passed. Then IO_ERROR "cache busy"."""
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise _refuse("IO_ERROR", "cache lock failed") from None
        if time.monotonic() >= deadline:
            raise _refuse("IO_ERROR", "cache busy: another fetch holds the lock")
        time.sleep(LOCK_RETRY)


def _remove_entry(path: Path) -> None:
    """Remove a directory tree or a single non-directory entry; a symbolic link is unlinked, never followed."""
    if path.is_symlink() or not path.is_dir():
        try:
            os.unlink(path)
        except OSError:
            pass
    else:
        shutil.rmtree(path, ignore_errors=True)


def _sweep_stale(base: Path, now_value: float) -> None:
    """Remove `tmp-*` entries under *base* whose mtime is older than STALE_TMP_SECONDS. Caller holds the lock."""
    try:
        entries = list(os.scandir(base))
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith("tmp-"):
            continue
        try:
            age = now_value - entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            continue
        if age > STALE_TMP_SECONDS:
            _remove_entry(base / entry.name)


def _run(argv: list, *, protocols: str, cwd: str, timeout, runner=None, extra_env=None, token=None, watch=None) -> bytes:
    """Run one git call and return its stdout.

    Timeout raises UNAVAILABLE. A non-zero exit is classified from stderr (then discarded) as AUTH_REQUIRED, AUTH_FAILED
    or UNAVAILABLE, and otherwise IO_ERROR. `token` marks an attached call: its value is scrubbed from every message.
    """
    env = _git_env(protocols)
    if extra_env:
        env.update(extra_env)
    try:
        if runner is not None:
            result = runner(argv, env=env, cwd=cwd, timeout=timeout)
        else:
            result = _run_bounded(argv, env=env, cwd=cwd, timeout=timeout, watch=watch)
    except subprocess.TimeoutExpired:
        raise _refuse("UNAVAILABLE", "git call timed out", token) from None
    except OSError as exc:
        raise _refuse("IO_ERROR", f"git call failed: {type(exc).__name__}", token) from None
    if result.returncode != 0:
        code = classify_git_stderr(getattr(result, "stderr", None) or b"", attached=token is not None)
        if code is not None:
            raise _refuse(code, _CLASS_MESSAGES[code], token)
        raise _refuse("IO_ERROR", f"git {_subcommand(argv)} exited with {result.returncode}", token)
    return result.stdout or b""


def _subcommand(argv: list) -> str:
    """The git subcommand name (skipping `-c <cfg>`, `-C <path>` and other options), for messages only."""
    skip = False
    for token in argv[1:]:
        if skip:
            skip = False
        elif token in ("-c", "-C"):
            skip = True
        elif not token.startswith("-"):
            return token
    return "?"


def _run_bounded(argv: list, *, env: dict, cwd: str, timeout, watch=None):
    """subprocess.Popen with stdout and stderr caps, a wall-clock timeout, and an optional in-flight size guard.

    The child runs in its own session so its whole group can be killed. `watch=(directory, max_bytes, poll_interval)`
    starts a watcher that kills the group once `directory` is larger than `max_bytes`. Stdout beyond
    MAX_LS_REMOTE_BYTES is refused. A timeout raises subprocess.TimeoutExpired. Growth raises IO_ERROR.
    """
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, cwd=cwd, shell=False, close_fds=True, start_new_session=True)
    state = {"timed_out": False, "grown": False}

    def _expire():
        state["timed_out"] = True
        _kill_group(proc)

    timer = threading.Timer(timeout, _expire)
    timer.daemon = True
    timer.start()
    errors, stop = [], threading.Event()
    err_reader = threading.Thread(target=_collect, args=(proc.stderr, _STDERR_KEEP, errors), daemon=True)
    err_reader.start()
    guard = None
    if watch is not None:
        guard = threading.Thread(target=_watch_size, args=(proc, watch, stop, state), daemon=True)
        guard.start()
    chunks, total = [], 0
    try:
        while True:
            chunk = proc.stdout.read(_OUTPUT_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_LS_REMOTE_BYTES:
                raise _refuse("IO_ERROR", "git output exceeds the size limit")
            chunks.append(chunk)
        returncode = proc.wait()
    finally:
        timer.cancel()
        stop.set()
        if proc.poll() is None:
            _kill_group(proc)
            proc.wait()
        proc.stdout.close()
        err_reader.join()
        if guard is not None:
            guard.join()
        proc.stderr.close()
    if state["grown"]:
        raise _refuse("IO_ERROR", "transfer exceeded the size bound; the git process was stopped")
    if state["timed_out"]:
        raise subprocess.TimeoutExpired(argv, timeout)
    return subprocess.CompletedProcess(argv, returncode, b"".join(chunks), b"".join(errors))


def _collect(stream, keep: int, sink: list) -> None:
    """Read *stream* to EOF, keeping at most *keep* bytes in *sink* (the rest is drained and dropped)."""
    kept = 0
    while True:
        chunk = stream.read(_OUTPUT_READ_CHUNK)
        if not chunk:
            return
        if kept < keep:
            part = chunk[: keep - kept]
            sink.append(part)
            kept += len(part)


def _watch_size(proc, watch, stop: threading.Event, state: dict) -> None:
    """Poll the watched directory until *stop* is set. Growth above the bound kills the process group."""
    directory, max_bytes, interval = watch
    while True:
        if _tree_size(directory) > max_bytes:
            state["grown"] = True
            _kill_group(proc)
            return
        if stop.wait(interval):
            return


def _kill_group(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _parse_heads(out: bytes) -> dict:
    """Strict parse of `ls-remote --heads --refs` output: `<40-hex>\\trefs/heads/<name>` per line. Anything else raises."""
    if len(out) > MAX_LS_REMOTE_BYTES:
        raise _refuse("IO_ERROR", "ls-remote output exceeds the size limit")
    lines = out.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if len(lines) > MAX_LS_REMOTE_LINES:
        raise _refuse("IO_ERROR", "ls-remote output has too many refs")
    heads = {}
    for raw in lines:
        match = _LS_LINE.fullmatch(raw)
        if match is None:
            raise _refuse("IO_ERROR", "malformed ls-remote line")
        branch = match.group(2).decode("ascii")
        if ".." in branch or "//" in branch or branch.endswith(("/", ".", ".lock")):
            raise _refuse("IO_ERROR", "ls-remote returned an invalid branch name")
        if branch in heads:
            raise _refuse("IO_ERROR", "ls-remote returned a duplicate branch")
        heads[branch] = match.group(1).decode("ascii")
    return heads


def _tree_size(repo: Path) -> int:
    """Total bytes of regular files and links under *repo*, without following links."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(repo, followlinks=False):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total
