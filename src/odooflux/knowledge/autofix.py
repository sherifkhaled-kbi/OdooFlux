"""Automatic FIX pipeline: orchestration and proof wiring (feature 012, plan Addendum F3, build steps 6 and 9).

Core module: it imports no transformer or parser (knowledge/ is core). The fix that runs is certified by
`update/certification` through the executor the composition root attaches (`certification.trusted_executor`); this
module never names a transformer.

- `prove_entry(record, inputs)` (the prover, step 6): proves ONE deterministic ledger change with
  `update/machine_confirmation.prove` (over `extract/proofs.py`, pure). On success it returns the candidate of a
  FIX-PENDING rule, its one evidence record and the machine confirmation record. A refusal raises `Refusal` with a code.
- `plan_pair(ledger, tree, ...)` (step 6): offers each eligible change to the prover. On success it writes
  `<tree>/confirmations/<rule_id>.json` (the sole writer of that file), accepts the pending rule
  (`accept.accept_fix_rule`: DETECT_ONLY, no fixer, review required) and records a `MACHINE` history entry on the ledger.
  The ledger `confirmed` flag is never touched. The change is then settled, so the ordinary detect-only candidate is
  not generated for it. A refusal is coded and leaves nothing behind; the change keeps its ordinary candidate. With no
  prover nothing is proposed at all.
- `promote_certified(tree, rule_ids, certify, trust)` (step 9): for each pending rule runs the certifier and then the
  trust check. Any failure restores the pending form (rule, history, certification, confirmation as they were) and is
  reported as a demotion. A demotion never blocks the build; the row simply stays DETECT_ONLY.
- `certify_row(tree, rule_id, blob_root=...)` (the real certifier of step 9): derives the fixer from the DERIVED class of the
  verified confirmation (L1; L2 when a blob store is given), issues the certification record through the attached
  executor, then revises the row (one history revision: fixer, tests, FIX_ENABLED, review off, approval
  `auto-cert:<policy>:<digest>`). The rule digest the confirmation binds is the digest of exactly that revision.

Trust is never decided here. The final authority is `release/safety.fix_row_trusted` (the loader's predicate); every
failure of this module ends in DETECT_ONLY with a coded reason.
"""

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.authoring import history as h
from odooflux.knowledge.authoring import ops
from odooflux.knowledge.candidates import accept as acc
from odooflux.knowledge.candidates import evidence_builder as eb
from odooflux.knowledge.candidates import generator as gen
from odooflux.knowledge.extract import proofs
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release import safety
from odooflux.knowledge.release.canonical import canonical_bytes, write_json_file
from odooflux.knowledge.release.safety import certification_path
from odooflux.knowledge.update import certification as cert
from odooflux.knowledge.update import machine_confirmation as mc

__all__ = ["ELIGIBLE_CLASSES", "PROVER", "RULE_BINDING", "ProofInputs", "Refusal", "certify_row", "plan_pair",
           "prove_entry", "promote_certified"]

ELIGIBLE_CLASSES = ("REPLACEMENT_CANDIDATE", "BEHAVIOUR_CHANGED", "DEPRECATED", "REMOVED")  # RENAMED never qualifies
CONFIRMATIONS_DIR = safety.CONFIRMATION_DIR
PROVER = "machine-confirmation/1"  # the prover's policy name: fingerprinted by the build (see pipeline._policy_name)
MACHINE_ACTOR = f"MACHINE:{mc.RECORD_SCHEMA}"  # a machine action is never MANUAL and never confirms the ledger entry
MACHINE_ACTION = "machine_confirm"
CERTIFY_ACTION = "certify"
FINAL_REV = 2  # a pending rule is created at rev 1; its certified revision is the next one (see certify_row)
RISK = "MEDIUM"
SEVERITY = "WARNING"
DETECTION = "KAP machine confirmation: ledger change proven by extract/proofs.py ({prover})"
TRANSFORMATION = "automatic: the certified fixer rewrites the imported symbol or removes the identity decorator"

_CERTIFIED = "odooflux.rules.python.certified"
# Derived class -> (detector_ref, fixer_ref). These are the names the certified fix templates bind (rules/python/
# certified.py); a test asserts they match transformers/fix_templates, which core cannot import.
RULE_BINDING = {
    "REPLACEMENT_CONFIRMED": (f"{_CERTIFIED}:flag_imported_symbol", f"{_CERTIFIED}:rewrite_imported_symbol"),
    "DELEGATING_ALIAS": (f"{_CERTIFIED}:flag_imported_symbol", f"{_CERTIFIED}:rewrite_imported_symbol"),
    "IDENTITY_DECORATOR_REMOVED": (f"{_CERTIFIED}:flag_imported_decorator", f"{_CERTIFIED}:remove_imported_decorator"),
}
TEST_LABELS = {"positive": "auto-cert:positive", "negative": "auto-cert:negative", "idempotence": "auto-cert:idempotence"}

NOT_PROVEN = "NOT_PROVEN"  # the prover refused the change (the coded reason is the Refusal code)
PROVER_FAULT = "PROVER_FAULT"  # the prover raised: this change only is refused
ACCEPT_REFUSED = "ACCEPT_REFUSED"  # the FIX-PENDING rule could not be accepted (nothing written)
CERTIFIER_MISSING = "CERTIFIER_NOT_ATTACHED"
CERTIFY_FAILED = "CERTIFY_FAILED"
TRUST_FAILED = "TRUST_FAILED"


class Refusal(Exception):
    """A coded refusal: `code` is a closed identifier, `detail` is for humans and must not echo source text."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ProofInputs:
    """What the prover may read for one ledger change.

    `tree` is the staged knowledge tree; `store` the build's blob store root; `sides` is {"from": identity, "to": identity}
    where identity = {source_id, snapshot_id, revision, verified, official, entries: {path: sha256}, source: dict} (the
    evidence source dict is `source`); `checked_on` the build date; `reserved` the evidence ids already in use."""
    tree: Path
    store: object
    sides: dict
    checked_on: str
    reserved: frozenset = frozenset()


def _path_in(locations, identity) -> str:
    hits = [loc for loc in locations if isinstance(loc, dict) and loc.get("snapshot_id") == identity.get("snapshot_id")]
    if len(hits) != 1:
        raise Refusal("ENTRY_LOCATIONS", "the ledger entry needs exactly one location in each pair side it uses")
    return hits[0]["path"]


def _side(identity, path, store, side: str) -> dict:
    """One proof side: the pinned blob of `path` read through the store (the store rehashes it on read)."""
    digest = (identity.get("entries") or {}).get(path)
    if not isinstance(digest, str):
        raise Refusal("SIDE_FILE_MISSING", f"the {side} side has no file for the change")
    try:
        data = BlobStore(store).get(digest)
    except SourceError:
        raise Refusal("BLOB_MISSING", f"the {side} blob is not in the blob store") from None
    revision = identity.get("revision")
    return {"source_id": identity.get("source_id"), "snapshot_id": identity.get("snapshot_id"), "revision": revision,
            "path": path, "blob_sha256": digest, "verified": identity.get("verified") is True,
            "official": identity.get("official") is True,
            "pinned": isinstance(revision, str) and safety.PINNED_REVISION.match(revision) is not None, "data": data}


def _forward_callee(data: bytes, path: str, old: str) -> str:
    """The name a delegating alias forwards to, read from the new side (BEHAVIOUR_CHANGED and DEPRECATED have no name)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refusal("PARSE_FAILED", "the new side is not utf-8") from None
    fact = (proofs.function_proofs(text, path) or {}).get(old) or {}
    shape = fact.get("forward_shape")
    callee = shape.get("callee") if isinstance(shape, dict) else None
    if not isinstance(callee, str):
        raise Refusal("NO_FORWARD", "the change is not a delegating alias in the new source")
    return callee


def prove_entry(record, inputs) -> dict:
    """The prover (build step 6): ``{candidate, evidence, confirmation}`` for one ledger change, or a `Refusal`.

    Pure apart from reading blobs. Nothing is written; `plan_pair` writes what this returns when it is accepted."""
    if not isinstance(inputs, ProofInputs) or inputs.store is None:
        raise Refusal("NO_STORE", "no blob store is attached to the prover")
    cls = record.get("class")
    if cls not in ELIGIBLE_CLASSES:
        raise Refusal("NOT_ELIGIBLE", f"class {cls!r} is never proven")
    sides = inputs.sides if isinstance(inputs.sides, dict) else {}
    if set(sides) != {"from", "to"}:
        raise Refusal("SIDE_MISSING", "both pair sides are required")
    old = str(record.get("subject_key", "")).rsplit(".", 1)[-1]
    locations = record.get("locations") or []
    if not isinstance(locations, list):
        raise Refusal("ENTRY_LOCATIONS", "the ledger entry has no location list")
    detail = record.get("detail") if isinstance(record.get("detail"), dict) else {}
    if cls == "REPLACEMENT_CANDIDATE":
        from_path, to_path = _path_in(locations, sides["from"]), _path_in(locations, sides["to"])
        new = str(detail.get("to") or "").rsplit(".", 1)[-1]  # the bare symbol (the ledger keeps `addon.name`)
    elif cls == "REMOVED":
        from_path = to_path = _path_in(locations, sides["from"])
        new = None
    else:  # BEHAVIOUR_CHANGED, DEPRECATED: the one location is the new side; the old side is the same file
        from_path = to_path = _path_in(locations, sides["to"])
        new = None
    from_side = _side(sides["from"], from_path, inputs.store, "from")
    to_side = _side(sides["to"], to_path, inputs.store, "to")
    if cls in ("BEHAVIOUR_CHANGED", "DEPRECATED"):
        new = _forward_callee(to_side["data"], to_path, old)
    digest = hashlib.sha256(canonical_bytes({"change": record.get("change_id"), "prover": PROVER, "old": old,
                                             "new": new, "class": cls})).hexdigest()
    rule_id = f"{record.get('step')}.{record.get('domain')}.fix-{digest[:8]}"
    try:
        evidence = eb.build_evidence(record, evidence_id=eb.next_evidence_id(set(inputs.reserved)), rule_ids=[rule_id],
                                     source=sides["to"]["source"], risk=RISK,
                                     detection_method=DETECTION.format(prover=PROVER),
                                     proposed_transformation=TRANSFORMATION, checked_on=inputs.checked_on,
                                     checked_by=eb.CHECKER)
    except (ValueError, KeyError, TypeError) as exc:  # EvidenceError, SourceIdentityError: no evidence, no proof
        raise Refusal("EVIDENCE_BUILD", str(exc)[:200]) from None
    proof = mc.prove(record, {"from": from_side, "to": to_side}, rule_id=rule_id, evidence=[evidence], new=new)
    if isinstance(proof, proofs.Refusal):
        raise Refusal(proof.code, proof.detail)
    p = proof.proof
    detector, fixer = RULE_BINDING[p.derived_class]
    if p.new is None:
        message = f"{p.old} is an identity decorator removed from {p.module}; a bare @{p.old} is a no-op."
        suggestion = "Remove the bare decorator (automatic fix once certified)."
    else:
        message = f"{p.old} is replaced by {p.new} in {p.module} ({p.derived_class})."
        suggestion = f"Use {p.new} (automatic fix once certified)."
    rule = {"id": rule_id, "step": record["step"], "category": record["domain"], "severity": SEVERITY,
            "maturity": "DETECT_ONLY", "review_required": True, "risk": RISK, "origin": "GENERATED",
            "evidence": [evidence["id"]], "detector_ref": detector, "fixer_ref": None,
            "params": copy.deepcopy(p.derived_params), "tests": {}, "message": message, "suggestion": suggestion}
    candidate = {"candidate_id": "CR-" + hashlib.sha256(rule_id.encode("utf-8")).hexdigest()[:16],
                 "change_id": record["change_id"], "template_id": PROVER, "status": "PROPOSED",
                 "detectors_verified": True, "rule": rule}
    # The row as it will stand after certification: the confirmation binds this shape (rule_digest covers fixer_ref,
    # tests and rev; maturity, review_required and approval are outside the digest).
    final = dict(rule, fixer_ref=fixer, tests=dict(TEST_LABELS), maturity="FIX_ENABLED", review_required=False,
                 rev=FINAL_REV)
    try:
        confirmation = mc.build(proof, rule_row=final)
    except mc.ConfirmationError as exc:
        raise Refusal(getattr(exc, "code", "CONFIRMATION_BUILD"), str(exc)[:200]) from None
    return {"candidate": candidate, "evidence": evidence, "confirmation": confirmation}


prove_entry.policy_name = PROVER  # the build fingerprints the prover by name (pipeline._policy_name)


def plan_pair(ledger, tree, *, prove=None, store=None, author=None, at=None, sources=None, checked_on="") -> dict:
    """Accept a FIX-PENDING rule for every eligible change that `prove` proves. Returns {accepted, refused}.

    `prove(record, inputs)` is called with a `ProofInputs` (the second argument is named `store` in the phase 1 fakes,
    which ignore it). `sources` maps a pair side to its identity (see `ProofInputs`)."""
    out = {"accepted": [], "refused": []}
    if prove is None:
        return out
    tree = Path(tree)
    records = ledger.records()
    reserved = set(eb.used_evidence_ids(tree, records)) | gen._store_evidence_ids(tree)
    for record in sorted(records, key=lambda r: r["change_id"]):
        if record.get("disposition") in gen.DISPOSED or record.get("class") not in ELIGIBLE_CLASSES:
            continue
        cid = record["change_id"]
        inputs = ProofInputs(tree=tree, store=store, sides=sources or {}, checked_on=checked_on,
                             reserved=frozenset(reserved))
        try:
            proof = prove(record, inputs)
        except Refusal as exc:
            out["refused"].append({"change_id": cid, "code": exc.code, "detail": exc.detail})
            continue
        except Exception as exc:  # a prover fault refuses this change only; the build goes on
            out["refused"].append({"change_id": cid, "code": PROVER_FAULT, "detail": type(exc).__name__})
            continue
        try:
            accepted = _accept_proof(tree, ledger, proof, author=author, at=at)
        except Exception as exc:  # per change: one refused change never stops the others or the build
            out["refused"].append({"change_id": cid, "code": ACCEPT_REFUSED, "detail": str(exc)[:200]})
            continue
        reserved.add(proof["evidence"]["id"])
        out["accepted"].append(accepted)
    return out


def _accept_proof(tree: Path, ledger, proof: dict, *, author, at) -> dict:
    candidate, evidence, confirmation = proof["candidate"], proof["evidence"], proof["confirmation"]
    rule_id = candidate["rule"]["id"]
    path = tree / CONFIRMATIONS_DIR / f"{rule_id}.json"
    if path.exists():
        raise acc.AcceptError(f"confirmation {rule_id}.json already exists; ids are never reused")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(path, confirmation)
    try:
        acc.accept_fix_rule(tree, candidate, ledger=ledger, evidence=[evidence], author=author, at=at)
    except Exception:
        path.unlink(missing_ok=True)  # the confirmation is only kept with the rule it proves
        if not any(path.parent.iterdir()):
            path.parent.rmdir()
        raise
    ledger.append_history(candidate["change_id"], actor=MACHINE_ACTOR, action=MACHINE_ACTION, from_value=None,
                          to_value=confirmation.get("record_digest"))
    return {"change_id": candidate["change_id"], "candidate_id": candidate["candidate_id"], "rule_id": rule_id}


def certify_row(tree, rule_id, *, blob_root=None, author=None, at=None) -> dict:
    """Certify one pending FIX rule (build step 9). Returns the certification record; raises `Refusal` or the
    certification error. The caller restores the pending form on any exception (`promote_certified`)."""
    tree = Path(tree)
    try:
        _, pending = ops._find(tree, rule_id)
        doc = ops._history(tree, rule_id)
    except ops.OpsError as exc:
        raise Refusal("RULE_MISSING", str(exc)) from None
    if (pending.get("origin") != "GENERATED" or pending.get("maturity") != "DETECT_ONLY"
            or pending.get("fixer_ref") is not None):
        raise Refusal("NOT_PENDING", "only a pending FIX rule (DETECT_ONLY, no fixer) is certified")
    path = safety.confirmation_path(tree, rule_id)
    if path is None or not path.is_file():
        raise Refusal("CONFIRMATION_MISSING", "no machine confirmation for this rule")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refusal("CONFIRMATION_UNREADABLE", "the machine confirmation is not readable JSON") from None
    binding = RULE_BINDING.get(record.get("derived_class")) if isinstance(record, dict) else None
    if binding is None:
        raise Refusal("CLASS_UNBOUND", "the confirmed class has no certified fix")
    rev = doc["entries"][-1]["rev"] + 1
    final = dict(pending, fixer_ref=binding[1], tests=dict(TEST_LABELS), maturity="FIX_ENABLED",
                 review_required=False, rev=rev)
    kb = load_knowledge(tree)
    rows = [kb.evidence[eid] for eid in final.get("evidence") or [] if eid in kb.evidence]
    verdict = mc.verify(record, rule_row=final, evidence_rows=rows)  # L1: recomputed, never trusted
    if not verdict.ok:
        raise Refusal("CONFIRMATION_INVALID", "; ".join(sorted({str(code) for code, _ in verdict.problems})))
    if blob_root is not None:  # L2: only where the blobs exist (build step 9)
        problems = safety.source_problems(tree, rule_id, blob_root)
        if problems:
            raise Refusal("SOURCE_INVALID", "; ".join(sorted({str(code) for code, _ in problems})))
    index = safety.load_provenance_index(tree)
    issued = cert.issue(final, rows, source_confidentiality=cert.source_confidentiality_from_index(index),
                        change_class=verdict.derived_class, confirmation_verified=True)
    target = certification_path(tree, rule_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json_file(target, issued)
    approved = dict(final, approval=cert.reference(issued))
    ops._revise(tree, rule_id, action=CERTIFY_ACTION,
                change=lambda row, d: (copy.deepcopy(approved), {"class": verdict.derived_class}),
                summary=f"certified {verdict.derived_class} by the machine confirmation", author=author, at=at)
    return issued


def promote_certified(tree, rule_ids, *, certify, trust) -> list:
    """Run `certify(tree, rule_id)` then `trust(tree, rule_id)` (findings) for each pending rule. Returns the demotions.

    Each row is independent. A failure restores that row's bytes (rule, history, certification and confirmation) and is
    reported with a coded reason; the build is never blocked by a row."""
    tree = Path(tree)
    demoted = []
    for rule_id in sorted(set(rule_ids)):
        snapshot = _snapshot(tree, rule_id)
        try:
            if certify is None:
                raise Refusal(CERTIFIER_MISSING, "no certifier is attached; the row stays DETECT_ONLY")
            certify(tree, rule_id)
            findings = trust(tree, rule_id)
            if findings:
                first = findings[0]
                raise Refusal(TRUST_FAILED, f"{first.get('code')}: {first.get('detail')}")
        except Exception as exc:  # every failure demotes; the build is never blocked by a row
            _restore(snapshot)
            code = exc.code if isinstance(exc, Refusal) else CERTIFY_FAILED
            demoted.append({"rule_id": rule_id, "code": code, "detail": str(exc)[:200]})
    return demoted


def _rule_path(tree: Path, rule_id: str):
    try:
        path, _ = ops._find(tree, rule_id)
    except ops.OpsError:
        return None
    return path


def _snapshot(tree: Path, rule_id: str) -> dict:
    try:
        history = h.history_path(tree, rule_id)
    except h.HistoryError:
        history = None
    paths = {"rule": _rule_path(tree, rule_id), "history": history,
             "cert": certification_path(tree, rule_id), "confirmation": safety.confirmation_path(tree, rule_id)}
    return {name: (path, path.read_bytes() if path is not None and path.is_file() else None)
            for name, path in paths.items()}


def _restore(snapshot: dict) -> None:
    for path, data in snapshot.values():
        if path is None:
            continue
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
