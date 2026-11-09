"""Promotion gates 1 to 5 for FIX_ENABLED rules over a knowledge tree (REQ-KAP-018, REQ-KAP-027, REQ-KAP-039;
contracts/manual-rule-cli.md "Promotion gates", contracts/release-lifecycle.md "Rule execution").

`fix_gate_findings(tree_root)` is pure: it reads the tree through `knowledge.loader.load_knowledge` and returns a list of
findings `{rule_id, gate, code, detail}`. An empty list means every checked rule passes gates 1 to 5. Gate 6 (approval)
belongs to `promote` and is not evaluated here.

Scope: only FIX_ENABLED rules are gated. A rule with no `origin` (or `origin` BUILTIN) is a grandfathered built-in rule
(plan.md) and is skipped unless `include_builtin=True`.

Gate 1 provenance: a record's own `official: true` is a claim, not evidence. The claim is supported only when the record
has a `source_id` that resolves in the release provenance (`provenance/sources.json`, a list of
`{source_id, revision, snapshot_digest, official, status}`; optional `url`, `origin_url`, `snapshot_id` and `kind`) to an
entry that is official, has a usable status, is pinned to a 40-hex git SHA or a `sha256:<64hex>` digest, and is on the
official allow-list: its `url` is an allow-listed https URL, or it is a local clone whose `origin_url` is a verified origin
(`sources.official_origin`, the same contract the git-local adapter uses). A `local:` url with no verified `origin_url` is
never official evidence (`OFFICIAL_IDENTITY_UNVERIFIED`). A local-origin entry is also bound to its snapshot: the snapshot
file `<tree>/../snapshots/<snapshot_id>.json` must exist, its revision, origin and recomputed digest must equal the
entry's. The record must not be AI-originated and at least one location must carry `content_sha256`.
Provenance is `provenance` when given, else `<tree_root>/../provenance/sources.json`; when neither is readable the
provenance is unknown and every official claim is unsupported (fail closed).

Gate 4 runs the A001..A006 authoring checks (authoring/checks.py) on the loaded tree: an ERROR involving the rule (by id,
in its finding pointer or message) blocks it, as does a `conflicts_with` target that is FIX_ENABLED.

Fail closed: an absent `review_required` counts as not false.

Trust (feature 012, Wave 3c, `fix_row_trusted`): one predicate for the load and import boundaries (package import P10 and
the loader). A FIX_ENABLED row is trusted when
  1. it is a shipped built-in row by byte identity AND the shipped baseline digest is computable (D3, inherited trust),
     which is only consulted while INHERITED_TRUST_RECORDABLE is True (True: see the constant); or
  2. it passes gates 1 to 5 AND, when certification governs it, its certification record verifies. Certification governs a
     row when the release has `certifications/<rule_id>.json` for it, or when its `approval` reference is automated
     (`auto-cert:`). A row whose `approval` is a human reference keeps the gates path unchanged. The change class a
     record is verified against is established by a verified machine confirmation (`confirmed_class`), never read from
     the record; with no such confirmation a governed row is refused (CONFIRMATION_MISSING).
     Review item 1 makes certification ALWAYS govern two kinds of row. (a) An origin other than MANUAL or BUILTIN
     (GENERATED, AI_PROPOSED, an unknown origin, or no origin on a row that is not shipped): such a row must carry an
     `auto-cert:` approval (CERT_APPROVAL_MISSING otherwise), a verified confirmation and a valid record. (b) A row whose
     fixer_ref or detector_ref is bound from `odooflux.rules.python.certified`: whatever its origin or approval string,
     a valid record must exist (a human approval reference then mismatches and is refused).
Certification never widens trust: it only adds a requirement on top of gates 1 to 5. The gate functions
(`gate_findings`, `fix_gate_findings`) are unchanged and still answer for every row exactly as before; the build-time
gates step and `promote` keep calling them.
"""

import functools
import json
import re
from pathlib import Path

from odooflux.knowledge.acquisition.blobstore import BlobStore, SourceError
from odooflux.knowledge.acquisition.sources import FORCED_UNOFFICIAL, enterprise_entry_problem, load_allow_list, \
    official_origin
from odooflux.knowledge.authoring.checks import check_authoring
from odooflux.knowledge.loader import load_knowledge
from odooflux.knowledge.release.builtin import builtin_digest
from odooflux.knowledge.release.canonical import CanonicalError, digest_obj
from odooflux.knowledge.update import certification as cert
from odooflux.knowledge.update import machine_confirmation as mc

FIX_ENABLED = "FIX_ENABLED"
BUILTIN_ORIGINS = (None, "BUILTIN")  # what a rule row CLAIMS; never used to skip a gate (see is_shipped_builtin_rule)


def _row_bytes(rule: dict) -> str:
    return json.dumps(rule, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@functools.lru_cache(maxsize=1)
def _shipped_rule_rows() -> dict:
    """id -> serialized row of every rule in the knowledge tree shipped with the package (read once per process)."""
    return {rule["id"]: _row_bytes(rule) for rule in load_knowledge().rules
            if isinstance(rule, dict) and isinstance(rule.get("id"), str)}


def is_shipped_builtin_rule(rule: dict) -> bool:
    """True only when `rule` is byte-for-byte the row shipped in the built-in tree. "Built-in rules are grandfathered"
    (migration-integration contract) means the shipped rows, not any row that claims `origin` BUILTIN or omits it: a
    release is not trusted to describe itself (REQ-KAP-027), so an origin-less FIX_ENABLED row that is new or altered goes
    through gates 1 to 5 like any other."""
    shipped = _shipped_rule_rows().get(rule.get("id"))
    return shipped is not None and shipped == _row_bytes(rule)


AI_ORIGIN = "AI_PROPOSED"
BLOCKING_STATUSES = frozenset({"UNVERIFIED", "CONFLICTING"})
TEST_KINDS = ("positive", "negative", "idempotence")
USABLE_SOURCE_STATUSES = ("VERIFIED",)
PINNED_REVISION = re.compile(r"^(?:[0-9a-f]{40}|sha256:[0-9a-f]{64})$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
PROVENANCE_RELPATH = ("provenance", "sources.json")
SNAPSHOT_ID = re.compile(r"^ss-[0-9a-f]{12}$")
IDENTITY_CODE = "OFFICIAL_IDENTITY_UNVERIFIED"

# D3 (owner-approved): carried-forward shipped rows are accepted at import by BYTE identity with the verified shipped
# baseline, never by id; the decision is recorded in the `release_installed` audit entry (details.inherited_trust).
INHERITED_TRUST_RECORDABLE = True

CERT_DIR = "certifications"  # <release>/knowledge/certifications/<rule_id>.json (inside the manifest digest)
CERT_GATE = 6  # the approval gate: a certification record is the automated approval, checked by fix_row_trusted only
CERT_MISSING = "cert-missing"
CERT_UNREADABLE = "cert-unreadable"
CERT_APPROVAL_MISMATCH = "cert-approval-mismatch"
CERT_VERIFY_FAILED = "cert-verify-failed"
CERT_EXECUTOR_MISSING_CODE = "cert-executor-missing"
AUTO_APPROVAL_PREFIX = f"{cert.REFERENCE_PREFIX}:"
CONFIRMATION_DIR = "confirmations"  # <release>/knowledge/confirmations/<rule_id>.json (inside the manifest digest)
CONFIRMATION_MISSING = "confirmation-missing"  # no verified machine confirmation establishes the change class
CONFIRMATION_UNREADABLE = "confirmation-unreadable"
CONFIRMATION_INVALID = "confirmation-invalid"  # the machine confirmation does not verify (L1)
CERT_APPROVAL_MISSING = "cert-approval-missing"  # a row whose origin requires it carries no automated approval
TRUSTED_ORIGINS = ("MANUAL", "BUILTIN")  # origins a certification never has to govern (see origin_requires_certification)
CERTIFIED_MODULE = "odooflux.rules.python.certified"  # the bound fixers and detectors of automated certification
RULE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def _finding(rule_id: str, gate: int, code: str, detail: str) -> dict:
    return {"rule_id": rule_id, "gate": gate, "code": code, "detail": detail}


def load_provenance_index(tree_root, provenance=None):
    """Map source_id -> entry, or None when provenance is unknown. Duplicated source_ids are ambiguous and dropped."""
    if provenance is None:
        path = Path(tree_root).resolve().parent.joinpath(*PROVENANCE_RELPATH)
        if not path.is_file():
            return None
        try:
            provenance = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if isinstance(provenance, dict):
        provenance = provenance.get("sources")
    if not isinstance(provenance, list):
        return None
    seen, index = {}, {}
    for entry in provenance:
        if isinstance(entry, dict) and isinstance(entry.get("source_id"), str):
            seen[entry["source_id"]] = seen.get(entry["source_id"], 0) + 1
            index[entry["source_id"]] = entry
    return {sid: entry for sid, entry in index.items() if seen[sid] == 1}


def _snapshot_binding(entry: dict, origin: str, snapshot_dir):
    """None when the provenance revision, origin and digest equal the recomputed snapshot, else the reason."""
    snapshot_id = entry.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID.match(snapshot_id) or snapshot_dir is None:
        return "snapshot_id is missing, digest is unverifiable"
    try:
        snap = json.loads((Path(snapshot_dir) / f"{snapshot_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "snapshot file is unavailable, digest is unverifiable"
    if not isinstance(snap, dict) or snap.get("source_id") != entry.get("source_id"):
        return "snapshot does not belong to the source"
    if snap.get("revision") != entry.get("revision") or snap.get("origin_url") != origin:
        return "provenance revision or origin does not match the snapshot"
    recorded = str(entry.get("snapshot_digest") or "")
    recorded = recorded[len("sha256:"):] if recorded.startswith("sha256:") else recorded
    recomputed = digest_obj({"source_id": snap["source_id"], "revision": snap["revision"],
                             "entries": snap.get("entries")})
    if not (recorded == recomputed == snap.get("snapshot_digest")):
        return "provenance digest does not match the recomputed snapshot digest"
    return None


def _official_problem(record: dict, index, allow_list: list, snapshot_dir=None):
    """None when the record's official claim is supported by provenance, else the reason it is not."""
    if record.get("origin") == AI_ORIGIN:
        return "record origin is AI"
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return "record has no source_id"
    if index is None:
        return "provenance is unknown"
    entry = index.get(source_id)
    if entry is None:
        return f"source_id {source_id} is not in the provenance"
    if entry.get("official") is not True:
        return f"source {source_id} is not official"
    if entry.get("kind") in FORCED_UNOFFICIAL:
        return f"source {source_id} is an unofficial kind ({entry.get('kind')})"
    # enterprise coherence (kind, confidentiality, licence). Gate 1 also runs on packages, where verify_provenance is
    # not called, so the same refusals as the release verifier apply here.
    coherence = enterprise_entry_problem(entry)
    if coherence is not None:
        return f"source {source_id}: {coherence}"
    if entry.get("status") not in USABLE_SOURCE_STATUSES:
        return f"source {source_id} status {entry.get('status')} is not usable"
    url, origin_url = entry.get("url"), entry.get("origin_url")
    local = isinstance(url, str) and url.startswith("local:")
    if local or origin_url is not None:
        origin = origin_url if isinstance(origin_url, str) else None
        if origin is None or official_origin(entry.get("kind"), origin, allow_list) != origin:
            return f"local source without verified origin ({IDENTITY_CODE})"
    else:
        if not isinstance(url, str) or not url:
            return f"source {source_id} has no url"
        if not any(url.startswith(prefix) for prefix in allow_list):
            return f"source {source_id} url is not on the official allow-list"
    revision = entry.get("revision")
    if not isinstance(revision, str) or not PINNED_REVISION.match(revision):
        return f"source {source_id} revision is not pinned"
    if local or origin_url is not None:
        binding = _snapshot_binding(entry, origin_url, snapshot_dir)
        if binding is not None:
            return f"{binding} ({IDENTITY_CODE})"
    locations = record.get("locations") or []
    if not any(isinstance(loc, dict) and isinstance(loc.get("content_sha256"), str)
               and SHA256_HEX.match(loc["content_sha256"]) for loc in locations):
        return "no location carries content_sha256"
    return None


def _gate1(rule_id, ids, records, kb_evidence, index, allow_list, snapshot_dir=None) -> list:
    out = []
    if not ids:
        out.append(_finding(rule_id, 1, "no-linked-evidence", "rule links no evidence"))
    for eid in ids:
        if eid not in kb_evidence:
            out.append(_finding(rule_id, 1, "evidence-missing", f"linked evidence {eid} does not exist"))
    for eid, record in records:
        if record.get("status") in BLOCKING_STATUSES:
            out.append(_finding(rule_id, 1, "evidence-unverified-or-conflicting",
                                f"{eid} has status {record.get('status')}"))
    supported = False
    for eid, record in records:
        if record.get("official") is not True:
            continue
        reason = _official_problem(record, index, allow_list, snapshot_dir)
        if reason is None:
            supported = True
        else:
            out.append(_finding(rule_id, 1, "official-claim-unsupported", f"{eid} claims official but {reason}"))
    if ids and not supported:
        out.append(_finding(rule_id, 1, "no-official-evidence",
                            "no linked record is officially supported and non-AI (AI or unofficial evidence alone is "
                            "refused)"))
    return out


def _gate2(rule, rule_id, records) -> list:
    out = []
    step = rule.get("step")
    if not isinstance(step, str) or not step:
        out.append(_finding(rule_id, 2, "step-missing", "rule has no step"))
    for eid, record in records:
        source = record.get("source_applicability")
        target = record.get("target_applicability")
        ok_source = isinstance(source, dict) and all(isinstance(source.get(k), str) and source.get(k)
                                                     for k in ("from", "to"))
        ok_target = isinstance(target, dict) and isinstance(target.get("from"), str) and bool(target.get("from"))
        if not (ok_source and ok_target):
            out.append(_finding(rule_id, 2, "applicability-missing",
                                f"{eid} lacks source or target version applicability"))
    return out


def _gate3(rule, rule_id) -> list:
    tests = rule.get("tests")
    if not isinstance(tests, dict) or any(not isinstance(tests.get(kind), str) or not tests.get(kind)
                                          for kind in TEST_KINDS):
        return [_finding(rule_id, 3, "tests-not-registered",
                         "positive, negative and idempotence tests must all be registered")]
    return []


def _involves(finding, rule_id: str) -> bool:
    if finding.pointer == rule_id:
        return True
    return re.search(r"(?<![\w.\-])" + re.escape(rule_id) + r"(?![\w.\-])", finding.message) is not None


def _gate4(rule, rule_id, fix_ids, authoring_errors) -> list:
    out = [_finding(rule_id, 4, "conflict-with-fix-enabled", f"conflicts_with {target} is FIX_ENABLED")
           for target in rule.get("conflicts_with") or [] if target in fix_ids]
    out += [_finding(rule_id, 4, finding.code, finding.message)
            for finding in authoring_errors if _involves(finding, rule_id)]
    return out


def _gate5(rule, rule_id) -> list:
    out = []
    fixer = rule.get("fixer_ref")
    if not isinstance(fixer, str) or not fixer:
        out.append(_finding(rule_id, 5, "fixer-ref-missing", "FIX_ENABLED rule has no fixer_ref"))
    if rule.get("review_required") is not False:
        out.append(_finding(rule_id, 5, "review-required", "review_required must be false for a FIX_ENABLED rule"))
    return out


def rule_gate_context(kb) -> dict:
    """The per-knowledge-base inputs gates 1 to 5 share (FIX_ENABLED ids, allow-list, ERROR authoring findings).
    Computed once per knowledge base and passed to every per-rule evaluation."""
    return {"fix_ids": {rule.get("id") for rule in kb.rules if rule.get("maturity") == FIX_ENABLED},
            "allow_list": load_allow_list(),
            "authoring_errors": [f for f in check_authoring(kb) if f.severity == "ERROR"]}


def _rule_findings(rule, kb, index, snapshot_dir, context) -> list:
    """Gates 1 to 5 for one FIX_ENABLED rule of a loaded knowledge base."""
    rule_id = str(rule.get("id", "?"))
    ids = [eid for eid in rule.get("evidence") or [] if isinstance(eid, str)]
    records = [(eid, kb.evidence[eid]) for eid in ids if eid in kb.evidence]
    findings = _gate1(rule_id, ids, records, kb.evidence, index, context["allow_list"], snapshot_dir)
    findings += _gate2(rule, rule_id, records)
    findings += _gate3(rule, rule_id)
    findings += _gate4(rule, rule_id, context["fix_ids"], context["authoring_errors"])
    findings += _gate5(rule, rule_id)
    return findings


def gate_findings(kb, index, *, include_builtin: bool = False, snapshot_dir=None) -> list:
    """Gates 1 to 5 for every FIX_ENABLED rule of a loaded KnowledgeBase (`index` from load_provenance_index)."""
    context = rule_gate_context(kb)
    findings = []
    for rule in kb.rules:
        if rule.get("maturity") != FIX_ENABLED:
            continue
        if not include_builtin and is_shipped_builtin_rule(rule):
            continue
        findings += _rule_findings(rule, kb, index, snapshot_dir, context)
    return findings


def fix_gate_findings(tree_root, *, include_builtin: bool = False, provenance=None, snapshot_dir=None) -> list:
    """Gates 1 to 5. Snapshots for local-origin claims are read from `snapshot_dir`, default `<tree>/../snapshots`."""
    kb = load_knowledge(tree_root)
    if snapshot_dir is None:
        snapshot_dir = Path(tree_root).resolve().parent / "snapshots"
    return gate_findings(kb, load_provenance_index(tree_root, provenance), include_builtin=include_builtin,
                         snapshot_dir=snapshot_dir)


# --- certified trust (feature 012, Wave 3c) -------------------------------------------------------------------------

def shipped_baseline_digest():
    """The digest of the shipped knowledge tree, or None when it cannot be computed. None means no inherited trust."""
    try:
        digest = builtin_digest()  # the shipped tree (builtin.py owns the built-in root reference)
    except (OSError, ValueError, TypeError, KeyError, CanonicalError):
        return None
    return digest if isinstance(digest, str) and digest else None


def is_inherited_builtin(rule) -> bool:
    """D3: the row is a shipped built-in row by byte identity and the shipped baseline is verified."""
    return isinstance(rule, dict) and is_shipped_builtin_rule(rule) and shipped_baseline_digest() is not None


def certification_path(tree_root, rule_id):
    """``<tree>/certifications/<rule_id>.json``, or None when the id cannot name a file (fail closed)."""
    if not isinstance(rule_id, str) or not RULE_FILE.match(rule_id) or ".." in rule_id:
        return None
    return Path(tree_root) / CERT_DIR / f"{rule_id}.json"


def certified_ref(rule) -> bool:
    """True when the row's fixer_ref or detector_ref is bound from the certified fixers module."""
    for key in ("fixer_ref", "detector_ref"):
        ref = rule.get(key)
        if isinstance(ref, str) and ref.partition(":")[0] == CERTIFIED_MODULE:
            return True
    return False


def origin_requires_certification(rule) -> bool:
    """True when the row's origin is one a certification must govern: anything but MANUAL or BUILTIN. An absent origin
    counts as BUILTIN only for a shipped row (byte identity), otherwise it is unknown and governed."""
    origin = rule.get("origin")
    if origin in TRUSTED_ORIGINS:
        return False
    if origin is None:
        return not is_shipped_builtin_rule(rule)
    return True


def l2_required(rule, tree_root) -> bool:
    """True when L2 (`source_problems`, the retained blobs re-proved) applies to the row: a machine confirmation file
    exists for it, or its fixer is a certified one. Independent of origin and approval (review item 3)."""
    path = confirmation_path(tree_root, str(rule.get("id", "?")))
    return (path is not None and path.is_file()) or certified_ref(rule)


def _governed(rule, tree_root):
    """``(governed, approval)``: whether the certification path decides this row, and its approval reference.

    A row whose origin requires certification, or whose fixer or detector is certified, is always governed (review item
    1). Otherwise a row with no `approval` is governed exactly when a certification file exists for it (a missing file on
    an unusable id counts as governed, so it is refused). A human approval reference keeps the gates path. An automated
    reference, or one that is not a string, is always governed."""
    rule_id = str(rule.get("id", "?"))
    approval = rule.get("approval")
    if certified_ref(rule) or origin_requires_certification(rule):
        return True, approval
    if approval is None:
        path = certification_path(tree_root, rule_id)
        return path is None or path.exists() or path.is_symlink(), None
    if isinstance(approval, str) and not approval.lower().startswith(AUTO_APPROVAL_PREFIX):
        return False, approval
    return True, approval


def _reference_of(record: dict) -> str:
    return f"{cert.REFERENCE_PREFIX}:{record.get('policy_version')}:{record.get('record_digest')}"


_VERIFY_CACHE = {}  # key -> findings; per process, never persisted


def confirmation_path(tree_root, rule_id):
    """``<tree>/confirmations/<rule_id>.json``, or None when the id cannot name a file (fail closed)."""
    if not isinstance(rule_id, str) or not RULE_FILE.match(rule_id) or ".." in rule_id:
        return None
    return Path(tree_root) / CONFIRMATION_DIR / f"{rule_id}.json"


def _read_confirmation(rule_id, path):
    """``(record, finding)``: the parsed machine confirmation, or a finding naming why it cannot be read."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, _finding(rule_id, CERT_GATE, CONFIRMATION_UNREADABLE, "machine confirmation is not readable JSON")
    if not isinstance(record, dict):
        return None, _finding(rule_id, CERT_GATE, CONFIRMATION_UNREADABLE, "machine confirmation is not an object")
    return record, None


def confirmed_class(rule, tree_root, kb, index, snapshot_dir) -> tuple:
    """``(change_class, findings)``: the change class a certification is verified against.

    The class is DERIVED: it is the `derived_class` of a machine confirmation that verifies (L1, `update/
    machine_confirmation.verify`, recomputed from the release tree: the witness is re-proved, the rule row and the evidence
    rows are bound by digest). The record's own `change_class` is never read here. Without a verifying confirmation no
    class is established and a governed row is refused (fail closed). L2 (the retained blobs re-proved) is run by
    `source_problems`, at build step 9 and at update pre-activation, where the blobs exist."""
    rule_id = str(rule.get("id", "?"))
    path = confirmation_path(tree_root, rule_id)
    if path is None or not path.is_file():
        return None, [_finding(rule_id, CERT_GATE, CONFIRMATION_MISSING,
                               "no verified machine confirmation establishes the change class; a record's own class "
                               "is never trusted")]
    record, problem = _read_confirmation(rule_id, path)
    if problem is not None:
        return None, [problem]
    rows = [kb.evidence[eid] for eid in rule.get("evidence") or [] if isinstance(eid, str) and eid in kb.evidence]
    verdict = mc.verify(record, rule_row=rule, evidence_rows=rows)
    if not verdict.ok:
        codes = ", ".join(sorted({str(code) for code, _ in verdict.problems}))
        return None, [_finding(rule_id, CERT_GATE, CONFIRMATION_INVALID,
                               f"machine confirmation does not verify ({codes})")]
    return verdict.derived_class, []


def source_problems(tree_root, rule_id, blob_root) -> list:
    """L2: the blobs of a machine confirmation, read from `blob_root` (the build's blob store), rehash to the record and
    re-prove to the same witness digest, byte for byte. Returns ``[(code, detail)]``; empty when L2 holds. A missing or
    tampered blob is a problem (fail closed). Callers pass L2 only where a blob store exists (build, update)."""
    path = confirmation_path(tree_root, rule_id)
    if path is None or not path.is_file():
        return [("confirmation-missing", "no machine confirmation to re-prove")]
    record, problem = _read_confirmation(str(rule_id), path)
    if problem is not None:
        return [("confirmation-unreadable", problem["detail"])]
    if not isinstance(record.get("sources"), list):
        return [("confirmation-unreadable", "machine confirmation names no sources")]
    store, data = BlobStore(blob_root), {}
    for item in record["sources"]:
        side = item.get("side") if isinstance(item, dict) else None
        if side not in ("from", "to"):
            continue
        try:
            data[side] = store.get(item["blob_sha256"])
        except (SourceError, KeyError, TypeError, ValueError, OSError):
            return [("blob-missing", f"{side} blob is not in the blob store")]
    return list(mc.verify_sources(record, data).problems)


def _reset_trust_cache_for_tests() -> None:
    """TEST ONLY: drop cached certification verdicts."""
    _VERIFY_CACHE.clear()


def _verify_key(rule, evidence_rows, record, conditions, executor, change_class, confirmation_verified):
    """Everything a verdict depends on. Any change in any component is a different key. None when not keyable."""
    try:
        live = executor.transformer_identity(record["template_id"])
        return (digest_obj(rule), digest_obj(record), digest_obj(list(evidence_rows)), digest_obj(conditions),
                digest_obj(live), id(executor), change_class, confirmation_verified)
    except (CanonicalError, cert.CertificationError, KeyError, TypeError, ValueError):
        return None


def _verify_record(rule, evidence_rows, record, conditions, change_class, confirmation_verified) -> list:
    """`cert.verify` with a per-process cache. `change_class` is the CONFIRMED class (see `confirmed_class`), never the
    record's own `change_class`. The record is verified again whenever any input changes."""
    kwargs = {"source_confidentiality": conditions, "change_class": change_class,
              "confirmation_verified": confirmation_verified}
    try:
        executor = cert.trusted_executor()
    except cert.CertificationError:
        return cert.verify(rule, evidence_rows, record, **kwargs)
    key = _verify_key(rule, evidence_rows, record, conditions, executor, change_class, confirmation_verified)
    if key is not None and key in _VERIFY_CACHE:
        return list(_VERIFY_CACHE[key])
    findings = cert.verify(rule, evidence_rows, record, **kwargs)
    if key is not None:
        _VERIFY_CACHE[key] = list(findings)
    return findings


def _certification_findings(rule, tree_root, evidence_rows, index, approval, *, kb, snapshot_dir=None,
                            automated_required=False) -> list:
    rule_id = str(rule.get("id", "?"))
    if automated_required and not (isinstance(approval, str) and approval.lower().startswith(AUTO_APPROVAL_PREFIX)):
        return [_finding(rule_id, CERT_GATE, CERT_APPROVAL_MISSING,
                         "origin requires an automated approval reference (auto-cert:) that names the record")]
    path = certification_path(tree_root, rule_id)
    if path is None:
        return [_finding(rule_id, CERT_GATE, CERT_MISSING, "rule id cannot name a certification record")]
    if not path.is_file():
        return [_finding(rule_id, CERT_GATE, CERT_MISSING,
                         "approval is automated but the release has no certification record")]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [_finding(rule_id, CERT_GATE, CERT_UNREADABLE, "certification record is not readable JSON")]
    if not isinstance(record, dict):
        return [_finding(rule_id, CERT_GATE, CERT_UNREADABLE, "certification record is not an object")]
    if approval is not None and approval != _reference_of(record):
        return [_finding(rule_id, CERT_GATE, CERT_APPROVAL_MISMATCH,
                         "approval reference does not match the certification record")]
    change_class, class_findings = confirmed_class(rule, tree_root, kb, index, snapshot_dir)
    if class_findings:
        return class_findings
    findings = []
    # A non-None class comes only from a verified confirmation, so the GENERATED gate of certification may pass.
    for item in _verify_record(rule, evidence_rows, record, cert.source_confidentiality_from_index(index),
                               change_class, confirmation_verified=True):
        code = CERT_EXECUTOR_MISSING_CODE if item["code"] == cert.EXECUTOR_MISSING else CERT_VERIFY_FAILED
        findings.append(_finding(rule_id, CERT_GATE, code, f"{item['code']} ({item['field'] or 'record'}): "
                                                           f"{item['detail']}"))
    return findings


def fix_row_trusted(rule_row, tree_root, evidence_rows, index, *, kb, snapshot_dir=None, context=None,
                    inherit=INHERITED_TRUST_RECORDABLE) -> tuple:
    """``(trusted, findings)`` for one FIX_ENABLED row. The single trust predicate for every trust boundary.

    `tree_root` is the knowledge tree the row belongs to (`<release>/knowledge`). `evidence_rows` are the evidence records
    the row links, with their ids. `index` is the verified provenance index (`load_provenance_index`, None when unknown).
    `kb` is the loaded knowledge base the row is in (gate 4 and gate 1 read it). `context` is `rule_gate_context(kb)`,
    optional, so that a caller evaluating many rows computes it once. Findings are gate findings (gates 1 to 5) or
    certification findings (gate 6, codes `cert-*`). An untrusted row always has at least one finding."""
    if not isinstance(rule_row, dict):
        return False, [_finding("?", 0, "row-not-mapping", "rule row is not a mapping")]
    rule_id = str(rule_row.get("id", "?"))
    if rule_row.get("maturity") != FIX_ENABLED:
        return False, [_finding(rule_id, 0, "not-fix-enabled", "only a FIX_ENABLED row can be trusted")]
    if inherit and is_inherited_builtin(rule_row):
        return True, []
    snapshot_dir = snapshot_dir if snapshot_dir is not None else Path(tree_root).resolve().parent / "snapshots"
    context = context if context is not None else rule_gate_context(kb)
    findings = _rule_findings(rule_row, kb, index, snapshot_dir, context)
    governed, approval = _governed(rule_row, tree_root)
    if not governed:
        return not findings, findings
    if findings:
        return False, findings
    cert_findings = _certification_findings(rule_row, tree_root, evidence_rows, index, approval, kb=kb,
                                            snapshot_dir=snapshot_dir,
                                            automated_required=origin_requires_certification(rule_row))
    return not cert_findings, cert_findings


def package_fix_findings(tree_root, *, inherit=INHERITED_TRUST_RECORDABLE) -> tuple:
    """``(findings, inherited_rule_ids, baseline_digest)`` for the FIX_ENABLED rows of a staged package tree (P10).

    Every FIX_ENABLED row goes through `fix_row_trusted`, built-in rows included. With `inherit` (D3, off by default, see
    INHERITED_TRUST_RECORDABLE) a shipped row is accepted by byte identity with the verified baseline and listed in
    `inherited_rule_ids`; otherwise it is judged by gates 1 to 5 exactly as before. Any other row is judged by gates 1 to 5
    and, when certification governs it, by its record."""
    tree = Path(tree_root)
    kb = load_knowledge(tree)
    index = load_provenance_index(tree)
    snapshot_dir = tree.resolve().parent / "snapshots"
    context = rule_gate_context(kb)
    baseline = shipped_baseline_digest()
    findings, inherited = [], []
    for rule in kb.rules:
        if not isinstance(rule, dict) or rule.get("maturity") != FIX_ENABLED:
            continue
        evidence_rows = [kb.evidence[eid] for eid in rule.get("evidence") or []
                         if isinstance(eid, str) and eid in kb.evidence]
        trusted, found = fix_row_trusted(rule, tree, evidence_rows, index, kb=kb, snapshot_dir=snapshot_dir,
                                         context=context, inherit=inherit)
        if inherit and trusted and is_inherited_builtin(rule):
            inherited.append(str(rule.get("id")))
        findings += found
    return findings, sorted(set(inherited)), baseline
