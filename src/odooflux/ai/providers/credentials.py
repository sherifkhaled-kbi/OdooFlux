"""Credential loading (REQ-AI-008, FR-010, D-10): environment or a secrets file outside the scanned paths.

A credential is wrapped in ``Secret``, which renders as ``***`` in every string, repr and format. Only an adapter
building a request header calls ``reveal()``. Nothing here logs.
"""

import os
import re
from pathlib import Path

API_KEY_DEPRECATION = ("WARNING: --api-key is deprecated (D-10): it can leak through shell history. "
                       "Set the provider's key in the environment or use --ai-secrets-file.")


class CredentialError(Exception):
    """``code``: secrets_file_in_scanned_path, secrets_file_permissions, secrets_file_unreadable."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__

    def __format__(self, spec) -> str:
        return "***"

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    __hash__ = None  # type: ignore[assignment]


def _inside(path: Path, roots) -> bool:
    path = path.resolve()
    for root in roots:
        try:
            path.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def read_secrets_file(path, scanned_paths=()) -> dict:
    """KEY=VALUE lines (``#`` comments, optional quotes). The file must not live under a scanned path and, on POSIX,
    must not be readable by group or others. Error messages never contain a value."""
    path = Path(path)
    if _inside(path, scanned_paths):
        raise CredentialError("secrets_file_in_scanned_path", "keep the secrets file outside every module and addons path")
    try:
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise CredentialError("secrets_file_permissions", f"{path.name} must be readable by its owner only (chmod 600)")
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CredentialError("secrets_file_unreadable", type(exc).__name__) from None
    values = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_credential(env_name: str, environ, *, secrets_file=None, scanned_paths=()):
    """Environment first, then the secrets file. Returns a ``Secret`` or None."""
    value = environ.get(env_name) if env_name else None
    if not value and secrets_file:
        value = read_secrets_file(secrets_file, scanned_paths).get(env_name)
    return Secret(value) if value else None


_SHAPES = [
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)?\s*)[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)((?:x-)?api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]{6,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
]


def redact_secrets(text: str, secrets=()) -> str:
    """Remove the known secret values and common key shapes from ``text`` before it is stored or shown."""
    for secret in secrets:
        value = secret.reveal() if isinstance(secret, Secret) else secret
        if value:
            text = text.replace(value, "***")
    for shape in _SHAPES:
        text = shape.sub(lambda m: (m.group(1) if m.groups() else "") + "***", text)
    return text
