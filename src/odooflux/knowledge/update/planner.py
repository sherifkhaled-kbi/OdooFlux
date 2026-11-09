"""Incremental update planner (feature 012, plan Addendum B4, task T05).

`plan_update` turns the official source catalog, a remote check report and the installed state into an `UpdatePlan`:
which sources to acquire, which to carry forward unchanged, which Enterprise sources to skip, the unified step pairs to
build, the planning fingerprint and the names of the inputs that changed.

Pure: no I/O, no network, no clock, no credentials. The Enterprise token is only a boolean here. Ordering follows the
catalog entry order everywhere, so the same inputs always give the same plan.

Spec shape: each ACQUIRE source carries a DECLARED record that `acquisition.sources.validate_spec` accepts, at the target
sha; each CARRY_FORWARD catalog source carries the same record at its INSTALLED sha. Every source records `installed_sha`
so a failed non-required acquisition can fall back to the installed revision. `url` is the
allow-listed prefix form (`expected_origin` + "/"), because the catalog `repository` ends in `.git`. `official` is true
for both families (Community and Enterprise). `kind`, `licence_id` and `licence_access` are copied from the catalog
entry, which requires all three. `scope` is the whole-repository scope: an empty `include` applies no filter (confirmed
in git_local). `redistribution` is not part of the spec because the registry schema has no such key; it is carried on
`PlannedSource`. `enterprise_derived` is never part of the spec: classification is derived downstream from the kind.

Two fingerprint lifecycles, never conflated:
- Planning fingerprint (`UpdatePlan.planning_fingerprint`, `UpdatePlan.planning_inputs`): the target revisions come from
  REMOTE metadata, `snapshot_digests` is always empty, and nothing has been acquired. It answers "what would be built".
  It NEVER proves that a snapshot was acquired or verified, and it must never be stored as a build record.
- Build fingerprint (`build_fingerprint`): the same inputs plus the VERIFIED snapshot digest of every ACQUIRE and
  CARRY_FORWARD source (carried digests come from the installed release). It refuses to exist without them.

Persisted for reproducible no-op decisions: the exact `FingerprintInputs.to_dict()` of the last successful build, stored
as the history record's `details["build_inputs"]` (the names are needed, so a digest alone is not enough). Those inputs
are: `source_shas` and `snapshot_digests` (one entry each per ACQUIRE and CARRY_FORWARD source), `catalog_digest`,
`extractor_version`, `rule_schema_version`, `build_config` and `parent_release_id`. `needs_build` compares the current
inputs with them. A plan NOOP from `plan_update` is only a planning hint: it does not by itself skip a build.

`plan_update`'s NOOP and BUILD decisions use `last_inputs` (a planning form), not `last_fingerprint`.
"""

import copy
import re
from dataclasses import dataclass, field

from odooflux.knowledge.update import fingerprint as fp
from odooflux.knowledge.update.model import InstalledState, transition_label

__all__ = ["PlannedSource", "UpdatePlan", "plan_update", "build_fingerprint", "needs_build", "DECISIONS", "ACTIONS",
           "BLOCKING_CODES", "NOT_PLANNED", "NO_INPUT_CHANGE", "PENDING_FINGERPRINT", "NO_PREVIOUS_BUILD_INPUTS"]

DECISIONS = ("NOOP", "BUILD", "BLOCKED")
ACTIONS = ("ACQUIRE", "CARRY_FORWARD", "SKIP")
BLOCKING_CODES = ("LOCAL_STATE_INVALID", "CHECK_CATALOG_MISMATCH", "CHECK_UNAVAILABLE", "ENTERPRISE_REQUIRED_UNAVAILABLE",
                  "ENTERPRISE_AUTH_FAILED", "ENTERPRISE_UNAVAILABLE")
NOT_PLANNED = "discovered, not planned: migration support not established"
NO_INPUT_CHANGE = "no relevant input changed"
PENDING_FINGERPRINT = "plan fingerprint pending acquisition"
NO_PREVIOUS_BUILD_INPUTS = "no previous build inputs"

_BLOCK_MESSAGES = {
    "LOCAL_STATE_INVALID": "installed state is invalid; repair the knowledge home before updating",
    "CHECK_CATALOG_MISMATCH": "check report was computed for a different catalog digest; run the check again",
    "CHECK_UNAVAILABLE": "remote check unavailable; no update is decided offline",
    "ENTERPRISE_REQUIRED_UNAVAILABLE": "Enterprise required but no usable Enterprise credentials or sources; nothing acquired",
    "ENTERPRISE_AUTH_FAILED": "Enterprise required but the Enterprise credentials were rejected; nothing acquired",
    "ENTERPRISE_UNAVAILABLE": "Enterprise required but the Enterprise remote is unavailable; nothing acquired",
}
# Enterprise codes in the order the blocking reason is chosen when several sources fail.
_ENTERPRISE_PRIORITY = ("ENTERPRISE_AUTH_FAILED", "ENTERPRISE_UNAVAILABLE", "ENTERPRISE_REQUIRED_UNAVAILABLE")
# Inputs that change what the extraction emits for unchanged sources: a change forces every pair to run again.
_FORCING_INPUTS = ("catalog_digest", "extractor_version", "rule_schema_version", "build_config")
# The inputs a build record must carry besides the source maps (checked against the plan by `build_fingerprint`).
_PLAN_BOUND_INPUTS = ("catalog_digest", "extractor_version", "rule_schema_version", "build_config", "parent_release_id")
_INSTALLED_ID = re.compile(r"odoo-(community|enterprise)-([0-9]+\.[0-9]+)")
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class PlannedSource:
    source_id: str
    edition: str
    version: str
    repository: object
    branch: object
    target_sha: object
    action: str
    required: bool
    spec: dict = field(default_factory=dict)
    redistribution: object = None  # from the catalog entry; not part of the registry spec
    installed_sha: object = None  # 40-hex revision the installed release pins, or None; set on every source

    def to_dict(self) -> dict:
        return {"source_id": self.source_id, "edition": self.edition, "version": self.version,
                "repository": self.repository, "branch": self.branch, "target_sha": self.target_sha,
                "action": self.action, "required": self.required, "spec": _copy(self.spec),
                "redistribution": self.redistribution, "installed_sha": self.installed_sha}


@dataclass(frozen=True)
class UpdatePlan:
    """A planning result. `planning_fingerprint` and `planning_inputs` are the PLANNING form (see module docstring):
    empty `snapshot_digests`, remote-derived SHAs, never a build record."""
    decision: str
    blocking_reason: object
    reasons: list
    sources: list
    pairs: list
    carried_forward: list
    planning_fingerprint: object
    planning_inputs: dict
    change_explanation: list

    def to_dict(self) -> dict:
        return {"decision": self.decision, "blocking_reason": self.blocking_reason, "reasons": list(self.reasons),
                "sources": [s.to_dict() for s in self.sources], "pairs": _copy(self.pairs),
                "carried_forward": list(self.carried_forward), "planning_fingerprint": self.planning_fingerprint,
                "planning_inputs": _copy(self.planning_inputs), "change_explanation": list(self.change_explanation)}


@dataclass
class _Draft:
    """Mutable working record for one source, turned into a PlannedSource at the end."""
    source_id: str
    edition: str
    version: str
    repository: object
    branch: object
    target_sha: object
    action: str
    required: bool
    note: str
    installed: bool
    redistribution: object = None
    installed_sha: object = None


def plan_update(catalog, check, installed, *, token_available: bool, require_enterprise: bool = False,
                only_pair=None, extractor_version: str, rule_schema_version: str, build_config: dict,
                last_fingerprint=None, last_inputs=None) -> UpdatePlan:
    """Plan one incremental update. See the module docstring. `last_fingerprint` is accepted for the caller's record
    only; decisions compare `last_inputs` (planning form)."""
    pair_filter = _pair_filter(only_pair)
    state_invalid = (not installed.valid) or ("LOCAL_STATE_INVALID" in check.statuses)
    inst = InstalledState() if state_invalid else installed  # never plan from a state that cannot be trusted
    checks = {sc.source_id: sc for sc in check.sources}
    catalog_ids = [catalog.source_id(entry) for entry in catalog.entries]

    blocks = []
    if state_invalid:
        blocks.append("LOCAL_STATE_INVALID")
    if check.catalog_digest != catalog.digest:
        blocks.append("CHECK_CATALOG_MISMATCH")

    drafts, ent_codes, community_unread = [], [], False
    for entry in catalog.entries:
        sid = catalog.source_id(entry)
        sc = checks.get(sid)
        is_installed = sid in inst.revisions
        installed_sha = inst.revisions.get(sid)
        remote = sc.remote_sha if (sc is not None and sc.status == "OK") else None
        read = remote is not None
        draft = _Draft(sid, entry.edition, entry.version, entry.repository, entry.branch, None, "SKIP",
                       entry.edition == "community" or require_enterprise, "", is_installed,
                       redistribution=entry.redistribution, installed_sha=installed_sha)
        if read and (entry.edition == "community" or token_available):
            if not is_installed:
                draft.action, draft.target_sha, draft.note = "ACQUIRE", remote, "not installed; acquire"
            elif remote != installed_sha:
                draft.action, draft.target_sha, draft.note = "ACQUIRE", remote, "revision changed; acquire"
            else:
                draft.action, draft.target_sha, draft.note = "CARRY_FORWARD", installed_sha, \
                    "unchanged; carried forward"
        else:
            if entry.edition == "community":
                code, why = "CHECK_UNAVAILABLE", f"remote not read ({sc.status if sc else 'not checked'})"
                community_unread = True
            else:
                code, why = _enterprise_problem(token_available, sc)
                ent_codes.append(code)
            if is_installed:
                draft.action, draft.target_sha = "CARRY_FORWARD", installed_sha
                draft.note = f"{why} ({code}); carried forward from the installed release"
            else:
                draft.note = f"{why} ({code}); not installed, skipped"
        drafts.append(draft)

    for sid in sorted(inst.revisions):  # installed sources the catalog no longer lists: carried, never removed
        if sid in catalog_ids:
            continue
        match = _INSTALLED_ID.fullmatch(sid)
        edition, version = (match.group(1), match.group(2)) if match else ("unknown", "")
        drafts.append(_Draft(sid, edition, version, None, None, inst.revisions[sid], "CARRY_FORWARD", False,
                             "installed, absent from the current catalog; carried forward, never removed", True,
                             installed_sha=inst.revisions[sid]))

    if community_unread or "CHECK_UNAVAILABLE" in check.statuses:
        blocks.append("CHECK_UNAVAILABLE")
    if require_enterprise:
        blocks.extend(code for code in _ENTERPRISE_PRIORITY if code in ent_codes)
    blocking = blocks[0] if blocks else None

    if blocking is not None:  # nothing is acquired; the installed release stays as it is
        for draft in drafts:
            if draft.action == "ACQUIRE":
                draft.action = "CARRY_FORWARD" if draft.installed else "SKIP"
                draft.target_sha = inst.revisions.get(draft.source_id)
                draft.note += "; not acquired, plan blocked"

    # ACQUIRE sources get a spec at the target sha; CARRY_FORWARD catalog sources get one at the installed sha.
    # Installed sources absent from the catalog have no catalog entry to declare from, so they keep an empty spec.
    specs = {d.source_id: _declared_spec(catalog, d) for d in drafts
             if d.action in ("ACQUIRE", "CARRY_FORWARD") and d.source_id in catalog_ids}
    planned = [_to_planned(d, specs.get(d.source_id, {})) for d in drafts]

    inputs, cur_inputs = None, None
    if blocking is None:
        inputs = fp.FingerprintInputs(
            source_shas={_fp_key(p): p.target_sha for p in planned if p.target_sha is not None},
            snapshot_digests={}, catalog_digest=catalog.digest, extractor_version=extractor_version,
            rule_schema_version=rule_schema_version, build_config=build_config,
            parent_release_id=None if inst.release_id is None else str(inst.release_id))
        cur_inputs = inputs.to_dict()
    changed = fp.explain_change(last_inputs, cur_inputs) if cur_inputs is not None else []

    pairs = []
    if blocking is None:
        pairs = _pairs(catalog, planned, inst, pair_filter, forced=any(n in changed for n in _FORCING_INPUTS))

    acquiring = any(p.action == "ACQUIRE" for p in planned)
    if blocking is not None:
        decision = "BLOCKED"
    elif acquiring or changed:
        decision = "BUILD"
    else:
        decision = "NOOP"

    reasons = []
    if blocking is not None:
        reasons.append(f"{blocking}: {_BLOCK_MESSAGES[blocking]}")
    reasons.extend(f"{d.source_id}: {d.note}" for d in drafts)
    if cur_inputs is not None and last_inputs is None:
        reasons.append("no previous fingerprint inputs recorded; full plan")
    reasons.extend(f"input changed: {name}" for name in changed if last_inputs is not None)
    known = {(e.edition, e.version) for e in catalog.entries}
    for nv in check.new_versions:
        if (nv.edition, nv.version) not in known:
            reasons.append(f"{nv.edition} {nv.version}: {NOT_PLANNED}")
    if decision == "NOOP":
        reasons.append(NO_INPUT_CHANGE)
    elif decision == "BUILD":
        reasons.append(PENDING_FINGERPRINT)

    if blocking is not None:
        return UpdatePlan(decision, blocking, reasons, planned, [], _carried(planned), None, {}, [])
    return UpdatePlan(decision, None, reasons, planned, pairs, _carried(planned),
                      inputs.digest(), cur_inputs, changed)


def build_fingerprint(plan: UpdatePlan, snapshot_digests: dict, *, extractor_version: str, rule_schema_version: str,
                      build_config: dict, parent_release_id) -> tuple:
    """(fingerprint, inputs) of a BUILD from VERIFIED snapshot digests. `inputs` is `FingerprintInputs.to_dict()`, the
    form to persist as the last build's `details["build_inputs"]`.

    `snapshot_digests` maps source_id -> 64-hex digest for EVERY ACQUIRE source (verified in this run) and EVERY
    CARRY_FORWARD source (taken from the installed release's snapshot digests). Raises `FingerprintError` when:
    the plan is blocked (it has no planning inputs); a digest is missing, not 64 lowercase hex, or belongs to a source
    outside the acquire/carry set; there are no acquire/carry sources; or the given extractor, rule-schema, build
    config, parent release or catalog digest differ from the values the plan was made with.
    """
    if plan.decision == "BLOCKED" or not plan.planning_inputs:
        raise fp.FingerprintError("a blocked plan has no build fingerprint")
    members = [p for p in plan.sources if p.action in ("ACQUIRE", "CARRY_FORWARD")]
    if not members:
        raise fp.FingerprintError("a build needs at least one acquired or carried source")
    member_ids = {_fp_key(p) for p in members}
    if not isinstance(snapshot_digests, dict):
        raise fp.FingerprintError("snapshot_digests must be a dict of source_id to digest")
    missing = sorted(member_ids - set(snapshot_digests))
    if missing:
        raise fp.FingerprintError(f"no verified snapshot digest for: {', '.join(missing)}")
    extra = sorted(str(sid) for sid in set(snapshot_digests) - member_ids)
    if extra:
        raise fp.FingerprintError(f"snapshot digests given for sources outside the plan: {', '.join(extra)}")
    for sid in sorted(member_ids):
        digest = snapshot_digests[sid]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise fp.FingerprintError(f"snapshot digest for {sid} is not 64 lowercase hex characters")
    inputs = fp.FingerprintInputs(
        source_shas={_fp_key(p): p.target_sha for p in members},
        snapshot_digests={sid: snapshot_digests[sid] for sid in sorted(member_ids)},
        catalog_digest=plan.planning_inputs["catalog_digest"], extractor_version=extractor_version,
        rule_schema_version=rule_schema_version, build_config=build_config, parent_release_id=parent_release_id)
    current = inputs.to_dict()
    planned = plan.planning_inputs
    if current["source_shas"] != planned["source_shas"]:
        raise fp.FingerprintError("source revisions differ from the plan")
    for name in _PLAN_BOUND_INPUTS:
        if current[name] != planned[name]:
            raise fp.FingerprintError(f"{name} differs from the plan")
    return inputs.digest(), current


def needs_build(plan_inputs_now: dict, last_build_inputs) -> tuple:
    """(needs_build, changed) for the current inputs against the persisted inputs of the last successful build.

    `plan_inputs_now` is a `FingerprintInputs.to_dict()` form and is validated. `last_build_inputs` is the stored
    `details["build_inputs"]`. When it is None, or is not a build form (wrong keys, malformed values, a source set that
    differs between revisions and digests, or EMPTY snapshot digests, which is the planning form), the result is
    (True, [NO_PREVIOUS_BUILD_INPUTS]). Otherwise `changed` is the sorted list of input names that differ (empty when
    nothing changed), as `fingerprint.explain_change` reports them.
    """
    current = fp.FingerprintInputs.from_dict(plan_inputs_now).to_dict()
    previous = _build_form_or_none(last_build_inputs)
    if previous is None:
        return True, [NO_PREVIOUS_BUILD_INPUTS]
    changed = fp.explain_change(previous, current)
    return bool(changed), changed


def _build_form_or_none(data):
    """The normalised build-form inputs of a stored record, or None when the record is not a build record."""
    if not isinstance(data, dict):
        return None
    try:
        inputs = fp.FingerprintInputs.from_dict(data)
    except fp.FingerprintError:
        return None
    if not inputs.snapshot_digests:  # the planning form carries no verified digests: never a build record
        return None
    if set(inputs.snapshot_digests) != set(inputs.source_shas):
        return None
    if not all(isinstance(value, str) and _DIGEST.fullmatch(value) for value in inputs.snapshot_digests.values()):
        return None
    return inputs.to_dict()


def _enterprise_problem(token_available: bool, sc) -> tuple:
    """(code, why) for an Enterprise source that cannot be acquired this run."""
    if not token_available:
        return "ENTERPRISE_REQUIRED_UNAVAILABLE", "no Enterprise credentials"
    status = sc.status if sc is not None else None
    if status is None:
        return "ENTERPRISE_UNAVAILABLE", "Enterprise source not checked"
    if status.startswith("SKIPPED_"):
        return "ENTERPRISE_REQUIRED_UNAVAILABLE", f"Enterprise source {status.lower()}"
    if status == "AUTH_FAILED":
        return "ENTERPRISE_AUTH_FAILED", "Enterprise credentials rejected"
    return "ENTERPRISE_UNAVAILABLE", f"Enterprise remote {status.lower()}"


def _declared_spec(catalog, draft: _Draft) -> dict:
    """A DECLARED SourceSpec that `sources.validate_spec` accepts for an allow-listed remote (see module docstring)."""
    entry = next(e for e in catalog.entries if catalog.source_id(e) == draft.source_id)
    return {
        "source_id": draft.source_id,
        "kind": entry.kind,
        "official": True,
        "url": entry.expected_origin + "/",
        "licence_access": entry.licence_access,
        "licence_id": entry.licence_id,
        "branch": entry.branch,
        "revision": draft.target_sha,
        "scope": {"modules": "*", "include": [], "exclude": [], "file_kinds": []},
        "retrieved_at": None,
        "checksum": None,
        "status": "DECLARED",
        "failure_reason": None,
        "required": draft.required,
        "expected_origin": entry.expected_origin,
    }


def _pairs(catalog, planned, inst, pair_filter, *, forced: bool) -> list:
    """Unified step pairs: consecutive versions per edition where a pair is changed, uncovered, or forced."""
    by_id = {p.source_id: p for p in planned}
    out = []
    for edition in catalog.editions():
        for a, b in catalog.pairs(edition):
            if pair_filter is not None and (_major(a), _major(b)) != pair_filter:
                continue
            ida, idb = catalog.source_id(catalog.entry_for(a, edition)), catalog.source_id(catalog.entry_for(b, edition))
            pa, pb = by_id[ida], by_id[idb]
            if "SKIP" in (pa.action, pb.action):
                continue
            covered = ida in inst.revisions and idb in inst.revisions
            if forced or "ACQUIRE" in (pa.action, pb.action) or not covered:
                out.append({"step": transition_label(a, b), "from": ida, "to": idb})
    return out


def _carried(planned) -> list:
    return [p.source_id for p in planned if p.action == "CARRY_FORWARD"]


def _to_planned(draft: _Draft, spec: dict) -> PlannedSource:
    return PlannedSource(draft.source_id, draft.edition, draft.version, draft.repository, draft.branch,
                         draft.target_sha, draft.action, draft.required, spec, draft.redistribution,
                         draft.installed_sha)


def _fp_key(p: PlannedSource) -> str:
    """Fingerprint source id: the registry-valid source id from `catalog.source_id` (owner decision)."""
    return p.source_id


def _major(version: str) -> str:
    return str(version).split(".")[0]


def _pair_filter(only_pair):
    if only_pair is None:
        return None
    if not isinstance(only_pair, (tuple, list)) or len(only_pair) != 2:
        raise ValueError("only_pair must be a (from_major, to_major) pair such as ('16', '17') or None")
    return (_major(only_pair[0]), _major(only_pair[1]))


def _copy(value):
    return copy.deepcopy(value)
