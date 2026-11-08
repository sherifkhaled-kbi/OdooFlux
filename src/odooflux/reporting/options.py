"""Renderer options and the shared untrusted-text helpers (FR-008). Stdlib only."""

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

COLOR_CHOICES = ("auto", "always", "never")


@dataclass(frozen=True)
class RendererOptions:
    color: str = "auto"                  # auto|always|never ; NO_COLOR is honoured for auto
    width: Optional[int] = None          # None = 80
    max_findings_per_file: int = 20      # lists are capped; totals stay exact
    show_fixed: bool = False
    min_severity: str = "INFO"
    verbose: bool = False

    def __post_init__(self):
        if self.color not in COLOR_CHOICES:
            raise ValueError(f"color must be one of {COLOR_CHOICES}, got {self.color!r}")
        if self.width is not None and self.width < 20:
            raise ValueError("width must be at least 20")
        if self.max_findings_per_file < 1:
            raise ValueError("max_findings_per_file must be at least 1")

    def use_color(self, is_tty: bool = False, environ=None) -> bool:
        env = os.environ if environ is None else environ
        if self.color == "always":
            return True
        if self.color == "never" or env.get("NO_COLOR"):
            return False
        return is_tty

    @property
    def columns(self) -> int:
        return self.width or 80


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")


def sanitize_text(text) -> str:
    """Neutralise untrusted text for a terminal: escape sequences and control characters are shown as visible
    <U+XXXX> markers, never interpreted. Newlines and tabs are flattened to a space (FR-008, REQ-SEC-004)."""
    text = str(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    text = _ANSI.sub(lambda m: _show(m.group(0)), text)
    return _CONTROL.sub(lambda m: f"<U+{ord(m.group(0)):04X}>", text)


def _show(sequence: str) -> str:
    return "".join(f"<U+{ord(c):04X}>" if (ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f) else c for c in sequence)


def display_width(text: str) -> int:
    """Visible column width: ANSI sequences count 0, wide East Asian characters count 2, combining marks 0 (F-REP-2)."""
    text = _ANSI.sub("", text)
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width
