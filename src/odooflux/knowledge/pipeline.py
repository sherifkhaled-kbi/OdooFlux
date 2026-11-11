"""Release build pipeline (feature 011; contracts/release-lifecycle.md "Build steps"; REQ-KAP-029, 030, 045).

CORE module: stdlib and core imports only. Adapters arrive as parameters on `BuildPlan` (the source adapters, the
extract callable, the bindable detector mapping), attached by the CLI composition root. No importlib, no subprocess,
no network, no AI call: the AI proposal is not part of this run (AI stays off, D-08).

`run_build(home, plan, ...)` runs the seventeen contract steps in order under `<home>/staging/<label>/`:

- Each step writes `steps/NN-name.json` with `input_digest`, `output_digest`, `status` (OK, SKIPPED or FAILED) and the
  step output. The input digest chains the plan fingerprint, the step's probe (for example the snapshot digests on
  disk) and the previous step's output digest.
- Resume reuses a step only when its recorded input digest matches. The first changed or missing input re-runs that
  step and every later step (the cascade). `from_step` forces a re-run from N onwards.
- `dry_run` computes the same decisions without creating anything (not even the kb-home layout).
- A stop (a StepStop, or any other exception recorded as STEP_ERROR) records FAILED and ends the run. The audit log
  gets `build_started` and `build_completed` (with the outcome); the release actions go through `release/audit.py`.
- Destructive changes against the parent release (`release/diff.py`) need the plan's `supersede` ids, or the build
  stops. `supersede` is a recorded flag, not an authenticated approval (FE-1, deferred).
  A `supersede_policy` (e.g. `update.capability.semantic_supersede_policy`) may approve removals in addition; its
  approvals are recorded in the build output and in the `release_installed` audit entry.

Pairs may carry a `key` (default: the step). Ledgers and accounting files are named by the key, so pairs that share a
step (Community and Enterprise for one transition) need distinct keys. `adapter_by_source` overrides the kind adapter
for one source (a retained snapshot). `emit_inventory` writes `knowledge/inventory/<branch>.json`. An internal or
Enterprise-derived release is never exported, so step 13 is skipped for it.

The release is built in `<staging>/release` (knowledge tree under `knowledge/`, provenance, snapshots, coverage).
Its completeness comes only from the coverage gates. A FAILED completeness stops the build (step 12) unless
`allow_failed` is set, and then the release stays STAGED: it is never published, never exported and never reported
complete. A built release is INSTALLED, never ACTIVE.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.sources import FAILURE_CODES, RegistryError, SourceRegistry, is_enterprise_kind
from odooflux.knowledge import autofix
from odooflux.knowledge.authoring import conflicts
from odooflux.knowledge.authoring.checks import authoring_findings
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.candidates.templates import load_templates
from odooflux.knowledge.checks import validate_knowledge
from odooflux.knowledge.coverage import manifest as cm
from odooflux.knowledge.coverage.gates import PARTIAL_ALLOWED, decide
from odooflux.knowledge.ledger.ledger import Ledger
from odooflux.knowledge.loader import is_builtin_path, load_knowledge
from odooflux.knowledge.update import inventory
from odooflux.knowledge.package.builder import export_package
from odooflux.knowledge.package.confidentiality import assess
from odooflux.knowledge.package.validate import validate_package
from odooflux.knowledge.release.audit import KbAudit
from odooflux.knowledge.release.canonical import canonical_bytes, digest_obj, write_compact_json_file, write_json_file
from odooflux.knowledge.release.diff import diff_releases
from odooflux.knowledge.release.manifest import verify_release_tree, write_release_manifest
from odooflux.knowledge.release.model import KnowledgeReleaseError, ReleaseState
from odooflux.knowledge.release.provenance import SNAPSHOT_DIRNAME, sources_meta, verify_provenance, write_provenance
from odooflux.knowledge.release.safety import FIX_ENABLED, fix_row_trusted, is_shipped_builtin_rule, \
    load_provenance_index, rule_gate_context
from odooflux.knowledge.release.store import KbLock, ensure_layout, set_release_state
from odooflux.utils.redaction import redact_text, scrub

__all__ = ["STEP_NAMES", "Step", "StepStop", "BuildPlan", "BuildResult", "plan_fingerprint", "run_build",
           "destructive_unapproved", "REAL_STEPS", "STAGING_DIR", "DATA_DIRS", "DATA_FILES"]

STEP_NAMES = ("acquire", "verify", "extract", "classify", "evidence", "candidates", "schema-validate",
              "dup-conflict", "rule-tests", "coverage", "gates", "build-package", "validate-package",
              "publish-local", "export", "import-activate", "provenance")
STAGING_DIR = "staging"
RELEASES_DIR = "releases"
DATA_DIRS = ("evidence", "compatibility", "official_sources", "schemas")  # schemas: note 69 (COMPLETE tree)
DATA_FILES = ("gaps.json",)
LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
PAIR_KEY = re.compile(r"[A-Za-z0-9._-]{1,48}")  # fullmatch; a pair key names its ledger and accounting files
INVENTORY_VERSION = re.compile(r"[A-Za-z0-9._-]{1,32}")  # a source branch names its inventory file
RUN_OK, RUN_SKIPPED, RUN_FAILED = "OK", "SKIPPED", "FAILED"
TOOL_SCHEMA_VERSIONS = {"evidence": "1", "rule_metadata": "1"}
_PUBLIC_TREE = "https://github.com/{repository}/tree/{revision}"


class StepStop(Exception):
    """A stop rule fired. `code` is a closed identifier, `message` must not echo secrets (masked by the runner)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Step:
    number: int
    name: str
    run: object  # callable(ctx) -> dict (the step output; a "status" key of SKIPPED marks a skipped step)
    probe: object = None  # callable(ctx) -> JSON value describing the step's current on-disk inputs, or None


@dataclass
class BuildPlan:
    label: str
    specs: list = field(default_factory=list)  # source spec dicts (DECLARED records, validated by SourceRegistry)
    pairs: list = field(default_factory=list)  # [{"step": "16-17", "from": source_id, "to": source_id}]
    base_tree: object = None  # shipped knowledge tree (read only), data dirs are copied into the staging tree
    adapters: dict = field(default_factory=dict)  # kind -> adapter with snapshot(spec, store, created_at=...)
    extract: object = None  # callable(from_snap, to_snap, step, store) -> (drafts, accounting document)
    known_detectors: dict = field(default_factory=dict)  # detector ref -> bindable callable (verified templates)
    created_at: str = "2026-01-01T00:00:00Z"
    checked_on: str = "2026-01-01"
    author: str = "pipeline"
    tool_version: str = "0.0.0"
    marker: str = ""  # test hook for probes; not part of the fingerprint
    parent_dir: object = None  # installed parent release directory, or None
    supersede: tuple = ()  # approved removal ids (recorded flag)
    secrets: tuple = ()
    allow_list: object = None
    source_meta: dict = field(default_factory=dict)  # source_id -> {"repository": "owner/name", "committed": date?}
    # Pair keys: a pair may carry `key` (default = its step). Pairs that share a step need distinct keys.
    adapter_by_source: dict = field(default_factory=dict)  # source_id -> adapter, consulted before the kind adapter
    emit_inventory: bool = False  # write release/knowledge/inventory/<branch>.json (in the fingerprint when True)
    # callable(diff, parent_dir, new_release_dir) -> {id: reason}: removals it approves count as supersede ids. Its
    # `policy_name` is in the fingerprint and the approvals are in the audit trail. None keeps today's behaviour.
    supersede_policy: object = None
    # Automatic FIX pipeline (feature 012, Addendum F3): callable(record, store) -> proof, or None. None means no FIX-PENDING
    # rule is ever proposed in this build (every change keeps its detect-only candidate). Its `policy_name` is in the
    # fingerprint, so a resumed run never reuses candidates made under another prover.
    autofix_prover: object = None


@dataclass
class BuildResult:
    outcome: str  # PLAN, OK, STOPPED or FAILED
    rows: list = field(default_factory=list)
    stopped_at: int = None
    code: str = None
    message: str = None
    release_id: str = None
    completeness: str = None
    dev_only: bool = False


@dataclass
class Ctx:
    home: Path
    workdir: Path
    plan: BuildPlan
    allow_failed: bool
    audit: object = None
    outputs: dict = field(default_factory=dict)

    def path(self, *parts) -> Path:
        return self.workdir.joinpath(*parts)

    def write(self, parts, obj) -> None:
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(target, obj)

    def read(self, parts):
        return json.loads(self.path(*parts).read_text(encoding="utf-8"))

    def tree(self) -> Path:
        return self.workdir / "release" / "knowledge"

    def release_dir(self) -> Path:
        published = self.outputs.get("publish-local", {}).get("path")
        return self.home / published if published else self.workdir / "release"


def _mask(text, plan) -> str:
    return redact_text(scrub(str(text), plan.secrets))


def pair_key(pair: dict) -> str:
    """The key that names a pair's ledger and accounting files: `key` when given, else the step (NN-NN)."""
    return pair.get("key", pair["step"])


def _pair_keys(plan: BuildPlan) -> list:
    """Every pair key, validated. A key is unique across pairs, so two pairs with one step must have distinct keys."""
    keys = [pair_key(pair) for pair in plan.pairs]
    for key in keys:
        if not isinstance(key, str) or not PAIR_KEY.fullmatch(key):
            raise ValueError("pair key must be 1-48 characters from A-Z a-z 0-9 . _ -")
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ValueError(f"duplicate pair key(s) {', '.join(duplicated)}: pairs that share a step need distinct keys")
    return keys


def plan_fingerprint(plan: BuildPlan, allow_failed: bool = False) -> str:
    """Digest of everything that defines the run. A change here invalidates every step (pinned config and revisions).
    `pairs` carries a `key` only when one was given, and `emit_inventory` is recorded only when it is True, so a plan
    that uses neither keeps its earlier fingerprint."""
    _pair_keys(plan)
    body = {
        "label": plan.label, "specs": plan.specs, "pairs": plan.pairs, "created_at": plan.created_at,
        "checked_on": plan.checked_on, "author": plan.author, "tool_version": plan.tool_version,
        "supersede": sorted(plan.supersede), "parent": plan.parent_dir.name if plan.parent_dir else None,
        "allow_failed": bool(allow_failed), "source_meta": plan.source_meta,
    }
    if plan.emit_inventory:
        body["emit_inventory"] = True
    if plan.supersede_policy is not None:
        body["supersede_policy"] = _policy_name(plan.supersede_policy)
    if plan.autofix_prover is not None:
        body["autofix_prover"] = _policy_name(plan.autofix_prover, "autofix_prover")
    return digest_obj(body)


def _policy_name(policy, label: str = "supersede_policy") -> str:
    name = getattr(policy, "policy_name", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{label} must carry a non-empty string policy_name")
    return name


def destructive_unapproved(entries: list, supersede) -> list:
    """Ids of destructive diff entries (removed rules or VERIFIED evidence) that the approval list does not name."""
    approved = set(supersede or ())
    return sorted({e["id"] for e in entries if e.get("destructive") and e["id"] not in approved})


def _record_path(ctx: Ctx, number: int, name: str) -> Path:
    return ctx.path("steps", f"{number:02d}-{name}.json")


def _read_record(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _probe_value(ctx: Ctx, step: Step):
    return step.probe(ctx) if step.probe is not None else None


def _input_digest(ctx: Ctx, step: Step, fingerprint: str, upstream) -> str:
    return digest_obj({"plan": fingerprint, "step": step.name, "upstream": upstream,
                       "probe": _probe_value(ctx, step)})


def _decide_actions(ctx: Ctx, steps, fingerprint, from_step):
    """(step, action, input_digest) for each step, read-only: REUSE when a recorded OK/SKIPPED result matches."""
    actions, upstream, cascade = [], None, False
    for step in steps:
        if from_step is not None and step.number >= from_step:
            cascade = True
        in_digest = _input_digest(ctx, step, fingerprint, upstream)
        rec = _read_record(_record_path(ctx, step.number, step.name))
        if not cascade and rec and rec.get("input_digest") == in_digest and rec.get("status") in (RUN_OK, RUN_SKIPPED):
            actions.append((step, "REUSE", in_digest))
            upstream = rec.get("output_digest")
            continue
        cascade = True
        actions.append((step, "RUN", in_digest))
        upstream = None  # unknown until it runs; the cascade makes every later step RUN anyway
    return actions


def _execute(ctx: Ctx, steps, fingerprint, from_step) -> BuildResult:
    rows, upstream, cascade = [], None, False
    for step in steps:
        if from_step is not None and step.number >= from_step:
            cascade = True
        in_digest = _input_digest(ctx, step, fingerprint, upstream)
        path = _record_path(ctx, step.number, step.name)
        rec = _read_record(path)
        if not cascade and rec and rec.get("input_digest") == in_digest and rec.get("status") in (RUN_OK, RUN_SKIPPED):
            ctx.outputs[step.name] = rec.get("output") or {}
            upstream = rec.get("output_digest")
            rows.append({"number": step.number, "name": step.name, "status": rec["status"], "action": "REUSE"})
            continue
        cascade = True  # changed or missing input: this step and every later step run again
        code, message, output, status = None, None, {}, RUN_OK
        try:
            output = step.run(ctx) or {}
            status = output.get("status", RUN_OK)
        except StepStop as exc:
            status, code, message = RUN_FAILED, exc.code, _mask(exc.message, ctx.plan)
        except Exception as exc:  # any step error is a recorded failure, never a silent pass
            status, code, message = RUN_FAILED, "STEP_ERROR", _mask(f"{type(exc).__name__}: {exc}", ctx.plan)
        if status == RUN_FAILED:
            output = {}
        record = {"step": step.number, "name": step.name, "status": status, "input_digest": in_digest,
                  "output_digest": digest_obj(output), "output": output, "code": code, "message": message}
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(path, record)
        rows.append({"number": step.number, "name": step.name, "status": status, "action": "RUN"})
        if status == RUN_FAILED:
            return BuildResult(outcome="STOPPED", rows=rows, stopped_at=step.number, code=code, message=message)
        ctx.outputs[step.name] = output
        upstream = record["output_digest"]
    completeness = ctx.outputs.get("build-package", {}).get("completeness")
    release_id = ctx.outputs.get("build-package", {}).get("release_id")
    dev_only = bool(ctx.outputs.get("build-package", {}).get("dev_only"))
    outcome = "FAILED" if completeness == "FAILED" else "OK"
    return BuildResult(outcome=outcome, rows=rows, release_id=release_id, completeness=completeness,
                       dev_only=dev_only)


def run_build(home, plan: BuildPlan, *, steps=None, dry_run: bool = False, from_step=None,
              allow_failed: bool = False) -> BuildResult:
    """Run (or plan, with `dry_run`) the build. `steps` defaults to the real pipeline (REAL_STEPS)."""
    steps = list(REAL_STEPS if steps is None else steps)
    if not LABEL.match(plan.label or ""):
        raise ValueError("build label must be 1-64 characters from A-Z a-z 0-9 . _ -")
    if from_step is not None and not 1 <= int(from_step) <= len(steps):
        raise ValueError(f"--from-step must be between 1 and {len(steps)}")
    home = Path(home)
    workdir = home / STAGING_DIR / plan.label
    if is_builtin_path(workdir):
        raise ValueError("refusing to build inside the shipped knowledge tree")
    fingerprint = plan_fingerprint(plan, allow_failed)
    ctx = Ctx(home=home, workdir=workdir, plan=plan, allow_failed=allow_failed)
    if dry_run:
        rows = [{"number": step.number, "name": step.name, "action": action}
                for step, action, _ in _decide_actions(ctx, steps, fingerprint, from_step)]
        return BuildResult(outcome="PLAN", rows=rows)
    ensure_layout(home)
    with KbLock(home):
        audit = KbAudit(home, plan.label, secrets=plan.secrets)
        ctx.audit = audit
        audit.record("build_started", target=plan.label, outcome="ok", details={"fingerprint": fingerprint})
        # Created 0700 (a new directory only): Enterprise blobs may be retained here, and they are never part of a
        # release or package. The workdir is stable per label, so the blob store persists across runs.
        workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            result = _execute(ctx, steps, fingerprint, from_step)
        except (OSError, KnowledgeReleaseError, ValueError) as exc:
            result = BuildResult(outcome="STOPPED", stopped_at=None, code="STEP_ERROR",
                                 message=_mask(f"{type(exc).__name__}: {exc}", plan))
        audit.record("build_completed", target=plan.label,
                     outcome="ok" if result.outcome == "OK" else "failed",
                     details={"run_outcome": result.outcome, "completeness": result.completeness,
                              "release_id": result.release_id, "code": result.code})
    return result


# --- real steps -------------------------------------------------------------------------------------------------

def _load_snapshot(ctx: Ctx, source_id: str) -> dict:
    return json.loads((ctx.path("snapshots", f"{source_id}.json")).read_text(encoding="utf-8"))


def _spec_for(ctx: Ctx, source_id: str) -> dict:
    for spec in ctx.plan.specs:
        if spec["source_id"] == source_id:
            return spec
    raise StepStop("UNKNOWN_SOURCE", f"{source_id} is not in the source list")


def _records(ctx: Ctx) -> list:
    return ctx.read(("sources.json",))


def _snapshot_probe(ctx: Ctx):
    folder = ctx.path("snapshots")
    if not folder.is_dir():
        return {}
    return {p.name: digest_obj(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))}


def _replay_registry(ctx: Ctx, records: list) -> SourceRegistry:
    """Rebuild the status machine from the specs and the recorded outcomes, so transitions stay the machine's."""
    registry = SourceRegistry(allow_list=ctx.plan.allow_list)
    for spec in ctx.plan.specs:
        registry.add(spec)
    for rec in records:
        if rec["status"] == "RETRIEVED":
            registry.transition(rec["source_id"], "RETRIEVED", checksum=rec["checksum"],
                                retrieved_at=rec["retrieved_at"])
        elif rec["status"] == "FAILED":
            registry.transition(rec["source_id"], "FAILED", failure_reason=rec["failure_reason"])
    return registry


def _acquire(ctx: Ctx) -> dict:
    plan = ctx.plan
    registry = SourceRegistry(allow_list=plan.allow_list)
    for spec in plan.specs:
        registry.add(spec)
    store = BlobStore(ctx.path("store"))
    for spec in plan.specs:
        sid = spec["source_id"]
        adapter = plan.adapter_by_source[sid] if sid in plan.adapter_by_source else plan.adapters.get(spec.get("kind"))
        try:
            if adapter is None:
                raise SourceError("IO_ERROR", sid, f"no adapter for kind {spec.get('kind')}")
            snap = adapter.snapshot(spec, store, created_at=plan.created_at)
        except SourceError as exc:
            code = exc.code if exc.code in FAILURE_CODES else "IO_ERROR"
            registry.transition(sid, "FAILED", failure_reason=f"{code}: {_mask(exc.message, plan)}")
            ctx.audit.record("source_failed", target=sid, outcome="failed",
                             details={"code": code, "required": bool(spec.get("required"))})
            if spec.get("required"):
                ctx.write(("sources.json",), registry.sources())
                raise StepStop("SOURCE_REQUIRED_FAILED", f"{sid}: {code}")
            continue
        ctx.write(("snapshots", f"{sid}.json"), snap)
        registry.transition(sid, "RETRIEVED", checksum=snap["snapshot_digest"], retrieved_at=plan.created_at)
        ctx.audit.record("source_acquired", target=sid, outcome="ok",
                         details={"snapshot_id": snap["snapshot_id"], "files": len(snap["entries"])})
    ctx.write(("sources.json",), registry.sources())
    return {"sources": [{"source_id": r["source_id"], "status": r["status"]} for r in registry.sources()]}


def _verify(ctx: Ctx) -> dict:
    records = _records(ctx)
    registry = _replay_registry(ctx, records)
    store = BlobStore(ctx.path("store"))
    for rec in records:
        if rec["status"] != "RETRIEVED":
            continue
        sid = rec["source_id"]
        snap = _load_snapshot(ctx, sid)
        try:
            for entry in snap["entries"]:
                store.get(entry["sha256"])  # verify-on-read
        except SourceError as exc:
            raise StepStop("CHECKSUM_MISMATCH", f"{sid}: {exc.code}") from None
        recomputed = digest_obj({"source_id": sid, "revision": snap["revision"], "entries": snap["entries"]})
        if recomputed != snap["snapshot_digest"] or rec["checksum"] != recomputed:
            raise StepStop("CHECKSUM_MISMATCH", f"{sid}: snapshot digest does not recompute")
        registry.transition(sid, "VERIFIED")
    ctx.write(("sources.json",), registry.sources())
    for spec in ctx.plan.specs:
        if spec.get("required") and registry.get(spec["source_id"])["status"] != "VERIFIED":
            raise StepStop("SOURCE_REQUIRED_NOT_VERIFIED", spec["source_id"])
    return {"verified": sorted(r["source_id"] for r in registry.sources() if r["status"] == "VERIFIED")}


def _verified(ctx: Ctx, source_id: str) -> bool:
    return any(r["source_id"] == source_id and r["status"] == "VERIFIED" for r in _records(ctx))


def _extract(ctx: Ctx) -> dict:
    if ctx.plan.extract is None:
        raise StepStop("NO_EXTRACTOR", "the run was started without an extract callable")
    out = []
    for pair in ctx.plan.pairs:
        if not (_verified(ctx, pair["from"]) and _verified(ctx, pair["to"])):
            raise StepStop("PAIR_SOURCE_NOT_VERIFIED", f"step {pair['step']}")
        from_snap, to_snap = _load_snapshot(ctx, pair["from"]), _load_snapshot(ctx, pair["to"])
        drafts, document = ctx.plan.extract(from_snap, to_snap, pair["step"], BlobStore(ctx.path("store")))
        ledger = Ledger.create(pair["step"], from_snap, to_snap, drafts, clock=lambda: ctx.plan.created_at)
        ctx.path("ledgers").mkdir(parents=True, exist_ok=True)
        ledger.save(ctx.path("ledgers", f"{pair_key(pair)}.json"))
        ctx.write(("accounting", f"{pair_key(pair)}.json"), document)
        out.append({"step": pair["step"], "changes": len(ledger.records()), "unresolved": len(ledger.unresolved())})
    return {"pairs": out}


def _classify(ctx: Ctx) -> dict:
    counts: dict = {}
    for pair in ctx.plan.pairs:
        for change in Ledger.load(ctx.path("ledgers", f"{pair_key(pair)}.json")).records():
            counts[change["class"]] = counts.get(change["class"], 0) + 1
    return {"classes": {k: counts[k] for k in sorted(counts)}}


def _stage_tree(ctx: Ctx) -> Path:
    tree = ctx.tree()
    if tree.exists():
        return tree
    base = Path(ctx.plan.base_tree)
    tree.mkdir(parents=True)
    for name in DATA_DIRS:
        shutil.copytree(base / name, tree / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in DATA_FILES:
        shutil.copyfile(base / name, tree / name)
    return tree


def _evidence(ctx: Ctx) -> dict:
    tree = _stage_tree(ctx)
    revisions_path = tree / "official_sources" / "revisions.json"
    revisions = json.loads(revisions_path.read_text(encoding="utf-8"))
    added = []
    for rec in _records(ctx):
        if rec["status"] != "VERIFIED":
            continue
        spec = _spec_for(ctx, rec["source_id"])
        meta = _meta_for(ctx, rec["source_id"])
        entry = {"repository": meta["repository"], "branch": spec["branch"], "revision": rec["revision"],
                 "committed": meta.get("committed", ctx.plan.checked_on), "pinned_on": ctx.plan.checked_on,
                 "tags": []}
        if entry not in revisions:
            revisions.append(entry)
            added.append(rec["revision"])
    write_json_file(revisions_path, revisions)
    output = {"revisions_catalogued": added}
    if ctx.plan.emit_inventory:
        output["inventory"] = _emit_inventory(ctx, tree)
    return output


def _emit_inventory(ctx: Ctx, tree: Path) -> list:
    """One module inventory per source branch (`inventory/<branch>.json`), built from the VERIFIED snapshots of this run
    (carried ones included). Enterprise kinds keep module facts only (inventory.build_part). Parts of one branch are
    merged; a module declared by two sources is recorded as a conflict, never resolved."""
    store = BlobStore(ctx.path("store"))
    by_branch: dict = {}
    for rec in _records(ctx):
        if rec["status"] == "VERIFIED":
            spec = _spec_for(ctx, rec["source_id"])
            by_branch.setdefault(spec["branch"], []).append(spec)
    written = []
    for branch in sorted(by_branch):
        if not INVENTORY_VERSION.fullmatch(str(branch)):
            raise StepStop("INVENTORY_BRANCH_INVALID", f"branch {branch!r} cannot name an inventory file")
        parts = [inventory.build_part(_load_snapshot(ctx, spec["source_id"]), store, source_id=spec["source_id"],
                                      confidentiality="enterprise" if is_enterprise_kind(spec.get("kind"))
                                      else "public")
                 for spec in sorted(by_branch[branch], key=lambda item: item["source_id"])]
        document = inventory.merge(parts)
        findings = inventory.verify_inventory(document)
        if findings:
            raise StepStop("INVENTORY_INVALID",
                           f"{branch}: {len(findings)} finding(s); first {_mask(findings[0], ctx.plan)}")
        (tree / "inventory").mkdir(parents=True, exist_ok=True)
        write_json_file(tree / "inventory" / f"{branch}.json", document)
        written.append(f"inventory/{branch}.json")
    return written


def _pair_sides(ctx: Ctx, pair: dict) -> dict:
    """The two sides of a pair as the automatic FIX prover reads them (addendum F3): identity, verification, the file
    digests of the snapshot and the evidence source. Nothing here is trusted by itself; the proof re-reads the blobs."""
    sides = {}
    for side in ("from", "to"):
        sid = pair[side]
        snap = _load_snapshot(ctx, sid)
        source = _candidate_source(ctx, _spec_for(ctx, sid))
        sides[side] = {"source_id": sid, "snapshot_id": snap["snapshot_id"], "revision": snap["revision"],
                       "verified": _verified(ctx, sid), "official": source["official"],
                       "entries": {entry["path"]: entry["sha256"] for entry in snap["entries"]}, "source": source}
    return sides


def _pinned_ledger(ctx: Ctx, key: str) -> Ledger:
    body = Ledger.load(ctx.path("ledgers", f"{key}.json")).to_dict()
    entries = {entry["change_id"]: entry for entry in body["entries"]}
    return Ledger(body["step"], body["from"], body["to"], entries, clock=lambda: ctx.plan.created_at)


def _meta_for(ctx: Ctx, source_id: str) -> dict:
    meta = ctx.plan.source_meta.get(source_id)
    if not meta or not meta.get("repository"):
        raise StepStop("SOURCE_META_MISSING", f"{source_id}: plan.source_meta needs a repository")
    return meta


def _candidate_source(ctx: Ctx, spec: dict) -> dict:
    repository = _meta_for(ctx, spec["source_id"])["repository"]
    url = _PUBLIC_TREE.format(repository=repository, revision=spec["revision"])
    return {"source_id": spec["source_id"], "official": spec.get("official") is True, "url": url,
            "repository": repository, "revision": spec["revision"], "branch": spec["branch"]}


class _PendingEvidence:
    """The evidence rows waiting in `candidates/evidence/`, read once. Answers each candidate with the rows it cites,
    in file-name order (the order the folder listing gave), and forgets rows as they are consumed."""

    def __init__(self, folder: Path):
        self._rows = {}
        for path in sorted(folder.glob("EV-*.json")) if folder.is_dir() else []:
            row = json.loads(path.read_text(encoding="utf-8"))
            self._rows[path.stem] = row

    def rows(self, evidence_ids) -> list:
        return [self._rows[eid] for eid in sorted(set(evidence_ids))
                if eid in self._rows and self._rows[eid].get("id") == eid]

    def drop(self, evidence_ids) -> None:
        for eid in evidence_ids:
            self._rows.pop(eid, None)


def _candidates(ctx: Ctx) -> dict:
    tree = _stage_tree(ctx)
    store = tree / "candidates"
    templates = load_templates(known_detectors=ctx.plan.known_detectors)
    summary = {"candidates": 0, "accepted": 0, "refused": [], "evidence": 0, "conflicts": 0}
    for pair in ctx.plan.pairs:
        ledger = _pinned_ledger(ctx, pair_key(pair))
        # Automatic FIX rules first: a change they settle gets no ordinary detect-only candidate (Addendum F3 step 3).
        sides = _pair_sides(ctx, pair) if ctx.plan.autofix_prover is not None else None
        fix = autofix.plan_pair(ledger, tree, prove=ctx.plan.autofix_prover, store=ctx.path("store"),
                                author=ctx.plan.author, at=ctx.plan.created_at, sources=sides,
                                checked_on=ctx.plan.checked_on)
        _note_fix(summary, fix)
        result = gen.generate(ledger, tree_root=tree, source=_candidate_source(ctx, _spec_for(ctx, pair["to"])),
                              checked_on=ctx.plan.checked_on, templates=templates,
                              known_detectors=ctx.plan.known_detectors,
                              skip_change_ids={item["change_id"] for item in fix["accepted"]})
        held_back = [link for link in result["linked"] if not link.get("generated")]
        if held_back:
            # Links to a rule this build did not generate are withheld: no disposition, no evidence, no citation.
            withheld_changes = {link["change_id"] for link in held_back}
            withheld_ids = {eid for link in held_back for eid in link["evidence_ids"]}
            result["dispositions"] = [d for d in result["dispositions"] if d["change_id"] not in withheld_changes]
            result["evidence"] = [r for r in result["evidence"] if r["id"] not in withheld_ids]
            summary.setdefault("skipped_links", []).extend(
                {"change_id": link["change_id"], "reason": gen.LINKED_NOT_GENERATED,
                 "rule_id": link["rule_ids"][0], "origin": link.get("origin")} for link in held_back)
            result["linked"] = [link for link in result["linked"] if link.get("generated")]
        gen.apply_dispositions(ledger, result, tree_root=tree)
        (store / "evidence").mkdir(parents=True, exist_ok=True)
        for record in result["evidence"]:
            write_json_file(store / "evidence" / f"{record['id']}.json", record)
        by_id = {record["id"]: record for record in result["evidence"]}
        for link in result["linked"]:
            ev_id = link["evidence_ids"][0]
            try:
                acc.ship_linked_evidence(tree, link["rule_ids"][0], by_id[ev_id], author=ctx.plan.author,
                                         at=ctx.plan.created_at)
            except acc.AcceptError as exc:
                raise StepStop("LINKED_EVIDENCE_REFUSED", _mask(f"{link['change_id']}: {exc}", ctx.plan)) from None
            (store / "evidence" / f"{ev_id}.json").unlink(missing_ok=True)
            summary["linked"] = summary.get("linked", 0) + 1
        for cand in result["candidates"]:
            write_json_file(store / f"{cand['candidate_id']}.json", cand)
        if result["conflicts"]:
            conflicts.write_conflicts(store, result["conflicts"])
        summary["candidates"] += len(result["candidates"])
        summary["evidence"] += len(result["evidence"])
        summary["conflicts"] += len(result["conflicts"])
        pending = _PendingEvidence(store / "evidence")  # read once; the loop below used to re-read it per candidate
        for cand in result["candidates"]:
            if cand.get("status") != "PROPOSED":
                continue
            evidence_ids = set(cand.get("rule", {}).get("evidence") or [])
            try:
                acc.accept(tree, cand, ledger=ledger, evidence=pending.rows(evidence_ids),
                           author=ctx.plan.author, at=ctx.plan.created_at)
            except acc.AcceptError as exc:
                summary["refused"].append({"candidate_id": cand["candidate_id"], "code": str(exc)[:60]})
                continue
            write_json_file(store / f"{cand['candidate_id']}.json", cand)
            for eid in evidence_ids:
                (store / "evidence" / f"{eid}.json").unlink(missing_ok=True)
            pending.drop(evidence_ids)
            summary["accepted"] += 1
        ledger.save(ctx.path("ledgers", f"{pair_key(pair)}.json"))
    return summary


def _note_fix(summary: dict, fix: dict) -> None:
    """Record the FIX-PENDING rules and the coded refusals of one pair. Keys appear only when there is something to say,
    so a build with no automatic FIX rule keeps its earlier summary shape."""
    if fix["accepted"]:
        summary.setdefault("autofix_pending", []).extend(item["rule_id"] for item in fix["accepted"])
    if fix["refused"]:
        summary.setdefault("autofix_refused", []).extend(fix["refused"])


def _schema_validate(ctx: Ctx) -> dict:
    findings = validate_knowledge(load_knowledge(_stage_tree(ctx)))
    errors = [f for f in findings if f.severity == "ERROR"]
    if errors:
        raise StepStop("SCHEMA_INVALID", f"{len(errors)} error(s); first {_mask(errors[0].line(), ctx.plan)}")
    return {"errors": 0, "warnings": len(findings) - len(errors)}


def _dup_conflict(ctx: Ctx) -> dict:
    findings = authoring_findings(load_knowledge(_stage_tree(ctx)))
    errors = [f for f in findings if f.severity == "ERROR"]
    if errors:
        raise StepStop("AUTHORING_INVALID", f"{len(errors)} error(s); first {_mask(errors[0].line(), ctx.plan)}")
    return {"errors": 0, "warnings": len(findings)}


def _rule_rows(tree: Path) -> list:
    rows = []
    for path in sorted((tree / "compatibility").glob("*.rules.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    return sorted(rows, key=lambda row: row["id"])


def _parent_rules(ctx: Ctx) -> dict:
    if ctx.plan.parent_dir is None:
        return {}
    parent_tree = Path(ctx.plan.parent_dir) / "knowledge"
    return {row["id"]: row for row in _rule_rows(parent_tree)} if parent_tree.is_dir() else {}


def _fix_trust_findings(tree: Path) -> list:
    """Findings for every FIX_ENABLED row of the staged tree that the loader's trust predicate refuses. Byte-identical
    shipped rows are skipped, as the loader skips them. A row without a certification record gets exactly the gate 1 to 5
    findings that `safety.fix_gate_findings` gives, so the build gate is unchanged for such rows. A row whose record is
    invalid or forged fails here (SAFETY_NOT_VERIFIED at G-SAFE)."""
    kb = load_knowledge(tree)
    index = load_provenance_index(tree)
    snapshot_dir = tree.resolve().parent / "snapshots"
    context = rule_gate_context(kb)
    findings = []
    for rule in kb.rules:
        if not isinstance(rule, dict) or rule.get("maturity") != FIX_ENABLED or is_shipped_builtin_rule(rule):
            continue
        evidence_rows = [kb.evidence[eid] for eid in rule.get("evidence") or []
                         if isinstance(eid, str) and eid in kb.evidence]
        trusted, found = fix_row_trusted(rule, tree, evidence_rows, index, kb=kb, snapshot_dir=snapshot_dir,
                                         context=context)
        if not trusted:
            findings += found
    return findings


def _pending_row_findings(tree: Path, rule_id: str) -> list:
    return [finding for finding in _fix_trust_findings(tree) if finding["rule_id"] == rule_id]


def _rule_tests(ctx: Ctx) -> dict:
    tree = _stage_tree(ctx)
    # Provenance is written before any trust check: gate 1 reads release/provenance. Step 10 writes the same file too,
    # and the write is idempotent (it depends only on VERIFIED records), so this only moves it ahead of the check.
    _write_release_provenance(ctx)
    pending = ctx.outputs.get("candidates", {}).get("autofix_pending", [])
    # Certification of automatic FIX rules (Addendum F3 step 4). Any failure demotes the row to its pending form.
    demoted = autofix.promote_certified(
        tree, pending, trust=_pending_row_findings,
        certify=lambda root, rule_id: autofix.certify_row(root, rule_id, blob_root=ctx.path("store"),
                                                          author=ctx.plan.author, at=ctx.plan.created_at))
    parent = _parent_rules(ctx)
    safety = _fix_trust_findings(tree)
    unsafe = {f["rule_id"] for f in safety}
    release_rules = []
    for row in _rule_rows(tree):
        previous = parent.get(row["id"])
        release_rules.append({
            "id": row["id"], "maturity": row.get("maturity"), "origin": row.get("origin"),
            "evidence_ids": list(row.get("evidence") or []),
            "in_release_delta": previous is None or canonical_bytes(previous) != canonical_bytes(row),
            "validation_passed": True,  # schema and authoring checks (steps 7 and 8) passed for every row
            "safety_passed": row["id"] not in unsafe,
        })
    return {"release_rules": release_rules, "safety_findings": safety, "autofix_demoted": demoted}


def _redaction_scan(release: Path) -> list:
    hits = []
    for path in sorted(p for p in release.rglob("*") if p.is_file() and p.name != "release.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if redact_text(text) != text:
            hits.append(path.relative_to(release).as_posix())
    return hits


def _coverage_data(ctx: Ctx, rules_out: dict) -> dict:
    tree = _stage_tree(ctx)
    index = {}
    for path in sorted((tree / "evidence").glob("EV-*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        index[rec["id"]] = {"valid": True, "official": rec.get("official") is True, "origin": rec.get("origin")}
    changes, accounting, transitions = [], [], []
    for pair in ctx.plan.pairs:
        step = pair["step"]
        document = ctx.read(("accounting", f"{pair_key(pair)}.json"))
        accounting.append(document)
        records = Ledger.load(ctx.path("ledgers", f"{pair_key(pair)}.json")).records()
        changes.extend(records)
        transitions.append({
            "step": step, "sources_verified": _verified(ctx, pair["from"]) and _verified(ctx, pair["to"]),
            "accounting_complete": all(item["state"] != "PENDING" for item in document["files"]),
            "ledger_present": True})
    sources = [{"source_id": s["source_id"], "required": bool(_spec_for(ctx, s["source_id"]).get("required")),
                "status": s["status"]} for s in _records(ctx)]
    inventory = [{"source_id": sid, "file_count": len(_load_snapshot(ctx, sid)["entries"]),
                  "snapshot_digest": _load_snapshot(ctx, sid)["snapshot_digest"]}
                 for sid in sorted(r["source_id"] for r in _records(ctx) if r["status"] == "VERIFIED")]
    release = ctx.workdir / "release"
    return json.loads(canonical_bytes({
        "declared_scope": {"sources": sorted(s["source_id"] for s in sources), "modules": ["*"],
                           "steps": [p["step"] for p in ctx.plan.pairs],
                           "domains": sorted({c["domain"] for c in changes})},
        "inventory": inventory, "sources": sources, "accounting": accounting, "changes": changes,
        "evidence_index": index, "release_rules": rules_out["release_rules"], "rule_findings": [],
        "safety_findings": rules_out["safety_findings"], "redaction_findings": _redaction_scan(release),
        "declared_transitions": transitions}).decode("utf-8"))


def _write_release_provenance(ctx: Ctx) -> None:
    release = ctx.workdir / "release"
    verified = [r for r in _records(ctx) if r["status"] == "VERIFIED"]
    snaps = [_load_snapshot(ctx, r["source_id"]) for r in verified]
    write_provenance(release, snaps, verified)


def _compact_changes(changes) -> list:
    """The ledger changes as the coverage bundle keeps them: only what the coverage metrics, gates and cross-checks
    read (`change_id`, `class`, `disposition`, `disposition_data.evidence_ids`, `subject_key`, the location paths).
    A real pair has ~157k changes; their full records (detail, history, hashes) made the bundle 237 MB, over the
    package validator's per-file limit."""
    return [{"change_id": c["change_id"], "class": c["class"], "disposition": c["disposition"],
             "disposition_data": {"evidence_ids": list((c.get("disposition_data") or {}).get("evidence_ids") or [])},
             "subject_key": c["subject_key"],
             "locations": [{"path": path} for path in sorted({loc["path"] for loc in c.get("locations") or []})]}
            for c in changes]


def _coverage(ctx: Ctx) -> dict:
    _write_release_provenance(ctx)
    rules_out = {"release_rules": ctx.outputs["rule-tests"]["release_rules"],
                 "safety_findings": ctx.outputs["rule-tests"]["safety_findings"]}
    data = _coverage_data(ctx, rules_out)
    data["changes"] = _compact_changes(data["changes"])  # the manifest below is built from what the bundle keeps
    try:
        manifest = cm.build_coverage_manifest(data, checked_at=ctx.plan.created_at, tool_version=ctx.plan.tool_version,
                                              schema_versions={"coverage_manifest": "1"})
        limits = _partial_limits(ctx, manifest)
        if limits:
            manifest = cm.build_coverage_manifest(data, checked_at=ctx.plan.created_at,
                                                  tool_version=ctx.plan.tool_version,
                                                  schema_versions={"coverage_manifest": "1"}, limits=limits)
    except cm.ManifestError as exc:
        raise StepStop("MANIFEST_INCONSISTENT", _mask(exc, ctx.plan)) from None
    release = ctx.workdir / "release"
    (release / "coverage").mkdir(parents=True, exist_ok=True)
    write_compact_json_file(release / "coverage" / "inputs.json", data)
    write_json_file(release / cm.COVERAGE_FILE[0] / cm.COVERAGE_FILE[1], manifest)
    return {"completeness": manifest["completeness"], "manifest_digest": manifest["manifest_digest"],
            "limits": limits if limits else [], "metrics": [{"id": m["id"], "numerator": m["numerator"],
                                                             "denominator": m["denominator"]}
                                                            for m in manifest["metrics"]]}


def _partial_limits(ctx: Ctx, manifest: dict) -> list:
    """One limit line per gate that is partial-allowed and failed, naming the gate (the decision needs that)."""
    limits = []
    for gate in manifest["gates"]:
        allowed = PARTIAL_ALLOWED.get(gate["gate_id"], frozenset())
        if gate["status"] == "FAIL" and gate["reason_codes"] and set(gate["reason_codes"]) <= allowed:
            sample = ", ".join(_mask(item, ctx.plan) for item in gate["offenders"][:3])
            limits.append(f"{gate['gate_id']} {','.join(gate['reason_codes'])}: {gate['offenders_total']} item(s)"
                          f" ({sample})")
    return limits


def _gates(ctx: Ctx) -> dict:
    release = ctx.workdir / "release"
    manifest = json.loads((release / cm.COVERAGE_FILE[0] / cm.COVERAGE_FILE[1]).read_text(encoding="utf-8"))
    inputs = json.loads((release / "coverage" / "inputs.json").read_text(encoding="utf-8"))
    findings = cm.check_consistency(manifest, inputs)
    if findings:
        raise StepStop("MANIFEST_INCONSISTENT", f"{len(findings)} finding(s); first {_mask(findings[0], ctx.plan)}")
    decision = decide(manifest["gates"], manifest["limits"])
    return {"completeness": decision["completeness"], "reasons": decision["reasons"],
            "gates": [{"gate_id": g["gate_id"], "status": g["status"], "blocking": g["blocking"],
                       "reason_codes": g["reason_codes"]} for g in manifest["gates"]]}


def _steps_covered(ctx: Ctx) -> list:
    """One row per distinct step. Its ledger digest is the sha256 of the ledger file when one pair carries the step,
    else a digest over the step's pair ledgers keyed by pair key (sorted), so each pair's ledger is covered."""
    manifest = json.loads((ctx.workdir / "release" / "coverage" / "coverage-manifest.json").read_text(encoding="utf-8"))
    keys_by_step: dict = {}
    for pair in ctx.plan.pairs:
        keys_by_step.setdefault(pair["step"], []).append(pair_key(pair))
    rows = []
    for step, keys in keys_by_step.items():
        ledger_hashes = {key: hashlib.sha256(ctx.path("ledgers", f"{key}.json").read_bytes()).hexdigest()
                         for key in keys}
        if len(keys) == 1:
            ledger_digest = ledger_hashes[keys[0]]
        else:
            ledger_digest = digest_obj({key: ledger_hashes[key] for key in sorted(keys)})
        rows.append({"step": step, "completeness": manifest["completeness"], "ledger_digest": ledger_digest})
    return sorted(rows, key=lambda row: row["step"])


def _build_package(ctx: Ctx) -> dict:
    plan, release = ctx.plan, ctx.workdir / "release"
    completeness = ctx.outputs["gates"]["completeness"]
    if completeness == "FAILED" and not ctx.allow_failed:
        raise StepStop("COMPLETENESS_FAILED", "a blocking gate failed; the release is not built")
    entries = json.loads((release / "provenance" / "sources.json").read_text(encoding="utf-8"))
    manifest = json.loads((release / cm.COVERAGE_FILE[0] / cm.COVERAGE_FILE[1]).read_text(encoding="utf-8"))
    parent_id = None
    if plan.parent_dir is not None:
        parent_id = json.loads((Path(plan.parent_dir) / "release.json").read_text(encoding="utf-8"))["release_id"]
    meta = {
        "label": plan.label, "parent_release": parent_id,
        "framework": {"built_with": plan.tool_version, "min_framework": plan.tool_version, "max_framework": None},
        "schema_versions": dict(TOOL_SCHEMA_VERSIONS), "sources": sources_meta(entries),
        "steps_covered": _steps_covered(ctx), "coverage_manifest_digest": manifest["manifest_digest"],
        "completeness": completeness, "build": {"tool_version": plan.tool_version,
                                                "build_time": plan.created_at, "host_free": True},
    }
    written = write_release_manifest(release, meta, secrets=plan.secrets)
    destructive, supersede, approved = [], set(plan.supersede), {}
    if plan.parent_dir is not None:
        diff = diff_releases(plan.parent_dir, release)
        destructive = sorted(e["id"] for e in diff.entries if e.get("destructive"))
        if plan.supersede_policy is not None:
            approved = {str(rid): str(reason) for rid, reason in
                        sorted(plan.supersede_policy(diff, plan.parent_dir, release).items())}
            supersede |= set(approved)
        unapproved = destructive_unapproved(diff.entries, supersede)
        if unapproved:
            raise StepStop("DESTRUCTIVE_NEEDS_SUPERSEDE", f"removed without approval: {', '.join(unapproved)}")
    out = {"release_id": written["release_id"], "release_digest": written["release_digest"],
           "completeness": completeness, "destructive": destructive,
           "supersede": sorted(plan.supersede) if plan.supersede_policy is None else sorted(supersede),
           "dev_only": completeness == "FAILED"}
    if plan.supersede_policy is not None:
        out["supersede_policy"] = _policy_name(plan.supersede_policy)
        out["approved"] = approved
    return out


def _validate_package(ctx: Ctx) -> dict:
    if ctx.outputs["build-package"]["completeness"] == "FAILED":
        return {"status": RUN_SKIPPED, "reason": "NOT_EXPORTABLE"}
    if assess(ctx.workdir / "release"):
        # Internal and Enterprise-derived releases are refused by the exporter, by design and with no override. The
        # same gate decides here, so there is no package to round-trip; the release is still verified by step 17.
        return {"status": RUN_SKIPPED, "reason": "INTERNAL_NOT_EXPORTABLE"}
    scratch = Path(tempfile.mkdtemp(prefix="validate-", dir=str(ctx.workdir)))
    try:
        archive = scratch / "check.ofkp"
        export_package(ctx.workdir / "release", archive)
        (scratch / "stage").mkdir()
        validate_package(archive, scratch / "stage", running_version=ctx.plan.tool_version)
    except Exception as exc:
        code = getattr(exc, "code", None) or "PACKAGE_INVALID"
        raise StepStop(str(code), _mask(exc, ctx.plan)) from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return {"checked": True}


def _publish(ctx: Ctx) -> dict:
    if ctx.outputs["build-package"]["completeness"] == "FAILED":
        return {"status": RUN_SKIPPED, "reason": "STAGED_ONLY"}
    rid = ctx.outputs["build-package"]["release_id"]
    dest = ctx.home / RELEASES_DIR / rid
    if dest.exists():
        raise StepStop("RELEASE_EXISTS", f"{rid} is already installed")
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(ctx.workdir / "release", dest)
    set_release_state(ctx.home, rid, ReleaseState.INSTALLED)  # the run already holds the kb-home lock
    details = {"digest": ctx.outputs["build-package"]["release_digest"]}
    if ctx.plan.supersede_policy is not None:
        built = ctx.outputs["build-package"]
        details.update({"supersede_policy": built["supersede_policy"], "approved": built["approved"]})
    ctx.audit.record("release_installed", target=rid, outcome="ok", details=details)
    return {"release_id": rid, "path": f"{RELEASES_DIR}/{rid}"}


def _export(ctx: Ctx) -> dict:
    return {"status": RUN_SKIPPED, "reason": "explicit `knowledge package export` after the build"}


def _import_activate(ctx: Ctx) -> dict:
    return {"status": RUN_SKIPPED, "reason": "consumer-side step (knowledge package import)"}


def _provenance(ctx: Ctx) -> dict:
    release = ctx.release_dir()
    try:
        verify_provenance(release)
    except KnowledgeReleaseError as exc:
        raise StepStop("PROVENANCE_INVALID", _mask(exc, ctx.plan)) from None
    problems = verify_release_tree(release)
    if problems:
        raise StepStop("RELEASE_INTEGRITY", _mask(problems[0], ctx.plan))
    return {"verified": True}


REAL_STEPS = (
    Step(1, "acquire", _acquire),
    Step(2, "verify", _verify, probe=_snapshot_probe),
    Step(3, "extract", _extract),
    Step(4, "classify", _classify),
    Step(5, "evidence", _evidence),
    Step(6, "candidates", _candidates),
    Step(7, "schema-validate", _schema_validate),
    Step(8, "dup-conflict", _dup_conflict),
    Step(9, "rule-tests", _rule_tests),
    Step(10, "coverage", _coverage),
    Step(11, "gates", _gates),
    Step(12, "build-package", _build_package),
    Step(13, "validate-package", _validate_package),
    Step(14, "publish-local", _publish),
    Step(15, "export", _export),
    Step(16, "import-activate", _import_activate),
    Step(17, "provenance", _provenance),
)
