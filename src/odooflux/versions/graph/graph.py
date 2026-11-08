"""Version graph: consecutive steps between registry versions (REQ-VER-002/003)."""

import re

from odooflux.core.contracts import UnsupportedVersionError
from odooflux.core.contracts.records import MigrationStep

_FORM = re.compile(r"^(\d+)(\.0)?$")


def normalize(value) -> str:
    """Accept ``M`` or ``M.0`` and return ``M.0``."""
    match = _FORM.match(str(value).strip())
    if not match:
        raise UnsupportedVersionError(f"version must look like M or M.0, got {value!r}")
    return f"{int(match.group(1))}.0"


class VersionGraph:
    def __init__(self, versions, transitions: dict):
        self._order = [v.id for v in sorted(versions, key=lambda v: v.major)]
        self._transitions = dict(transitions)

    @property
    def versions(self) -> list:
        return list(self._order)

    @property
    def minimum(self) -> str:
        return self._order[0]

    def steps(self, source: str, target: str) -> list:
        """Consecutive steps from source to target. Unknown or misordered input raises."""
        for version in (source, target):
            if version not in self._order:
                raise UnsupportedVersionError(
                    f"{version} is not in the registry (supported {self._order[0]}–{self._order[-1]})")
        i, j = self._order.index(source), self._order.index(target)
        if i >= j:
            raise UnsupportedVersionError(f"source {source} must be lower than target {target}")
        return [MigrationStep(a, b, self._transitions.get((a, b), "NOT_ASSESSED"))
                for a, b in zip(self._order[i:j], self._order[i + 1:j + 1])]

    @staticmethod
    def unresearched(steps) -> list:
        return [s for s in steps if s.unresearched]
