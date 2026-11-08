"""Secret redaction for log and report text."""

import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,]+"),
]


def redact(text: str) -> str:
    text = _PATTERNS[0].sub("sk-ant-REDACTED", text)
    return _PATTERNS[1].sub(lambda m: m.group(1) + "REDACTED", text)
