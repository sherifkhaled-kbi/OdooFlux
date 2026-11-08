"""Release model: id derivation, KnowledgeHandle, lifecycle state, error class (REQ-KAP-022, REQ-KAP-026).

`builtin_handle()` describes the implicit built-in knowledge tree. It never touches the filesystem.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from odooflux.knowledge.loader import KNOWLEDGE_ROOT

BUILTIN_RELEASE_ID = "builtin"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class KnowledgeReleaseError(Exception):
    """A knowledge release cannot be used (corrupt, incompatible, not loadable). Callers fail closed."""


class ReleaseState(Enum):
    STAGED = "STAGED"
    INSTALLED = "INSTALLED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


LOADABLE_STATES = frozenset({ReleaseState.INSTALLED, ReleaseState.ACTIVE})


def release_id_from_digest(digest: str) -> str:
    """`kr-` plus the first 12 hex characters of the release digest."""
    if not isinstance(digest, str) or not _DIGEST.match(digest):
        raise ValueError(f"release digest must be 64 lowercase hex characters: {digest!r}")
    return "kr-" + digest[:12]


@dataclass(frozen=True)
class KnowledgeHandle:
    root: Path
    release_id: str
    digest: "str | None"
    builtin: bool
    completeness: "str | None"
    steps: dict = field(default_factory=dict)


def builtin_handle(root: Path = KNOWLEDGE_ROOT) -> KnowledgeHandle:
    return KnowledgeHandle(root=Path(root), release_id=BUILTIN_RELEASE_ID, digest=None, builtin=True,
                           completeness=None, steps={})
