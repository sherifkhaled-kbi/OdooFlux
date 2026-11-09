"""Enterprise git credentials for the knowledge-base update flow (feature 012, Addendum A2).

Scope and rules (stdlib only, no subprocess):

- Token sources: `ODOOFLUX_ENTERPRISE_TOKEN` (environment), else the regular file named by
  `ODOOFLUX_ENTERPRISE_TOKEN_FILE`. The environment value wins when both are set. The file must not be a symlink, must
  have no group or other permission bits, must be owned by the effective user, must be at most MAX_TOKEN_FILE_BYTES,
  must decode as UTF-8, and its stripped content must be non-empty and free of whitespace and control characters.
- `Token` never reveals its value through repr, str, format, pickling or copying. `reveal()` exists for building a
  child process environment only; `redact()` removes the value from text.
- `write_askpass_stub` writes a fixed, OdooFlux-owned `GIT_ASKPASS` script (mode 0700, inside a 0700 directory). It
  holds no secret: it answers git's Username prompt with a fixed name and its Password prompt from the child
  environment variable `ODOOFLUX_GIT_SECRET`.
- `resolve_ca_bundle` validates `ODOOFLUX_CA_BUNDLE` (an absolute path to an existing regular file). The caller maps it
  to `GIT_SSL_CAINFO` for one call. Nothing here writes git configuration, and TLS verification is never disabled.

Nothing in this module reads the environment as a side effect of import. Callers decide when a token is resolved.
"""

import contextlib
import os
import shutil
import stat
import tempfile
import unicodedata
from pathlib import Path

from odooflux.utils.redaction import scrub

__all__ = [
    "ENV_TOKEN", "ENV_TOKEN_FILE", "ENV_SECRET", "ENV_CA_BUNDLE", "ASKPASS_USERNAME", "MAX_TOKEN_FILE_BYTES",
    "CREDENTIAL_ERROR_CODES", "CredentialError", "Token", "resolve_enterprise_token", "resolve_ca_bundle",
    "write_askpass_stub", "remove_askpass_stub", "askpass_session",
]

ENV_TOKEN = "ODOOFLUX_ENTERPRISE_TOKEN"
ENV_TOKEN_FILE = "ODOOFLUX_ENTERPRISE_TOKEN_FILE"
ENV_SECRET = "ODOOFLUX_GIT_SECRET"  # the child-environment variable the askpass stub reads; never set in the parent
ENV_CA_BUNDLE = "ODOOFLUX_CA_BUNDLE"
ASKPASS_USERNAME = "x-access-token"
MAX_TOKEN_FILE_BYTES = 4096
MAX_TOKEN_CHARS = 4096

CREDENTIAL_ERROR_CODES = (
    "TOKEN_INVALID",
    "TOKEN_FILE_MISSING",
    "TOKEN_FILE_UNREADABLE",
    "TOKEN_FILE_SYMLINK",
    "TOKEN_FILE_NOT_REGULAR",
    "TOKEN_FILE_CHANGED",
    "TOKEN_FILE_PERMISSIONS",
    "TOKEN_FILE_TOO_LARGE",
    "TOKEN_FILE_NOT_UTF8",
    "TOKEN_FILE_EMPTY",
    "TOKEN_FILE_INVALID",
    "CA_BUNDLE_INVALID",
    "CA_BUNDLE_MISSING",
    "ASKPASS_FAILED",
)

# The stub is fixed text. It contains no secret: the password is read from the child environment at prompt time.
_ASKPASS_SCRIPT = """#!/bin/sh
# OdooFlux GIT_ASKPASS stub (feature 012). Holds no secret; answers only git's Username and Password prompts.
case "$1" in
  *Username*) printf '%s\\n' 'x-access-token' ;;
  *Password*)
    if [ -z "$ODOOFLUX_GIT_SECRET" ]; then exit 1; fi
    printf '%s\\n' "$ODOOFLUX_GIT_SECRET" ;;
  *) exit 1 ;;
esac
"""


class CredentialError(Exception):
    """Credential or CA-bundle configuration failure with a closed code. Messages never echo file or token contents."""

    def __init__(self, code: str, message: str):
        if code not in CREDENTIAL_ERROR_CODES:
            raise ValueError(f"unknown CredentialError code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _is_invisible(ch: str) -> bool:
    return ch.isspace() or unicodedata.category(ch).startswith("C")


def _checked_value(text: str, code: str) -> str:
    """The stripped token text, or CredentialError(code) when empty, too long, or containing whitespace/controls."""
    value = text.strip()
    if not value:
        raise CredentialError(code, "token is empty")
    if len(value) > MAX_TOKEN_CHARS or any(_is_invisible(ch) for ch in value):
        raise CredentialError(code, "token contains whitespace, control characters, or is too long")
    return value


class Token:
    """An Enterprise token. The value leaves the object only through `reveal()` (child environment construction) and
    `redact()` (removing it from text). Pickling and copying are refused."""

    __slots__ = ("__value",)

    def __init__(self, value: str):
        if not isinstance(value, str):
            raise CredentialError("TOKEN_INVALID", "token must be text")
        self.__value = _checked_value(value, "TOKEN_INVALID")

    def reveal(self) -> str:
        """The raw value. Call only where a child process environment is built."""
        return self.__value

    def redact(self, text: str) -> str:
        """`text` with the token value (and credential-shaped strings) removed."""
        return scrub(text, secrets=(self.__value,))

    def __repr__(self) -> str:
        return "<token>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("Token objects are not serialisable")


def _token_from_file(path: str) -> Token:
    if "\x00" in path:
        raise CredentialError("TOKEN_FILE_INVALID", "token file path is malformed")
    try:
        before = os.lstat(path)
    except FileNotFoundError as exc:
        raise CredentialError("TOKEN_FILE_MISSING", "token file does not exist") from exc
    except OSError as exc:
        raise CredentialError("TOKEN_FILE_UNREADABLE", "token file cannot be inspected") from exc
    if stat.S_ISLNK(before.st_mode):
        raise CredentialError("TOKEN_FILE_SYMLINK", "token file must not be a symbolic link")
    if not stat.S_ISREG(before.st_mode):
        raise CredentialError("TOKEN_FILE_NOT_REGULAR", "token file must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise CredentialError("TOKEN_FILE_UNREADABLE", "token file cannot be opened") from exc
    with os.fdopen(fd, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise CredentialError("TOKEN_FILE_CHANGED", "token file changed while it was being opened")
        if opened.st_mode & 0o077:
            raise CredentialError("TOKEN_FILE_PERMISSIONS", "token file must be accessible to its owner only")
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None and opened.st_uid != geteuid():
            raise CredentialError("TOKEN_FILE_PERMISSIONS", "token file must be owned by the current user")
        if opened.st_size > MAX_TOKEN_FILE_BYTES:
            raise CredentialError("TOKEN_FILE_TOO_LARGE", "token file exceeds the size bound")
        data = handle.read(MAX_TOKEN_FILE_BYTES + 1)
    if len(data) > MAX_TOKEN_FILE_BYTES:
        raise CredentialError("TOKEN_FILE_TOO_LARGE", "token file exceeds the size bound")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CredentialError("TOKEN_FILE_NOT_UTF8", "token file is not UTF-8") from exc
    text = text.strip()
    if not text:
        raise CredentialError("TOKEN_FILE_EMPTY", "token file is empty")
    try:
        return Token(_checked_value(text, "TOKEN_FILE_INVALID"))
    except CredentialError as exc:
        raise CredentialError("TOKEN_FILE_INVALID", "token file contains whitespace or control characters") from exc


def resolve_enterprise_token(env=None):
    """The Enterprise `Token`, or None when neither source is configured.

    The environment variable wins when set (non-empty). Otherwise the token file named by ODOOFLUX_ENTERPRISE_TOKEN_FILE
    is read and fully validated. Errors carry a code and never echo the file or token contents.
    """
    source = os.environ if env is None else env
    raw = source.get(ENV_TOKEN)
    if raw is not None and raw.strip():
        try:
            return Token(raw.strip())
        except CredentialError as exc:
            raise CredentialError("TOKEN_INVALID", "environment token contains whitespace or control characters") from exc
    path = source.get(ENV_TOKEN_FILE)
    if path is None or not path.strip():
        return None
    return _token_from_file(path)


def resolve_ca_bundle(env=None):
    """The validated corporate CA bundle path, or None when ODOOFLUX_CA_BUNDLE is unset or empty.

    Must be an absolute path to an existing, readable regular file (symbolic links to one are followed). Anything else
    raises CredentialError. The caller maps the result to GIT_SSL_CAINFO for a single call.
    """
    source = os.environ if env is None else env
    value = source.get(ENV_CA_BUNDLE)
    if value is None or value == "":
        return None
    if value != value.strip() or any(unicodedata.category(ch).startswith("C") for ch in value):
        raise CredentialError("CA_BUNDLE_INVALID", "CA bundle path has surrounding whitespace or control characters")
    if not os.path.isabs(value):
        raise CredentialError("CA_BUNDLE_INVALID", "CA bundle path must be absolute")
    try:
        status = os.stat(value)
    except OSError as exc:
        raise CredentialError("CA_BUNDLE_MISSING", "CA bundle file does not exist") from exc
    if not stat.S_ISREG(status.st_mode):
        raise CredentialError("CA_BUNDLE_INVALID", "CA bundle must be a regular file")
    if not os.access(value, os.R_OK):
        raise CredentialError("CA_BUNDLE_INVALID", "CA bundle file is not readable")
    return value


def write_askpass_stub(directory) -> Path:
    """Write the fixed askpass script into *directory* (a real directory the caller created) and return its path.

    The directory is set to mode 0700 and the script is created exclusively with mode 0700. The script holds no secret.
    """
    directory = Path(directory)
    try:
        dir_status = os.lstat(directory)
        if not stat.S_ISDIR(dir_status.st_mode):
            raise CredentialError("ASKPASS_FAILED", "askpass directory is not a directory")
        os.chmod(directory, 0o700)
        path = directory / "askpass.sh"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(path, flags, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_ASKPASS_SCRIPT)
        os.chmod(path, 0o700)
    except OSError as exc:
        raise CredentialError("ASKPASS_FAILED", "askpass stub could not be written") from exc
    return path


def remove_askpass_stub(path) -> None:
    """Remove a stub written by `write_askpass_stub`, then its directory if (and only if) it is now empty."""
    path = Path(path)
    with contextlib.suppress(OSError):
        os.unlink(path)
    with contextlib.suppress(OSError):
        os.rmdir(path.parent)


@contextlib.contextmanager
def askpass_session():
    """Yield the path of a fresh askpass stub inside a private 0700 temp directory, removed on exit."""
    directory = tempfile.mkdtemp(prefix="odooflux-askpass-")
    try:
        os.chmod(directory, 0o700)
        yield write_askpass_stub(directory)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
