"""Knowledge update orchestrator (feature 012, Wave 3c; plan Addendum E). Behind `knowledge update`.

`run_update` sequences the update manager's parts and decides nothing they do not decide itself: discovery (read-only
check), planner (what is acquired, carried and paired), acquisition (verified commits, retained Enterprise snapshots),
the unchanged pipeline (`pipeline.run_build` in the stable staging workdir `<kb-home>/staging/update/`), activation
evaluation, and the one audited pointer swap in `activation.activate_release`.

Order of work: the update lock `<kb-home>/updates/.update.lock` (flock, bounded wait) is held for the whole run. A dry run
writes nothing and takes no lock. Installed state and the history chain are checked before any network access. Nothing is
fetched or built until the check and the plan have decided it. A release changes only through `activate_release`. Every
failure before that point leaves the previous pointer as it was. Every returned value and every history record is scrubbed
of the token value.

Persisted build inputs: each ACTIVE and NOOP history record carries `details["build_inputs"]`, the `FingerprintInputs` form
of the release the record describes. Its `parent_release_id` is the release that run installed or kept, which is the
installed release the next run plans against. A repeated run with no change therefore compares equal and is a NOOP. The
planner receives the planning form (snapshot digests emptied), as `plan_update` requires.

Pair completion: the planner emits only pairs that changed or are uncovered. The pipeline builds without a parent overlay,
so a pair whose two sources both take part in the build is always added, carried Enterprise pairs included. Otherwise the
rules that a carried source produces would be dropped and the build would stop as a destructive change.
"""

import contextlib
import errno
import fcntl
import json
import os
import time
from pathlib import Path

from odooflux import __version__
from odooflux.knowledge import autofix
from odooflux.knowledge import pipeline as pl
from odooflux.knowledge.acquisition.adapters.git_local import GitLocalAdapter
from odooflux.knowledge.acquisition.adapters.retained import RetainedSnapshotAdapter
from odooflux.knowledge.acquisition.sources import is_enterprise_kind, load_allow_list
from odooflux.knowledge.extract import driver
from odooflux.knowledge.release import coverage_check as cc
from odooflux.knowledge.release.manifest import MANIFEST_NAME
from odooflux.knowledge.release.model import builtin_handle
from odooflux.knowledge.release.store import read_active, utc_now
from odooflux.knowledge.update import acquire as acq
from odooflux.knowledge.update import activation, capability, discovery
from odooflux.knowledge.update import fingerprint as fp
from odooflux.knowledge.update import inventory, planner
from odooflux.knowledge.update.catalog import CatalogError, load_catalog
from odooflux.knowledge.update.history import HistoryError, UPDATES_DIR, UpdateHistory
from odooflux.knowledge.update.model import CheckReport, UpdateResult, transition_label
from odooflux.utils.redaction import scrub

__all__ = ["run_update", "LABEL", "BUILD_CONFIG", "UPDATE_LOCK_NAME", "LOCK_WAIT_SECONDS"]

LABEL = "update"
BUILD_CONFIG = {"label": LABEL, "supersede_policy": capability.POLICY_NAME, "tool_version": __version__}
UPDATE_LOCK_NAME = ".update.lock"
LOCK_WAIT_SECONDS = 5.0  # bounded wait for the update lock; tests shorten it
LOCK_POLL_SECONDS = 0.05
FAULT_POINTS = ("verify", "lock", "pointer", "audit")
ENTERPRISE_PREFIX = discovery.ENTERPRISE_PREFIX
ENTERPRISE_FAILURES = ("AUTH_FAILED", "UNAVAILABLE", "SKIPPED_NO_CREDENTIALS", "SKIPPED_OFFLINE")
# Pipeline stop codes that mean a gate refused the candidate (BLOCKED). Every other stop is a FAILED build.
GATE_CODES = frozenset({
    "DESTRUCTIVE_NEEDS_SUPERSEDE", "COMPLETENESS_FAILED", "SCHEMA_INVALID", "AUTHORING_INVALID",
    "MANIFEST_INCONSISTENT", "INVENTORY_INVALID", "INVENTORY_BRANCH_INVALID", "LINKED_EVIDENCE_REFUSED",
    "PROVENANCE_INVALID", "RELEASE_INTEGRITY", "RELEASE_EXISTS",
})
_MAX_REASON = 300
_NOT_CHANGED = (acq.NOT_ATTEMPTED, acq.NOT_REQUIRED)


class _LockBusy(Exception):
    """Another update holds the update lock (contention, not an error)."""


class _LockError(Exception):
    """The update lock cannot be taken for a reason other than contention."""


def _extractor(toolkit):
    """The extract callable of `BuildPlan.extract`, composed the way `cli/kap_release` composes it."""
    registry = driver.default_registry()

    def extract(from_snap, to_snap, step, store):
        result = driver.extract_pair(from_snap, to_snap, None, registry, store=store, step=step, toolkit=toolkit)
        return result.drafts, result.accounting
    return extract


@contextlib.contextmanager
def _update_lock(home: Path, wait: float):
    """flock on `<home>/updates/.update.lock`, created 0700 with its directory. Raises _LockBusy after `wait` seconds."""
    updates = home / UPDATES_DIR
    if updates.is_symlink():
        raise _LockError("the updates directory is a symlink")
    try:
        os.makedirs(home, exist_ok=True)
        os.makedirs(updates, mode=0o700, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(updates / UPDATE_LOCK_NAME, flags, 0o600)
    except OSError as exc:
        raise _LockError(f"cannot open the update lock ({type(exc).__name__})") from None
    try:
        deadline = time.monotonic() + max(0.0, float(wait))
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise _LockError(f"the update lock failed ({type(exc).__name__})") from None
            if time.monotonic() >= deadline:
                raise _LockBusy()
            time.sleep(LOCK_POLL_SECONDS)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the flock


class _Run:
    """State of one run: the home, the switches, the secrets to scrub, and the history writer."""

    def __init__(self, home, *, offline, dry_run, require_enterprise, only_pair, token, ls_remote, fetch, transport_for,
                 clock, cache_dir, fault_at, catalog, toolkit):
        self.home = home
        self.offline = offline
        self.dry_run = dry_run
        self.require_enterprise = require_enterprise
        self.only_pair = only_pair
        self.token = token
        self.secrets = (token.reveal(),) if token is not None else ()
        self.ls_remote = ls_remote
        self.fetch = fetch
        self.transport_for = transport_for
        self.clock = clock
        self.cache_dir = cache_dir
        self.fault_at = fault_at
        self.catalog = catalog
        self.toolkit = toolkit
        self.history = None
        self.history_error = None
        self.prev_id = None

    # --- output helpers -------------------------------------------------------------------------------------------

    def clean(self, value):
        return scrub(value, self.secrets)

    def reasons(self, values) -> tuple:
        return tuple(self.clean(str(v))[:_MAX_REASON] for v in values)

    def result(self, outcome, reasons=(), **fields) -> UpdateResult:
        values = {"outcome": outcome, "reasons": self.reasons(reasons), "dry_run": self.dry_run,
                  "offline": self.offline, "previous_release": self.prev_id,
                  "history_seq": self._latest_seq()}
        for key, value in fields.items():
            values[key] = None if value is None else self.clean(value)
        if "carried_forward" in values and values["carried_forward"] is not None:
            values["carried_forward"] = tuple(values["carried_forward"])
        if "limitations" in values and values["limitations"] is not None:
            values["limitations"] = tuple(values["limitations"])
        values.setdefault("carried_forward", ())
        values.setdefault("limitations", ())
        return UpdateResult(**values)

    def _latest_seq(self):
        if self.dry_run or self.history is None or self.history_error is not None:
            return None
        try:
            newest = self.history.read(limit=1)
        except HistoryError:
            return None
        return newest[0]["seq"] if newest else None

    # --- history --------------------------------------------------------------------------------------------------

    def record(self, outcome, reasons=(), *, fingerprint=None, new_release=None, revisions=None, details=None):
        """Append one history record. Never for a dry run. A failed append is noted, not raised."""
        if self.dry_run or self.history is None:
            return
        record = {"outcome": outcome, "fingerprint": fingerprint, "previous_release": self.prev_id,
                  "new_release": new_release, "source_revisions": dict(revisions or {}),
                  "reason": self.reasons(reasons)[0] if reasons else None}
        if details is not None:
            record["details"] = details
        try:
            self.history.append(record, secrets=self.secrets)
        except HistoryError as exc:
            self.history_error = exc.code


def _major(version) -> str:
    return str(version).split(".")[0]


def _pair_selected(only_pair, a, b) -> bool:
    if only_pair is None:
        return True
    return (_major(only_pair[0]), _major(only_pair[1])) == (_major(a), _major(b))


def _last_build_inputs(history):
    """The build-form inputs of the newest ACTIVE or NOOP record, or None when it has none."""
    for entry in history.read():
        if entry["outcome"] in ("ACTIVE", "NOOP"):
            details = entry.get("details") or {}
            return details.get("build_inputs")
    return None


def _release_dir(home: Path, release_id):
    return None if release_id is None else home / "releases" / release_id


def _release_meta(release_dir: Path) -> dict:
    return json.loads((release_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def _build_output(home: Path) -> dict:
    """The `build-package` step output of the update workdir (its approved supersede ids and digest)."""
    steps = home / pl.STAGING_DIR / LABEL / "steps"
    for path in sorted(steps.glob("*-build-package.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        output = record.get("output")
        return output if isinstance(output, dict) else {}
    return {}


def _enterprise_findings(prev_dir, new_dir, branches) -> list:
    """Carried Enterprise module findings for every branch. A missing or unreadable inventory on either side fails closed."""
    findings = []
    for branch in sorted(set(branches)):
        module = f"inventory:{branch}"
        old_path = prev_dir / "knowledge" / "inventory" / f"{branch}.json"
        new_path = new_dir / "knowledge" / "inventory" / f"{branch}.json"
        if not old_path.is_file():
            findings.append({"module": module, "missing": ["previous inventory not recorded"]})
            continue
        if not new_path.is_file():
            findings.append({"module": module, "missing": ["new inventory not emitted"]})
            continue
        try:
            old = json.loads(old_path.read_text(encoding="utf-8"))
            new = json.loads(new_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            findings.append({"module": module, "missing": ["inventory unreadable"]})
            continue
        problems = inventory.verify_inventory(old) + inventory.verify_inventory(new)
        if problems:
            findings.append({"module": module, "missing": [f"inventory inconsistent: {problems[0]}"[:120]]})
            continue
        try:
            findings.extend(inventory.carry_forward_compat(old, new))
        except inventory.InventoryError as exc:
            findings.append({"module": module, "missing": [f"inventory invalid ({type(exc).__name__})"]})
    return findings


def _pairs(catalog, plan, acquisition, only_pair) -> list:
    """The planner's pairs among participating sources, completed with every other catalog pair both of whose sources
    participate. Each pair gets its key: the step for Community, `<step>.enterprise` for Enterprise."""
    participating = {spec["source_id"] for spec in acquisition.specs}
    edition_of = {src.source_id: src.edition for src in plan.sources}
    pairs = [dict(p) for p in plan.pairs if p["from"] in participating and p["to"] in participating]
    seen = {(p["from"], p["to"]) for p in pairs}
    for edition in catalog.editions():
        for a, b in catalog.pairs(edition):
            if not _pair_selected(only_pair, a, b):
                continue
            ida = catalog.source_id(catalog.entry_for(a, edition))
            idb = catalog.source_id(catalog.entry_for(b, edition))
            if ida in participating and idb in participating and (ida, idb) not in seen:
                pairs.append({"step": transition_label(a, b), "from": ida, "to": idb})
                seen.add((ida, idb))
    for pair in pairs:
        family = edition_of.get(pair["from"], "community")
        pair["key"] = pair["step"] if family != "enterprise" else f"{pair['step']}.enterprise"
    return pairs


def _enterprise_summary(check, installed, acquisition, plan_carried) -> dict:
    """Enterprise status and freshness. Freshness is FRESH only after a successful acquisition in this run."""
    check_by_id = {sc.source_id: sc for sc in check.sources if sc.edition == "enterprise"}
    installed_ent = sorted(sid for sid in installed.revisions if sid.startswith(ENTERPRISE_PREFIX))
    ids = sorted(set(check_by_id) | set(installed_ent))
    if not ids:
        return {"status": "NOT_INSTALLED", "freshness": "NOT_INSTALLED", "carried": [], "sources": []}
    acquired_status = {}
    if acquisition is not None:
        for row in acquisition.results:
            if row.source_id in ids and row.status not in _NOT_CHANGED:
                acquired_status[row.source_id] = row.status
    rows, statuses = [], []
    for sid in ids:
        sc = check_by_id.get(sid)
        check_status = sc.status if sc is not None else None
        status = acquired_status.get(sid)
        if status == acq.REVISION_UNAVAILABLE:
            status = acq.UNAVAILABLE
        for seen in (check_status, status):
            if seen in ENTERPRISE_FAILURES:
                statuses.append(seen)
        rows.append({"source_id": sid, "check": check_status, "acquire": status,
                     "detail": (sc.detail if sc is not None else "")[:200]})
    failure = next((code for code in ENTERPRISE_FAILURES if code in statuses), None)
    acquired = sorted(sid for sid, st in acquired_status.items() if st == acq.ACQUIRED)
    if acquisition is None:
        carried = list(installed_ent)
    else:
        carried = sorted(sid for sid, st in acquired_status.items() if st == acq.CARRIED)
        carried = sorted(set(carried) | {sid for sid in installed_ent if sid not in acquired})
    if failure is not None:
        status = failure
    elif carried:
        status = "CARRIED"
    elif acquired:
        status = "ACQUIRED"
    else:
        status = "NOT_INSTALLED"
    if not installed_ent and not acquired:
        freshness = "NOT_INSTALLED"
    elif acquired and failure is None and not (set(installed_ent) - set(acquired)):
        freshness = "FRESH"
    elif installed_ent:
        freshness = "STALE_UNVERIFIED"
    else:
        freshness = "UNKNOWN"
    return {"status": status, "freshness": freshness, "carried": carried, "sources": rows}


def _limitations(completeness, enterprise) -> tuple:
    out = ["migration support not established", "production certification not granted"]
    if completeness == cc.PARTIAL:
        out.append(activation.PARTIAL_WARNING)
    if enterprise.get("carried"):
        out.append("Enterprise freshness unverified (carried forward)")
        out.append("compatibility of carried Enterprise knowledge with the new Community revision: "
                   "dependency-checked, not source-verified")
    return tuple(out)


def _needs_build(plan, installed, last_build) -> tuple:
    """(needs_build, changed) for a plan that says NOOP, from the verified digests of the installed release."""
    members = [p for p in plan.sources if p.action in ("ACQUIRE", "CARRY_FORWARD")]
    digests = {p.source_id: installed.snapshot_digests[p.source_id] for p in members
               if p.source_id in installed.snapshot_digests}
    if len(digests) != len(members):
        return True, ["no verified snapshot digest for every source"]
    parent = None if installed.release_id is None else str(installed.release_id)
    try:
        _, inputs = planner.build_fingerprint(plan, digests, extractor_version=fp.EXTRACTOR_VERSION,
                                              rule_schema_version=fp.RULE_SCHEMA_VERSION,
                                              build_config=dict(BUILD_CONFIG), parent_release_id=parent)
    except fp.FingerprintError as exc:
        return True, [f"prospective fingerprint unavailable ({type(exc).__name__})"]
    return planner.needs_build(inputs, last_build)


def _build_inputs(meta: dict, catalog_digest: str, parent_release_id: str):
    """(fingerprint digest, build-form inputs) of an installed release, from its own verified manifest."""
    source_shas, digests = {}, {}
    for entry in meta.get("sources") or []:
        sid = entry.get("source_id")
        if not isinstance(sid, str) or "snapshot_digest" not in entry:
            raise ValueError(f"release manifest lacks a snapshot digest for {sid!r}")
        source_shas[sid] = entry["revision"]
        digests[sid] = entry["snapshot_digest"]
    inputs = fp.FingerprintInputs(source_shas=source_shas, snapshot_digests=digests, catalog_digest=catalog_digest,
                                  extractor_version=fp.EXTRACTOR_VERSION, rule_schema_version=fp.RULE_SCHEMA_VERSION,
                                  build_config=dict(BUILD_CONFIG), parent_release_id=parent_release_id)
    return inputs.digest(), inputs.to_dict()


def _changes(prev_dir, new_dir, approved, installed, acquisition, pairs) -> dict:
    diff = capability.compare(prev_dir, new_dir)
    caps = capability.capabilities(new_dir)
    fix_added = sorted(rid for rid in diff.added if caps[rid].maturity == capability.FIX_ENABLED)
    detect_added = sorted(rid for rid in diff.added if caps[rid].maturity == capability.DETECT_ONLY)
    versions_added = sorted(r.source_id for r in acquisition.results
                            if r.status == acq.ACQUIRED and r.source_id not in installed.revisions)
    transitions = sorted({p["step"] for p in pairs
                          if not (p["from"] in installed.revisions and p["to"] in installed.revisions)})
    return {"rules_added": len(diff.added), "rules_changed": len(diff.changed), "rules_lost": len(diff.lost),
            "rules_downgraded": len(diff.downgraded), "rules_unchanged": diff.unchanged,
            "rules_superseded": len(approved), "superseded": sorted(approved),
            "fix_enabled_added": fix_added, "detect_only_added": len(detect_added),
            "versions_added": versions_added, "transitions_added": transitions}


def _execute(run: _Run) -> UpdateResult:
    home = run.home
    installed = discovery.read_installed_state(home)
    run.prev_id = installed.release_id
    try:
        run.history = UpdateHistory(home, clock=run.clock)
        history_ok, history_problems = run.history.verify()
    except HistoryError as exc:
        history_ok, history_problems = False, [exc.code]
    if not history_ok:
        run.history = None
        return run.result("BLOCKED", (f"HISTORY_INVALID: {history_problems[0]}",))
    if not installed.valid:
        run.record("BLOCKED", (f"LOCAL_STATE_INVALID: {installed.problem}",))
        return run.result("BLOCKED", (f"LOCAL_STATE_INVALID: {installed.problem}",),
                          enterprise=_enterprise_summary(_empty_check(run), installed, None, ()))

    check = discovery.check(run.catalog, installed, offline=run.offline, token=run.token, ls_remote=run.ls_remote)
    last_build = _last_build_inputs(run.history)
    last_planning = None if last_build is None else dict(last_build, snapshot_digests={})
    plan = planner.plan_update(run.catalog, check, installed, token_available=run.token is not None,
                               require_enterprise=run.require_enterprise, only_pair=run.only_pair,
                               extractor_version=fp.EXTRACTOR_VERSION, rule_schema_version=fp.RULE_SCHEMA_VERSION,
                               build_config=dict(BUILD_CONFIG), last_inputs=last_planning)
    enterprise = _enterprise_summary(check, installed, None, plan.carried_forward)
    if plan.decision == "BLOCKED":
        run.record("BLOCKED", plan.reasons)
        return run.result("BLOCKED", plan.reasons, check=check.to_dict(), plan=plan.to_dict(),
                          enterprise=enterprise, carried_forward=plan.carried_forward,
                          limitations=_limitations(None, enterprise))

    if plan.decision == "NOOP":
        needs, changed = _needs_build(plan, installed, last_build)
        if not needs:
            if run.dry_run:
                return run.result("DRY_RUN", plan.reasons, check=check.to_dict(), plan=plan.to_dict(),
                                  enterprise=enterprise, carried_forward=plan.carried_forward,
                                  limitations=_limitations(None, enterprise))
            fingerprint = fp.FingerprintInputs.from_dict(last_build).digest()
            run.record("NOOP", ("no relevant input changed",), fingerprint=fingerprint,
                       new_release=installed.release_id, revisions=installed.revisions,
                       details={"build_inputs": last_build})
            return run.result("NOOP", ("no relevant input changed",), check=check.to_dict(), plan=plan.to_dict(),
                              enterprise=enterprise, carried_forward=plan.carried_forward,
                              limitations=_limitations(None, enterprise), previous_release=installed.release_id,
                              new_release=installed.release_id)

    if run.dry_run:
        return run.result("DRY_RUN", plan.reasons, check=check.to_dict(), plan=plan.to_dict(),
                          enterprise=enterprise, carried_forward=plan.carried_forward,
                          limitations=_limitations(None, enterprise))

    return _build_and_activate(run, check, installed, plan)


def _empty_check(run):
    """A check used only to summarise a state that could not be read (no network was used)."""
    return CheckReport(schema=discovery.SCHEMA, statuses=("LOCAL_STATE_INVALID",), sources=(),
                                 new_versions=(), affected_transitions=(), enterprise_freshness="UNKNOWN",
                                 catalog_digest=run.catalog.digest, offline=True, installed_release=None)


def _build_and_activate(run, check, installed, plan) -> UpdateResult:
    home = run.home
    now = run.clock()
    acquisition = acq.acquire(plan, cache_dir=run.cache_dir, token=run.token, offline=run.offline,
                              fetch=run.fetch, transport_for=run.transport_for)
    revisions = {r.source_id: r.revision for r in acquisition.results if r.revision}
    enterprise = _enterprise_summary(check, installed, acquisition, plan.carried_forward)
    base = {"check": check.to_dict(), "plan": plan.to_dict(), "acquisition": acquisition.to_dict(),
            "enterprise": enterprise, "carried_forward": tuple(acquisition.carried_source_ids),
            "limitations": _limitations(None, enterprise)}

    def failed(reason):
        run.record("FAILED", (reason,), revisions=revisions)
        return run.result("FAILED", (reason,), **base)

    if acquisition.blocking is not None:
        sid, status = acquisition.blocking
        return failed(f"FAILED: required source {sid} is {status}; nothing was built")
    if not any(r.status in (acq.ACQUIRED, acq.CARRIED) and r.source_id in _community_ids(plan)
               for r in acquisition.results):
        return failed("FAILED: no community source was acquired or carried; nothing was built")
    pairs = _pairs(run.catalog, plan, acquisition, run.only_pair)
    if not pairs:
        return failed("FAILED: no transition has every source available; nothing was built")

    spec_kind = {spec["source_id"]: spec.get("kind") for spec in acquisition.specs}
    carried_ids = [sid for sid in acquisition.carried_source_ids if sid in spec_kind]
    expected = {sid: installed.snapshot_digests[sid] for sid in carried_ids if sid in installed.snapshot_digests}
    retained = RetainedSnapshotAdapter(home / pl.STAGING_DIR / LABEL / "snapshots", expected)
    prev_dir = _release_dir(home, installed.release_id)
    build_plan = pl.BuildPlan(
        label=LABEL, specs=acquisition.specs, pairs=pairs, base_tree=builtin_handle().root,
        adapters={kind: GitLocalAdapter(kind) for kind in ("GIT_COMMUNITY", "GIT_ENTERPRISE")},
        adapter_by_source={sid: retained for sid in carried_ids}, extract=_extractor(run.toolkit),
        known_detectors=run.toolkit.detectors, created_at=now, checked_on=now[:10], author="update",
        tool_version=__version__, parent_dir=prev_dir, supersede_policy=capability.semantic_supersede_policy(),
        emit_inventory=True, source_meta=acquisition.source_meta, allow_list=load_allow_list(),
        secrets=run.secrets, autofix_prover=autofix.prove_entry)  # automatic FIX rules, offline (addendum F)
    build = pl.run_build(home, build_plan)
    build_summary = {"outcome": build.outcome, "code": build.code, "message": build.message,
                     "release_id": build.release_id, "completeness": build.completeness,
                     "stopped_at": build.stopped_at}
    if build.outcome == "STOPPED" and build.code in GATE_CODES:
        reason = f"BLOCKED: {build.code}: {build.message or ''}".rstrip(": ")
        run.record("BLOCKED", (reason,), revisions=revisions, details={"build_code": build.code})
        return run.result("BLOCKED", (reason,), build=build_summary, **base)
    if build.outcome == "STOPPED":
        return failed(f"FAILED: build stopped at {build.code or 'an unknown step'}: {build.message or ''}".rstrip(": "))
    if build.outcome != "OK" or build.release_id is None:
        return failed("FAILED: the build did not produce an installable release; nothing was installed")

    new_id = build.release_id
    new_dir = home / "releases" / new_id
    base["limitations"] = _limitations(build.completeness, enterprise)
    output = _build_output(home)
    approved = dict(output.get("approved") or {})
    carried_enterprise = [sid for sid in carried_ids if is_enterprise_kind(spec_kind[sid])]
    branches = [spec["branch"] for spec in acquisition.specs if spec["source_id"] in carried_enterprise]
    findings = []
    if carried_enterprise:
        findings = (_enterprise_findings(prev_dir, new_dir, branches) if prev_dir is not None
                    else [{"module": "carried Enterprise", "missing": ["no previous release to compare"]}])
    decision = activation.evaluate(prev_dir, new_dir, completeness=build.completeness, supersede=sorted(approved),
                                   carried_inventory_findings=findings, kb_home=home,
                                   blob_root=home / pl.STAGING_DIR / LABEL / "store")
    if not decision.allowed:
        try:
            activation.block(run.history, decision, previous_release=installed.release_id, new_release=new_id,
                             fingerprint=None, source_revisions=revisions)
        except HistoryError as exc:
            run.history_error = exc.code
        reasons = tuple(f"{entry['code']}: {entry['detail']}" for entry in decision.blocking)
        return run.result("BLOCKED", reasons or ("BLOCKED: activation refused",), build=build_summary,
                          new_release=new_id, release_digest=_digest_of(new_dir), completeness=build.completeness,
                          activation={**decision.to_dict(), "state": "BLOCKED"}, **base)

    meta = _release_meta(new_dir)
    digest, inputs = _build_inputs(meta, run.catalog.digest, new_id)
    changes = _changes(prev_dir, new_dir, approved, installed, acquisition, pairs)
    done = activation.activate_release(home, new_id, history=run.history, previous_release=installed.release_id,
                                       fingerprint=digest, source_revisions=revisions, build_inputs=inputs,
                                       now=now, fault_at=run.fault_at)
    state = done["state"]
    reason = (f"ACTIVE: release {new_id}" if state == "ACTIVE"
              else f"{state}: {done.get('reason') or 'activation did not complete'}")
    return run.result(state, (reason,), build=build_summary, new_release=new_id,
                      release_digest=meta.get("release_digest"), completeness=build.completeness,
                      activation={**decision.to_dict(), "state": state, "reason": done.get("reason"),
                                  "history_error": done.get("history_error")},
                      changes=changes if state == "ACTIVE" else None, **base)


def _community_ids(plan) -> set:
    return {src.source_id for src in plan.sources if src.edition == "community"}


def _digest_of(release_dir: Path):
    try:
        return _release_meta(release_dir).get("release_digest")
    except (OSError, ValueError, AttributeError):
        return None


def _pointer_id(home: Path):
    try:
        current = read_active(home)
    except Exception:  # an unreadable pointer is reported as unknown, never guessed
        return "unreadable"
    return None if current is None else current["release_id"]


def _guarded(run: _Run) -> UpdateResult:
    try:
        return _execute(run)
    except Exception as exc:  # any failure after the lock is FAILED, with the reason scrubbed
        reasons = [run.clean(f"FAILED: {type(exc).__name__}: {exc}")[:_MAX_REASON]]
        if not run.dry_run and _pointer_id(run.home) != run.prev_id:
            reasons.append("the active pointer no longer names the previous release; check the status")
        run.record("FAILED", (reasons[0],))
        return run.result("FAILED", reasons)


def run_update(kb_home, *, toolkit, catalog=None, offline=False, dry_run=False, require_enterprise=False,
               only_pair=None, token=None, ls_remote=None, fetch=None, transport_for=None, clock=None,
               cache_dir=None, fault_at=None) -> UpdateResult:
    """Run one knowledge update of `kb_home`. See the module docstring for the order of work and the outcomes.

    `toolkit` is the composed `ExtractToolkit` (None is refused as BLOCKED). `catalog` defaults to the shipped catalog.
    `token` is a `credentials.Token` the caller resolved; this function never reads the environment for it. `ls_remote`,
    `fetch` and `transport_for` are injection seams for tests; None selects the production `remote_git` functions.
    `fault_at` names an activation boundary to fail (tests only).
    """
    if fault_at is not None and fault_at not in FAULT_POINTS:
        raise ValueError(f"unknown fault point {fault_at!r}")
    if only_pair is not None and (not isinstance(only_pair, (tuple, list)) or len(only_pair) != 2):
        raise ValueError("only_pair must be a (from_major, to_major) pair such as ('16', '17') or None")
    home = Path(kb_home)
    clock = utc_now if clock is None else clock
    cache = Path(cache_dir) if cache_dir is not None else home / UPDATES_DIR / "cache"
    run = _Run(home, offline=offline, dry_run=dry_run, require_enterprise=require_enterprise, only_pair=only_pair,
               token=token, ls_remote=ls_remote, fetch=fetch, transport_for=transport_for, clock=clock,
               cache_dir=cache, fault_at=fault_at, catalog=None, toolkit=toolkit)
    if toolkit is None:
        return run.result("BLOCKED", ("extract toolkit not attached",))
    try:
        run.catalog = load_catalog() if catalog is None else catalog
    except CatalogError as exc:
        return run.result("FAILED", (f"FAILED: catalog invalid ({exc.code})",))
    if dry_run:
        return _guarded(run)
    try:
        with _update_lock(home, LOCK_WAIT_SECONDS):
            return _guarded(run)
    except _LockBusy:
        return run.result("BLOCKED", ("CONCURRENT_UPDATE: another update holds the update lock; nothing was changed",))
    except _LockError as exc:
        return run.result("BLOCKED", (f"LOCK_UNAVAILABLE: {run.clean(str(exc))}",))
