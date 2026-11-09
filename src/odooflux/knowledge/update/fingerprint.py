"""Deterministic update fingerprints (feature 012, plan section 3).

A fingerprint is the sha256 of the canonical JSON (key-sorted, compact, see `release/canonical.py`) of every input that
can change the knowledge built from upstream: source commit SHAs, per-source snapshot digests, the catalog digest, the
extractor and rule-schema versions, the build configuration and the parent release. Same inputs give the same
fingerprint whatever the insertion order of the dicts; any change to any input gives a different one.

The reports use `explain_change` to name the inputs that moved, so an operator can see why an update was or was not
needed.

Two lifecycles share this input shape and must never be conflated:
- A planning fingerprint (`planner.UpdatePlan.planning_fingerprint`) has an EMPTY `snapshot_digests`. Its source SHAs come
  from remote metadata. It never proves that a snapshot was acquired or verified.
- A build fingerprint (`planner.build_fingerprint`) carries the VERIFIED snapshot digest of every acquired or carried
  source. It can only be computed after acquisition and verification.
The planning form is therefore never a valid build record: `planner.needs_build` treats it as "no previous build inputs".
"""

import copy
import re
from dataclasses import dataclass
from typing import Literal, Optional

from odooflux.knowledge.release.canonical import CanonicalError, canonical_bytes, digest_obj

FINGERPRINT_FORMAT = "odooflux.update-fingerprint/1"

# The shipped JSON schemas each carry their own `odooflux.<name>/1` const (see knowledge/schemas/*.json); none is a
# single knowledge-wide version, so the rule-schema version is an explicit constant. Bump it when rule_metadata or
# rule_history change shape so that every fingerprint built on the old shape is different.
RULE_SCHEMA_VERSION = "1"
# Bump when the extraction (pipeline steps 1-15) changes what it emits for the same snapshot.
EXTRACTOR_VERSION = "1"

NO_PREVIOUS = "NO_PREVIOUS"
UNCHANGED = "UNCHANGED"
CHANGED = "CHANGED"
Comparison = Literal["NO_PREVIOUS", "UNCHANGED", "CHANGED"]

INPUT_NAMES = ("source_shas", "snapshot_digests", "catalog_digest", "extractor_version", "rule_schema_version",
               "build_config", "parent_release_id")

_SHA = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class FingerprintError(ValueError):
    """An input cannot be fingerprinted (bad SHA, empty digest, non-JSON value, malformed fingerprint)."""


def _non_empty_str(value, what: str) -> None:
    if not isinstance(value, str) or not value:
        raise FingerprintError(f"{what} must be a non-empty string")


def _str_map(value, what: str, check) -> None:
    if not isinstance(value, dict):
        raise FingerprintError(f"{what} must be a dict")
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise FingerprintError(f"{what} keys must be non-empty strings")
        check(item, f"{what}[{key!r}]")


def _check_sha(value, what: str) -> None:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise FingerprintError(f"{what} must be a 40-character lowercase hex commit SHA")


@dataclass(frozen=True)
class FingerprintInputs:
    """The inputs of one fingerprint. Validated on construction; `to_dict` gives the storable form."""

    source_shas: dict
    snapshot_digests: dict
    catalog_digest: str
    extractor_version: str
    rule_schema_version: str
    build_config: dict
    parent_release_id: Optional[str]

    def __post_init__(self):
        _str_map(self.source_shas, "source_shas", _check_sha)
        _str_map(self.snapshot_digests, "snapshot_digests", _non_empty_str)
        _non_empty_str(self.catalog_digest, "catalog_digest")
        _non_empty_str(self.extractor_version, "extractor_version")
        _non_empty_str(self.rule_schema_version, "rule_schema_version")
        if not isinstance(self.build_config, dict):
            raise FingerprintError("build_config must be a dict")
        if self.parent_release_id is not None:
            _non_empty_str(self.parent_release_id, "parent_release_id")
        # Copy mutable containers so that later changes by the caller cannot alter a stored fingerprint.
        object.__setattr__(self, "source_shas", copy.deepcopy(self.source_shas))
        object.__setattr__(self, "snapshot_digests", copy.deepcopy(self.snapshot_digests))
        object.__setattr__(self, "build_config", copy.deepcopy(self.build_config))
        try:
            canonical_bytes(self.to_dict())
        except CanonicalError as exc:
            raise FingerprintError(f"fingerprint input is not canonical JSON: {exc}") from None

    def to_dict(self) -> dict:
        return {"source_shas": copy.deepcopy(self.source_shas),
                "snapshot_digests": copy.deepcopy(self.snapshot_digests),
                "catalog_digest": self.catalog_digest,
                "extractor_version": self.extractor_version,
                "rule_schema_version": self.rule_schema_version,
                "build_config": copy.deepcopy(self.build_config),
                "parent_release_id": self.parent_release_id}

    @classmethod
    def from_dict(cls, data: dict) -> "FingerprintInputs":
        if not isinstance(data, dict) or set(data) != set(INPUT_NAMES):
            raise FingerprintError(f"fingerprint inputs must have exactly the keys {sorted(INPUT_NAMES)}")
        return cls(**{name: data[name] for name in INPUT_NAMES})

    def digest(self) -> str:
        return digest_obj({"format": FINGERPRINT_FORMAT, **self.to_dict()})


def compute_fingerprint(*, source_shas: dict, snapshot_digests: dict, catalog_digest: str, extractor_version: str,
                        rule_schema_version: str, build_config: dict, parent_release_id: Optional[str]) -> str:
    """sha256 hex of the canonical JSON of all inputs. Raises `FingerprintError` on invalid input."""
    return FingerprintInputs(source_shas=source_shas, snapshot_digests=snapshot_digests,
                             catalog_digest=catalog_digest, extractor_version=extractor_version,
                             rule_schema_version=rule_schema_version, build_config=build_config,
                             parent_release_id=parent_release_id).digest()


def _check_fingerprint(value: str, what: str) -> None:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise FingerprintError(f"{what} is not a sha256 hex fingerprint")


def compare_fingerprints(previous: Optional[str], current: str) -> Comparison:
    """NO_PREVIOUS when there is no stored fingerprint, else UNCHANGED or CHANGED."""
    _check_fingerprint(current, "current fingerprint")
    if previous is None:
        return NO_PREVIOUS
    _check_fingerprint(previous, "previous fingerprint")
    return UNCHANGED if previous == current else CHANGED


_MISSING = object()


def explain_change(prev_inputs: Optional[dict], cur_inputs: dict) -> list:
    """Sorted names of the top-level inputs that differ between two `to_dict()` forms.

    A name present on one side only counts as changed. With no previous inputs every input of `cur_inputs` is
    reported, which matches the NO_PREVIOUS comparison."""
    if prev_inputs is None:
        return sorted(cur_inputs)
    names = set(prev_inputs) | set(cur_inputs)
    return sorted(name for name in names
                  if prev_inputs.get(name, _MISSING) != cur_inputs.get(name, _MISSING))
