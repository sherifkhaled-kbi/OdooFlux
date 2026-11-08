"""Runtime log classifier (REQ-VAL-004, REQ-ACL-002, FR-006).

Patterns are data (``knowledge/compatibility/runtime_log_patterns.json``, EV-360..EV-367), loaded through the
knowledge loader. Logs are split into records: a record starts at a timestamped line and owns the continuation
lines after it (tracebacks included). Patterns are tried in file order and the first match wins. A pattern's
optional ``context`` must match the same record. Patterns whose ``version_range`` excludes the target do not
apply. An ERROR or CRITICAL record that no pattern claims is ``unknown``.

``timeout`` and ``oom`` are not log patterns: the caller passes ``killed_reason`` from the container state.
Nothing here executes or imports customer code; the input is text.
"""

import functools
import re
from dataclasses import dataclass
from typing import Optional

from odooflux.knowledge.loader import load_knowledge

RECORD_START = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \d+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) (\S+) (\S+?): ?(.*)$")
REPORTED_LEVELS = ("ERROR", "CRITICAL")
LOADING_RE = re.compile(r"^loading (\S+\.(?:xml|csv))$")
ADDON_FILE_PATTERNS = (
    re.compile(r"while parsing (/\S+?\.(?:xml|csv|py|js|scss))(?::(\d+))?"),
    re.compile(r"'file': '([^']+\.(?:xml|csv|py|js|scss))'(?:.*?'line': (\d+))?", re.S),
    re.compile(r"(/mnt/extra-addons/\S+?\.(?:xml|csv|py|js|scss))(?::(\d+))?"),
)
XML_ID_RE = re.compile(r"(?:External ID not found in the system: |'xmlid': ')([\w.]+)")
ORPHAN_ERROR_RE = re.compile(r"Traceback|Error|Exception")
ADDONS_PREFIXES = ("mnt/extra-addons/", "extra-addons/")


@dataclass(frozen=True)
class LogRecord:
    level: str
    logger: str
    message: str
    text: str
    start: int           # index of the record's first line in the log


@dataclass(frozen=True)
class ClassifiedError:
    error_class: str
    pattern_id: Optional[str]
    level: str
    message: str
    file: Optional[str] = None
    xml_id: Optional[str] = None
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return {"class": self.error_class, "pattern_id": self.pattern_id, "level": self.level,
                "message": self.message, "file": self.file, "xml_id": self.xml_id, "line": self.line}


@functools.lru_cache(maxsize=8)
def _knowledge_patterns(knowledge_root: Optional[str] = None) -> tuple:
    kb = load_knowledge() if knowledge_root is None else load_knowledge(knowledge_root)
    return tuple(kb.runtime_patterns.get("patterns", []))


def load_patterns(*, knowledge_root=None) -> list:
    """Runtime log patterns in file order (the first match wins).

    `knowledge_root` (a release's knowledge tree) selects its `compatibility/runtime_log_patterns.json`; without it the
    built-in tree is used (REQ-KAP-036).
    """
    key = None if knowledge_root is None else str(knowledge_root)
    return [dict(p) for p in _knowledge_patterns(key)]


def _version_key(value) -> Optional[tuple]:
    try:
        major, minor = str(value).split(".")
        return int(major), int(minor)
    except (TypeError, ValueError):
        return None


def applies(pattern: dict, version: str) -> bool:
    window = pattern.get("version_range") or {}
    low, high, target = _version_key(window.get("from")), _version_key(window.get("to")), _version_key(version)
    if low is None or high is None or target is None:
        return False
    return low <= target <= high


def split_records(text: str) -> list:
    records = []
    current = None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = RECORD_START.match(line)
        if match:
            if current is not None:
                records.append(_finish(current))
            current = {"level": match.group(1), "logger": match.group(3), "message": match.group(4),
                       "lines": [line], "start": index}
        elif current is None:
            current = {"level": None, "logger": "", "message": line, "lines": [line], "start": index}
        else:
            current["lines"].append(line)
    if current is not None:
        records.append(_finish(current))
    return records


def _finish(raw: dict) -> LogRecord:
    text = "\n".join(raw["lines"])
    level = raw["level"]
    if level is None:
        # Text without an Odoo timestamp (for example a crash before logging starts) is an error only when it
        # looks like one.
        level = "ERROR" if ORPHAN_ERROR_RE.search(text) else "INFO"
    return LogRecord(level=level, logger=raw["logger"], message=raw["message"], text=text, start=raw["start"])


def _addon_relative(path: str) -> str:
    cleaned = path.lstrip("/")
    for prefix in ADDONS_PREFIXES:
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):]
    return cleaned


def _attribute(record: LogRecord, loading: Optional[str]):
    """(file, xml id, line). The file is the one named by the record, else the data file Odoo was loading."""
    file_path, line_no = None, None
    for pattern in ADDON_FILE_PATTERNS:
        found = pattern.search(record.text)
        if found:
            file_path = _addon_relative(found.group(1))
            line_no = int(found.group(2)) if found.group(2) else None
            break
    if file_path is None and loading:
        file_path = loading
    xml = XML_ID_RE.search(record.text)
    return file_path, (xml.group(1) if xml else None), line_no


def _matching_pattern(record: LogRecord, version: str, patterns: list):
    for pattern in patterns:
        if not applies(pattern, version):
            continue
        if not re.search(pattern["pattern"], record.text):
            continue
        context = pattern.get("context")
        if context and not re.search(context, record.text):
            continue
        return pattern
    return None


def classify_text(text: str, version: str, killed_reason: Optional[str] = None,
                  patterns: Optional[list] = None, *, knowledge_root=None) -> list:
    """ClassifiedError list for one log text. ``killed_reason`` (timeout or oom) is listed first."""
    patterns = load_patterns(knowledge_root=knowledge_root) if patterns is None else patterns
    errors = []
    if killed_reason:
        errors.append(ClassifiedError(error_class=killed_reason, pattern_id=None, level="KILLED",
                                      message=f"container stopped by the runtime adapter: {killed_reason}"))
    loading = None
    for record in split_records(text):
        if record.logger == "odoo.modules.loading":
            announced = LOADING_RE.match(record.message.strip())
            if announced:
                loading = _addon_relative(announced.group(1))
        pattern = _matching_pattern(record, version, patterns)
        if pattern is None and record.level not in REPORTED_LEVELS:
            continue
        file_path, xml_id, line_no = _attribute(record, loading)
        errors.append(ClassifiedError(
            error_class=pattern["class"] if pattern else "unknown",
            pattern_id=pattern["id"] if pattern else None,
            level=record.level,
            message=record.message.strip(),
            file=file_path,
            xml_id=xml_id,
            line=line_no,
        ))
    return errors


def excerpt_for(text: str, max_lines: int) -> str:
    """Up to ``max_lines`` lines from the first ERROR or CRITICAL record, or the last lines when there is none."""
    lines = text.splitlines()
    first_error = next((r for r in split_records(text) if r.level in REPORTED_LEVELS), None)
    if first_error is not None:
        return "\n".join(lines[first_error.start:first_error.start + max_lines])
    return "\n".join(lines[-max_lines:])
