"""Exit-code policy (FR-006, REQ-REP-005; F-VER-4, F-REP-3). Pure functions of the report model.

0 OK; 1 threshold exceeded; 2 usage or configuration error; 3 rejected edits in write mode; 4 BLOCKED module or
internal tool error. Precedence 4 > 3 > 1 > 0. The default ``--fail-on critical`` fails on an open CRITICAL finding or
a FAILED module; INFO never fails a build unless ``--fail-on info``. ``--fail-on none`` disables code 1 unless
``--fail-on-status`` is given explicitly."""

from dataclasses import dataclass
from typing import Optional

OK, THRESHOLD, USAGE, REJECTED, BLOCKED = 0, 1, 2, 3, 4
FAIL_ON_CHOICES = ("none", "critical", "warning", "info")
FAIL_ON_STATUSES = ("FAILED", "NEEDS_REVIEW")
_RANK = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
_FLOOR = {"critical": 3, "warning": 2, "info": 1}


class UsageError(ValueError):
    """Invalid --fail-on / --fail-on-status value: the CLI reports it and exits 2 before any processing."""


@dataclass(frozen=True)
class ExitPolicy:
    fail_on: str = "critical"
    fail_on_status: Optional[tuple] = None   # None = default (FAILED unless fail_on is none); () = disabled

    def __post_init__(self):
        if self.fail_on not in FAIL_ON_CHOICES:
            raise UsageError(f"--fail-on must be one of {', '.join(FAIL_ON_CHOICES)}, got {self.fail_on!r}")
        if self.fail_on_status is not None:
            bad = [s for s in self.fail_on_status if s not in FAIL_ON_STATUSES]
            if bad:
                raise UsageError(f"--fail-on-status accepts {', '.join(FAIL_ON_STATUSES)} or none, got {bad[0]!r}")

    @property
    def statuses(self) -> tuple:
        if self.fail_on_status is not None:
            return tuple(self.fail_on_status)
        return () if self.fail_on == "none" else ("FAILED",)


def parse_fail_on_status(text) -> Optional[tuple]:
    """Parse ``FAILED,NEEDS_REVIEW`` (or ``none``). None means not given."""
    if text is None:
        return None
    if text.strip().lower() == "none":
        return ()
    parts = tuple(p.strip().upper() for p in text.split(",") if p.strip())
    bad = [p for p in parts if p not in FAIL_ON_STATUSES]
    if bad or not parts:
        raise UsageError(f"--fail-on-status accepts {', '.join(FAIL_ON_STATUSES)} or none, got {text!r}")
    return parts


def exit_code(report: dict, policy: ExitPolicy = None, *, write_mode: bool = False) -> int:
    policy = policy or ExitPolicy()
    modules = report["modules"]
    if any(m["status"] == "BLOCKED" for m in modules):
        return BLOCKED
    if write_mode and report["summary"]["edits"]["rejected"] > 0:
        return REJECTED
    if policy.fail_on != "none":
        floor = _FLOOR[policy.fail_on]
        if any(f["status"] in ("OPEN", "NEEDS_REVIEW") and _RANK[f["severity"]] >= floor
               for m in modules for f in m["findings"]):
            return THRESHOLD
    if any(m["status"] in policy.statuses for m in modules):
        return THRESHOLD
    return OK


def code_for_exception(exc: BaseException) -> int:
    """An internal tool error is reported with the BLOCKED code (4), never as success."""
    return BLOCKED


def legacy_exit_code(reports: list, write_mode: bool, fail_on: str, rejected: int) -> int:
    """The characterised mapping kept for one minor release (D-10): 4 blocked, 3 rejected edit in write mode, 1 open
    finding at or above --fail-on, else 0. It looks only at the module reports, never at the status model, so a module
    that cannot run L3 (no manifest) is not BLOCKED here. ``--exit-codes v1`` selects :func:`exit_code`."""
    if any(r.blocked for r in reports):
        return BLOCKED
    if write_mode and rejected:
        return REJECTED
    if fail_on != "none" and any(r.open_findings(_NAMES[fail_on]) for r in reports):
        return THRESHOLD
    return OK


_NAMES = {"critical": "CRITICAL", "warning": "WARNING", "info": "INFO"}
