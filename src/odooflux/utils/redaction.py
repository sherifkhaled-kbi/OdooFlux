"""Redaction and canary scanning (T019; REQ-AI-008, REQ-SEC-005; contracts/audit-log.md).

``redact_text`` removes known secret values and credential-shaped strings from text; ``scrub`` does the same for
nested JSON-like data and masks any value stored under a secret-looking name. The scanners are the release gate's
evidence: ``scan_for_canaries`` looks for exact planted values in every file under the given roots, and
``scan_for_shapes`` looks for credential shapes that nothing should ever have written.

Standard library only; nothing here imports the AI package."""

import os
import re
from pathlib import Path

MASK = "***"
MIN_SECRET_LENGTH = 6  # shorter values would mangle ordinary text; credentials are longer
SECRET_NAME_PARTS = ("api_key", "apikey", "api-key", "password", "passwd", "secret", "token", "authorization",
                     "credential", "private_key")

_REDACT_SHAPES = [
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)?\s*)[A-Za-z0-9._~+/=\-]{8,}"),
    re.compile(r"(?i)((?:x-)?api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    # URL userinfo: `scheme://user:password@host` and `scheme://token@host` (REQ-KAP-046). Scheme is kept.
    re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://)[^\s/:@'\"]+:[^\s/@'\"]+@"),
    re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://)[A-Za-z0-9_\-]{20,}@"),
]
_SCAN_SHAPES = {
    "provider_api_key": re.compile(rb"\bsk-(?:ant-)?[A-Za-z0-9_\-]{16,}"),
    "bearer_token": re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{20,}"),
    "url_credentials": re.compile(
        rb"(?i)\b[a-z][a-z0-9+.\-]*://(?:[^\s/:@'\"]+:[^\s/@'\"]+|[A-Za-z0-9_\-]{20,})@"),
}


def is_secret_name(name) -> bool:
    lowered = str(name).lower()
    return any(part in lowered for part in SECRET_NAME_PARTS)


def redact_text(text: str, secrets=()) -> str:
    """*text* without the given secret values and without credential-shaped strings."""
    for secret in secrets:
        value = getattr(secret, "reveal", lambda: secret)()
        if value and len(value) >= MIN_SECRET_LENGTH:
            text = text.replace(value, MASK)
    for shape in _REDACT_SHAPES:
        text = shape.sub(lambda m: (m.group(1) if m.groups() else "") + MASK, text)
    return text


def scrub(value, secrets=()):
    """A copy of nested dict/list/str data with secrets removed and secret-named values masked."""
    if isinstance(value, dict):
        return {k: (MASK if is_secret_name(k) and v not in (None, "", False) else scrub(v, secrets))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def _files(roots):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for base, dirs, names in os.walk(root, followlinks=False):
            dirs.sort()
            for name in sorted(names):
                path = Path(base) / name
                if path.is_file() and not path.is_symlink():
                    yield path


def scan_for_canaries(roots, canaries) -> list:
    """``[(path, canary)]`` for every file under *roots* (files or directories) that contains a canary, as UTF-8,
    UTF-16 or raw bytes. An empty list is the passing result."""
    needles = []
    for canary in canaries:
        value = getattr(canary, "reveal", lambda: canary)()
        if value:
            for encoding in ("utf-8", "utf-16-le"):
                needles.append((value, value.encode(encoding)))
    hits = []
    for path in _files(roots):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for canary, needle in needles:
            if needle in data and (str(path), canary) not in hits:
                hits.append((str(path), canary))
    return hits


def scan_for_shapes(roots) -> list:
    """``[(path, shape name)]`` for files that contain a credential-shaped string."""
    hits = []
    for path in _files(roots):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for name, pattern in _SCAN_SHAPES.items():
            if pattern.search(data):
                hits.append((str(path), name))
    return hits
