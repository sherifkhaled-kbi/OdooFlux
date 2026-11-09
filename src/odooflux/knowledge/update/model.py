"""Shared value types of the knowledge update manager (feature 012). Pure data; no I/O, no network.

`SourceCheck.status` values (per source, never merged): OK, SKIPPED_OFFLINE, SKIPPED_NO_CREDENTIALS, AUTH_FAILED,
UNAVAILABLE. A missing Enterprise token is SKIPPED_NO_CREDENTIALS (not an error); a rejected token is AUTH_FAILED; an
unreachable remote is UNAVAILABLE. `CheckReport.statuses` uses the overall vocabulary of the feature brief; several may coexist.
"""

from dataclasses import dataclass, field

SOURCE_STATUSES = ("OK", "SKIPPED_OFFLINE", "SKIPPED_NO_CREDENTIALS", "AUTH_FAILED", "UNAVAILABLE")
OVERALL_STATUSES = ("NO_UPDATE", "SOURCE_REVISION_AVAILABLE", "KNOWLEDGE_UPDATE_AVAILABLE", "NEW_VERSION_DISCOVERED",
                    "TRANSITION_NOT_YET_SUPPORTED", "CHECK_UNAVAILABLE", "LOCAL_STATE_INVALID")
FRESHNESS = ("FRESH", "OUTDATED", "STALE_UNVERIFIED", "NOT_INSTALLED", "UNKNOWN")
# check: FRESH/OUTDATED when the remote was read; UNKNOWN when it could not be; NOT_INSTALLED when no Enterprise source is
# installed. STALE_UNVERIFIED is for carried-forward components in an update (not produced by check).



@dataclass(frozen=True)
class InstalledState:
    """What the active release says is installed. `release_id` None = built-in knowledge only (nothing installed)."""
    release_id: object = None
    digest: object = None
    revisions: dict = field(default_factory=dict)  # source_id -> pinned 40-hex revision recorded in the release manifest
    valid: bool = True
    problem: object = None  # set when valid is False (corrupt/unreadable state; never silently treated as empty)
    # source_id -> 64-hex digest of the VERIFIED snapshot recorded in the release manifest. Empty when the manifest has no
    # snapshot digest for a source; a present but malformed digest makes the whole state invalid (see discovery).
    snapshot_digests: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SourceCheck:
    source_id: str
    edition: str
    version: str
    remote_sha: object  # 40-hex or None when the remote was not (or could not be) read
    installed_sha: object  # 40-hex or None
    status: str  # one of SOURCE_STATUSES
    detail: str = ""  # short, already scrubbed

    def changed(self) -> bool:
        return bool(self.remote_sha) and self.remote_sha != self.installed_sha

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "edition": self.edition, "version": self.version,
                "remote_sha": self.remote_sha, "installed_sha": self.installed_sha, "status": self.status,
                "detail": self.detail}


@dataclass(frozen=True)
class NewVersion:
    edition: str
    version: str
    branch: str
    remote_sha: str

    def to_dict(self) -> dict:
        return {"edition": self.edition, "version": self.version, "branch": self.branch, "remote_sha": self.remote_sha}


@dataclass(frozen=True)
class CheckReport:
    schema: str  # "odooflux.knowledge-check/1"
    statuses: tuple
    sources: tuple  # SourceCheck, in catalog order
    new_versions: tuple  # NewVersion
    affected_transitions: tuple  # "16-17" style labels (numeric majors, derived from catalog versions)
    enterprise_freshness: str  # one of FRESHNESS
    catalog_digest: str
    offline: bool
    installed_release: object  # release id or None

    def to_dict(self) -> dict:
        return {"schema": self.schema, "statuses": list(self.statuses), "sources": [s.to_dict() for s in self.sources],
                "new_versions": [n.to_dict() for n in self.new_versions],
                "affected_transitions": list(self.affected_transitions),
                "enterprise_freshness": self.enterprise_freshness, "catalog_digest": self.catalog_digest,
                "offline": self.offline, "installed_release": self.installed_release}


def transition_label(from_version: str, to_version: str) -> str:
    """two release versions -> "NN-MM" (the step label used by the pipeline and the migrate CLI)."""
    return f"{int(str(from_version).split('.')[0])}-{int(str(to_version).split('.')[0])}"


UPDATE_OUTCOMES = ("NOOP", "ACTIVE", "BLOCKED", "FAILED", "ROLLED_BACK", "DRY_RUN")
UPDATE_SCHEMA = "odooflux.knowledge-update/1"
# The four support dimensions are reported separately and are never inferred from each other (feature brief section 13).
CERTIFICATION_STATEMENT = {
    "source_availability": "reported per source (verified provenance of the acquired snapshot)",
    "knowledge_completeness": "reported from the release (COMPLETE or PARTIAL)",
    "migration_support": "not established by an update",
    "production_certification": "NOT_GRANTED",
}


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of one `knowledge update` run. Plain data; every nested value is JSON-serialisable and already scrubbed.

    outcome: NOOP (nothing relevant changed, no release created), ACTIVE (a new release was activated), BLOCKED (a
    safety/activation condition stopped it; previous release preserved), FAILED (acquisition/build/activation error;
    previous release preserved), ROLLED_BACK (activation faulted and the previous pointer was restored), DRY_RUN (plan
    only: nothing downloaded, built, installed or activated). `changes` holds counts and short id lists only."""
    outcome: str
    reasons: tuple = ()
    dry_run: bool = False
    offline: bool = False
    previous_release: object = None
    new_release: object = None
    release_digest: object = None
    completeness: object = None
    check: object = None  # CheckReport.to_dict()
    plan: object = None  # UpdatePlan.to_dict()
    acquisition: object = None  # AcquireResult.to_dict()
    build: object = None  # {"outcome","code","message","release_id","completeness"}
    activation: object = None  # ActivationDecision.to_dict() plus {"state": ...}
    changes: object = None  # {"rules_added","rules_changed","rules_lost","rules_downgraded","rules_superseded",
    #                          "fix_enabled_added","detect_only_added","versions_added","transitions_added", ...}
    carried_forward: tuple = ()
    enterprise: object = None  # {"status": ..., "freshness": ...}
    limitations: tuple = ()
    history_seq: object = None

    def to_dict(self) -> dict:
        return {"schema": UPDATE_SCHEMA, "outcome": self.outcome, "reasons": list(self.reasons), "dry_run": self.dry_run,
                "offline": self.offline, "previous_release": self.previous_release, "new_release": self.new_release,
                "release_digest": self.release_digest, "completeness": self.completeness, "check": self.check,
                "plan": self.plan, "acquisition": self.acquisition, "build": self.build, "activation": self.activation,
                "changes": self.changes, "carried_forward": list(self.carried_forward), "enterprise": self.enterprise,
                "limitations": list(self.limitations), "support_dimensions": dict(CERTIFICATION_STATEMENT),
                "history_seq": self.history_seq}
