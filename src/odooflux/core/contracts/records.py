"""Data contracts (CONTRACTS.md, P2 subset). Frozen where the value is a fact about the input."""

import re
from dataclasses import dataclass, field
from typing import Optional

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.utils.hashing import finding_id

RESEARCH_STATUSES = ("NOT_ASSESSED", "RESEARCH_SEEDED", "RESEARCHED",
                     "RULES_DRAFTED", "RULES_TESTED", "RUNTIME_VALIDATED")
LAYER_OUTCOMES = ("PASS", "FAIL", "UNAVAILABLE", "SKIPPED")
EDIT_STATUSES = ("PENDING", "APPLIED", "REJECTED")
SEVERITIES = ("CRITICAL", "WARNING", "INFO")
_VERSION_ID = re.compile(r"^\d+\.0$")


@dataclass(frozen=True)
class OdooVersion:
    """A registry version. The id is the major release written as ``M.0``."""

    id: str
    python_min: Optional[str] = None
    python_max: Optional[str] = None
    online_releases: tuple = ()
    support_status: str = "UNSUPPORTED"
    contract_version: int = CONTRACT_VERSION

    def __post_init__(self):
        if not _VERSION_ID.match(self.id):
            raise ValueError(f"version id must look like 'M.0', got {self.id!r}")

    @property
    def key(self) -> str:
        return self.id

    @property
    def major(self) -> int:
        return int(self.id.split(".")[0])


@dataclass(frozen=True)
class MigrationStep:
    """One consecutive pair of registry versions (REQ-VER-002)."""

    source: str
    target: str
    research_status: str = "NOT_ASSESSED"

    @property
    def id(self) -> str:
        return f"{self.source}->{self.target}"

    @property
    def unresearched(self) -> bool:
        return self.research_status == "NOT_ASSESSED"


@dataclass(frozen=True)
class ModuleRef:
    name: str
    path: str
    manifest_path: Optional[str]
    declared_version: Optional[str]
    depends: tuple = ()
    order_index: int = -1


@dataclass
class MigrationPlan:
    source: str
    target: str
    steps: list
    modules: list
    status: str  # READY or BLOCKED
    reasons: list = field(default_factory=list)
    blocked_steps: list = field(default_factory=list)
    blocked_modules: list = field(default_factory=list)
    cycles: list = field(default_factory=list)
    allow_unverified: bool = False


@dataclass(frozen=True)
class Document:
    """Text of one file as seen by the engine."""

    path: str
    text: str


@dataclass(frozen=True)
class Finding:
    rule_id: str
    path: str
    line: int
    severity: str
    message: str
    suggestion: str = ""
    matched: str = ""
    status: str = "OPEN"
    evidence: tuple = ()

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")

    @property
    def id(self) -> str:
        return finding_id(self.rule_id, self.path, self.line, self.matched)


@dataclass
class Edit:
    """A span replacement. ``before`` must equal the current slice when applied (REQ-VER-004)."""

    path: str
    start: int
    end: int
    before: str
    after: str
    finding_ids: tuple = ()
    precedence: int = 0
    status: str = "PENDING"
    rejection_reason: str = ""

    def __post_init__(self):
        if self.status not in EDIT_STATUSES:
            raise ValueError(f"unknown edit status {self.status!r}")
        if self.status == "REJECTED" and not self.rejection_reason:
            raise ValueError("a REJECTED edit needs a rejection_reason")


@dataclass(frozen=True)
class ValidationResult:
    layer: int
    outcome: str
    reason: str = ""
    coverage: Optional[str] = None

    def __post_init__(self):
        if self.outcome not in LAYER_OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}")
        if self.outcome != "PASS" and not self.reason:
            raise ValueError("a non-PASS result needs a reason")
        if self.coverage not in (None, "full", "partial"):
            raise ValueError(f"coverage must be full, partial or None, got {self.coverage!r}")
